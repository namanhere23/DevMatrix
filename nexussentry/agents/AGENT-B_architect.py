# nexussentry/agents/architect.py
"""
Agent B — The Architect
━━━━━━━━━━━━━━━━━━━━━━
Takes a sub-task from the Scout and creates a precise,
detailed execution plan for the builder pipeline.

Role in the swarm: Technical planner. Research & strategy.
Provider preference: OpenRouter (diverse model access)
"""

import json
import logging

from langchain_core.output_parsers import JsonOutputParser
from langchain_core.prompts import PromptTemplate

from nexussentry.providers.llm_provider import get_provider
from nexussentry.utils.response_cache import get_cache
from nexussentry.memory.feedback_store import SwarmFeedbackStore
from nexussentry.memory.episodic_memory import EpisodicMemory

logger = logging.getLogger("Architect")

ARCHITECT_SYSTEM = """You are The Architect — a senior technical planner.

Given a sub-task and context, create a precise execution plan.
Your plan will be handed to builder agents who will implement it.
Do not invent unsupported assumptions. Keep plan relevant to prompt and context.
Identify execution order needs and technical area clearly.

Execution profile policy:
- You MUST decide execution_profile from task logic, file coupling, and dependency risk.
- Use "parallel" only when file groups can be built independently with low merge risk.
- Use "sequential" when ordering/coupling matters (shared files, stateful edits, migrations, risky refactors).
- Include a brief justification in builder_requirements.

Respond ONLY with valid JSON — no preamble, no markdown:
{
    "plan_summary": "short plan summary",
    "technical_area": "frontend/backend/fullstack/infrastructure/security/data",
    "execution_profile": "parallel/sequential",
    "approach": "technical approach",
  "files_to_read": ["file1.py"],
  "files_to_modify": ["file2.py"],
  "commands_to_run": ["pytest tests/", "..."],
  "success_criteria": "how we know it worked",
    "builder_requirements": ["critical requirement for builder"],
    "assumptions": ["explicit assumption tied to prompt/context"],
  "risks": ["potential issue 1"]
}"""


USER_MSG_TEMPLATE = PromptTemplate.from_template(
    """Sub-task: {sub_task}
    Sub-task metadata: {sub_task_meta}

    Previous attempt failed. Critic feedback:
    {feedback}

    Task priority: {task_priority}
    Estimated complexity: {estimated_complexity}

    Context:
    {context}{few_shot}{anti_patterns}"""
)


