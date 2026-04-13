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
Be specific about files, functions, line numbers when relevant.

Respond ONLY with valid JSON — no preamble, no markdown:
{
  "plan_summary": "what we're doing and why",
  "approach": "detailed technical approach",
  "files_to_read": ["file1.py"],
  "files_to_modify": ["file2.py"],
  "commands_to_run": ["pytest tests/", "..."],
  "success_criteria": "how we know it worked",
  "risks": ["potential issue 1"]
}"""

SINGLE_FILE_ARCHITECT_CONSTRAINT = """
HARD CONSTRAINT — SINGLE FILE MODE:
The user requires ALL output in a single file: {entrypoint}.
You MUST set files_to_modify to ONLY ["{entrypoint}"].
Do NOT plan separate CSS, JS, test, or helper files.
All CSS must be inline in <style> tags. All JS must be inline in <script> tags.
No external asset references are allowed.
builder_count MUST be 1.
"""


class ArchitectAgent:
    """Researches context + creates an execution plan for the builder pipeline."""

    def plan(self, sub_task: str, feedback: str = "",
             context: str = "", task_priority: str = "medium",
             estimated_complexity: str = "medium", tracer=None,
             goal_contract=None) -> dict:
        if tracer:
            tracer.log("Architect", "plan_start", {"task": sub_task})

        cache = get_cache()
        provider = get_provider()
        provider_name = provider.get_provider_for_agent("architect")

        # Include contract fingerprint in cache key
        contract_fp = goal_contract.fingerprint() if goal_contract else "none"
        cache_key = (
            f"plan::{contract_fp}::{sub_task}::priority={task_priority}::complexity={estimated_complexity}"
            f"::feedback={feedback[:50]}"
        )

        # Check cache
        cached = cache.get(cache_key, model=provider_name)
        if cached is not None:
            print(f"\n🏗️  Architect (cached) plan: {cached.get('plan_summary', '...')}")
            if tracer:
                tracer.log("Architect", "plan_done", {**cached, "from_cache": True, "provider": "cache"})
            return cached

        # Build system prompt with contract constraints
        system_prompt = ARCHITECT_SYSTEM
        if goal_contract and goal_contract.single_file:
            entrypoint = goal_contract.preferred_entrypoint or "index.html"
            system_prompt += "\n\n" + SINGLE_FILE_ARCHITECT_CONSTRAINT.format(entrypoint=entrypoint)

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

        user_msg = PromptTemplate.from_template(
            """Sub-task: {sub_task}

Previous attempt failed. Critic feedback:
{feedback}

Task priority: {task_priority}
Estimated complexity: {estimated_complexity}

Context:
{context}{few_shot}{anti_patterns}""",
        ).format(
            sub_task=sub_task,
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
            plan.setdefault("files_to_read", [])
            plan.setdefault("files_to_modify", [])
            plan.setdefault("commands_to_run", [])
            plan.setdefault("success_criteria", "Task completes without errors")
            plan.setdefault("risks", [])

            # Enforce single-file contract post-hoc
            if goal_contract and goal_contract.single_file:
                plan = self._enforce_single_file_plan(plan, goal_contract)

            plan.setdefault(
                "builder_dispatch",
                self._build_builder_dispatch(
                    plan=plan,
                    task_priority=task_priority,
                    estimated_complexity=estimated_complexity,
                    goal_contract=goal_contract,
                ),
            )

            cache.put(cache_key, plan, model=provider_name)

            if tracer:
                tracer.log("Architect", "plan_done", {**plan, "provider": provider_name})

            return plan

        except Exception as e:
            logger.error(f"Architect planning failed: {e}")

            # Build fallback with contract awareness
            if goal_contract and goal_contract.single_file:
                entrypoint = goal_contract.preferred_entrypoint or "index.html"
                files = [entrypoint]
            else:
                files = []

            fallback = {
                "plan_summary": f"Direct execution: {sub_task[:80]}",
                "approach": "Execute the task directly with standard tools",
                "files_to_read": [],
                "files_to_modify": files,
                "commands_to_run": [],
                "success_criteria": "Task completes successfully",
                "risks": ["Using fallback plan — LLM planning unavailable"]
            }
            fallback["builder_dispatch"] = self._build_builder_dispatch(
                plan=fallback,
                task_priority=task_priority,
                estimated_complexity=estimated_complexity,
                goal_contract=goal_contract,
            )
            print(f"\n🏗️  Architect (fallback): {fallback['plan_summary']}")
            if tracer:
                tracer.log("Architect", "plan_fallback", {"error": str(e)})
            return fallback

    def _enforce_single_file_plan(self, plan: dict, goal_contract) -> dict:
        """Override plan to respect single-file contract."""
        entrypoint = goal_contract.preferred_entrypoint or "index.html"
        allowed = set(goal_contract.allowed_output_files) if goal_contract.allowed_output_files else {entrypoint}

        # Force files_to_modify to only allowed files
        plan["files_to_modify"] = [f for f in plan.get("files_to_modify", []) if f in allowed]
        if not plan["files_to_modify"]:
            plan["files_to_modify"] = [entrypoint]

        return plan

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

    def _build_builder_dispatch(self, plan: dict, task_priority: str,
                                estimated_complexity: str,
                                goal_contract=None) -> dict:
        """Create a lean builder dispatch contract for the next pipeline stage."""

        # Single-file mode forces exactly 1 builder
        if goal_contract and goal_contract.single_file:
            return {
                "task_size": "small",
                "builder_count": 1,
                "builder_slots": 1,
                "parallel_groups": 1,
                "merge_strategy": "direct_merge",
            }

        task_size = self._classify_task_size(plan, task_priority, estimated_complexity)

        if task_size == "small":
            builder_count = 2
            builder_slots = 2
            parallel_groups = 1
            merge_strategy = "direct_merge"
        elif task_size == "medium":
            builder_count = 3
            builder_slots = 3
            parallel_groups = 2
            merge_strategy = "integrator_then_qa"
        else:
            builder_count = 5
            builder_slots = 5
            parallel_groups = 3
            merge_strategy = "integrator_then_qa_then_critic"

        return {
            "task_size": task_size,
            "builder_count": builder_count,
            "builder_slots": builder_slots,
            "parallel_groups": parallel_groups,
            "merge_strategy": merge_strategy,
        }

    def _parse_json_response(self, text: str) -> dict:
        parsed = JsonOutputParser().parse(text)
        if isinstance(parsed, dict):
            return parsed
        raise ValueError(f"Could not parse JSON from response: {text[:200]}")