class ArchitectAgent:
    """Researches context + creates an execution plan for the builder pipeline."""

    json_parser = JsonOutputParser()

    def plan(self, sub_task: str, feedback: str = "",
             context: str = "", task_priority: str = "medium",
             estimated_complexity: str = "medium", tracer=None,
             sub_task_meta: dict | None = None) -> dict:
        """Create execution plan for a sub-task (model-driven, no rigid contracts)."""
        if tracer:
            tracer.log("Architect", "plan_start", {"task": sub_task})

        cache = get_cache()
        provider = get_provider()
        provider_name = provider.get_provider_for_agent("architect")

        # Cache key without contract fingerprint (model handles all decisions)
        cache_key = (
            f"plan::{sub_task}::priority={task_priority}::complexity={estimated_complexity}"
            f"::feedback={feedback[:50]}"
        )

        # Check cache
        cached = cache.get(cache_key, model=provider_name)
        if cached is not None:
            print(f"\n🏗️  Architect (cached) plan: {cached.get('plan_summary', '...')}")
            if tracer:
                tracer.log("Architect", "plan_done", {**cached, "from_cache": True, "provider": "cache"})
            return cached

        # Build system prompt (model-driven)
        system_prompt = ARCHITECT_SYSTEM

        # v3.0: Retrieve similar past successes from episodic memory
        few_shot_block = ""
        try:
            episodic = EpisodicMemory()
            similar = episodic.retrieve_similar(sub_task, n=3, min_similarity=0.72)
            if similar:
                few_shot_block = "\n\nSIMILAR PAST SOLUTIONS (use as inspiration, not copy):\n"
                for ep in similar[:2]:  # Max 2 to save tokens
                    few_shot_block += (
                        f"Past task (similarity={ep['similarity']}): {ep['past_task'][:150]}\n"
                        f"Successful approach: {ep['approach'][:200]}\n"
                        f"Files modified: {ep['files_modified']}\n---\n"
                    )
        except Exception:
            pass  # Episodic memory is optional

        # v3.0: Inject anti-patterns from feedback store
        anti_pattern_block = ""
        try:
            feedback_store = SwarmFeedbackStore()
            negative_examples = feedback_store.get_negative_examples_for_task(sub_task)
            if negative_examples:
                anti_examples = "\n".join([
                    f"APPROACH TO AVOID: {ex['failed_approach']}\n"
                    f"REASON IT FAILED: {', '.join(ex['failure_reason']) if isinstance(ex['failure_reason'], list) else ex['failure_reason']}"
                    for ex in negative_examples
                ])
                anti_pattern_block = f"\n\nANTI-PATTERNS (these approaches failed previously on similar tasks):\n{anti_examples}"
        except Exception:
            pass  # Feedback store is optional

        user_msg = USER_MSG_TEMPLATE.format(
            sub_task=sub_task,
            sub_task_meta=json.dumps(sub_task_meta or {}, ensure_ascii=False),
            feedback=feedback or "none",
            task_priority=task_priority,
            estimated_complexity=estimated_complexity,
            context=context or "none",
            few_shot=few_shot_block,
            anti_patterns=anti_pattern_block,
        )

        try:
            raw_text = provider.chat(
                system=system_prompt,
                user_msg=user_msg,
                max_tokens=1500,
                agent_name="architect"
            )

            plan = self._parse_json_response(raw_text)
            print(f"\n🏗️  Architect plan (via {provider_name}): {plan['plan_summary']}")

            # Ensure all expected keys exist with defaults
            plan.setdefault("approach", "Direct implementation")
            plan.setdefault("technical_area", self._infer_technical_area(sub_task, plan))
            plan["execution_profile"] = self._normalize_execution_profile(plan.get("execution_profile"))
            plan.setdefault("files_to_read", [])
            plan.setdefault("files_to_modify", [])
            plan.setdefault("commands_to_run", [])
            plan.setdefault("success_criteria", "Task completes without errors")
            plan.setdefault("builder_requirements", [])
            plan.setdefault("assumptions", [])
            plan.setdefault("risks", [])

            plan.setdefault(
                "builder_dispatch",
                self._build_builder_dispatch(
                    plan=plan,
                    task_priority=task_priority,
                    estimated_complexity=estimated_complexity,
                ),
            )

            cache.put(cache_key, plan, model=provider_name)

            if tracer:
                tracer.log("Architect", "plan_done", {**plan, "provider": provider_name})

            return plan

        except Exception as e:
            logger.error(f"Architect planning failed: {e}")

            # Build fallback (model-driven)
            files = []

            fallback = {
                "plan_summary": f"Direct execution: {sub_task[:80]}",
                "technical_area": self._infer_technical_area(sub_task, {}),
                "execution_profile": "sequential",
                "approach": "Execute the task directly with standard tools",
                "files_to_read": [],
                "files_to_modify": files,
                "commands_to_run": [],
                "success_criteria": "Task completes successfully",
                "builder_requirements": [],
                "assumptions": [],
                "risks": ["Using fallback plan — LLM planning unavailable"]
            }
            fallback["builder_dispatch"] = self._build_builder_dispatch(
                plan=fallback,
                task_priority=task_priority,
                estimated_complexity=estimated_complexity,
            )
            print(f"\n🏗️  Architect (fallback): {fallback['plan_summary']}")
            if tracer:
                tracer.log("Architect", "plan_fallback", {"error": str(e)})
            return fallback

    def _classify_task_size(self, plan: dict, task_priority: str, estimated_complexity: str) -> str:
        """Classify a task as small, medium, or large before builder dispatch."""
        files_to_modify = plan.get("files_to_modify", []) or []
        commands_to_run = plan.get("commands_to_run", []) or []
        risks = plan.get("risks", []) or []

        priority = (task_priority or "medium").lower()
        complexity = (estimated_complexity or "medium").lower()

        if (
            complexity == "complex"
            or priority == "high"
            or len(files_to_modify) >= 4
            or len(commands_to_run) >= 3
            or len(risks) >= 3
        ):
            return "large"

        if (
            complexity == "medium"
            or priority == "medium"
            or len(files_to_modify) >= 2
            or len(commands_to_run) >= 2
            or len(risks) >= 2
        ):
            return "medium"

        return "small"

    def _infer_technical_area(self, sub_task: str, plan: dict) -> str:
        text = f"{sub_task} {plan.get('approach', '')}".lower()
        if any(token in text for token in ["api", "server", "route", "backend", "database"]):
            return "backend"
        if any(token in text for token in ["ui", "frontend", "css", "html", "react", "component"]):
            return "frontend"
        if any(token in text for token in ["auth", "security", "xss", "sql injection"]):
            return "security"
        if any(token in text for token in ["schema", "migration", "query", "etl", "data"]):
            return "data"
        if any(token in text for token in ["docker", "kubernetes", "deploy", "ci", "infra"]):
            return "infrastructure"
        return "fullstack"

    def _normalize_execution_profile(self, value: str | None) -> str:
        """Accept only supported execution modes; do not infer policy heuristics here."""
        mode = str(value or "").strip().lower()
        if mode in {"parallel", "sequential"}:
            return mode
        return "sequential"

    def _build_builder_dispatch(self, plan: dict, task_priority: str,
                                estimated_complexity: str) -> dict:
        """Create builder dispatch metadata; prefer model values and only normalize bounds."""

        task_size = self._classify_task_size(plan, task_priority, estimated_complexity)

        dispatch_from_model = plan.get("builder_dispatch", {}) or {}
        model_count = dispatch_from_model.get("builder_count", plan.get("builder_count"))
        try:
            builder_count = int(model_count)
        except (TypeError, ValueError):
            # Fallback sizing only when model omitted the value.
            if task_size == "small":
                builder_count = 2
            elif task_size == "medium":
                builder_count = 3
            else:
                builder_count = 5

        builder_count = max(1, min(5, builder_count))
        builder_slots = builder_count
        parallel_groups = min(builder_count, 3)

        return {
            "task_size": task_size,
            "builder_count": builder_count,
            "builder_slots": builder_slots,
            "parallel_groups": parallel_groups,
            "execution_profile": plan.get("execution_profile", "sequential"),
        }

    def _parse_json_response(self, text: str) -> dict:
        """Parse JSON response using LangChain's class-level JsonOutputParser."""
        parsed = self.json_parser.parse(text)
        if isinstance(parsed, dict):
            return parsed
        raise ValueError(f"Could not parse JSON from response: {text[:200]}")
