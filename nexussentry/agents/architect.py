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
import re
import logging

from nexussentry.providers.llm_provider import get_provider
from nexussentry.utils.response_cache import get_cache

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


class ArchitectAgent:
    """Researches context + creates an execution plan for the builder pipeline."""

    def plan(self, sub_task: str, feedback: str = "",
             context: str = "", task_priority: str = "medium",
             estimated_complexity: str = "medium", tracer=None) -> dict:
        if tracer:
            tracer.log("Architect", "plan_start", {"task": sub_task})

        cache = get_cache()
        provider = get_provider()
        provider_name = provider.get_provider_for_agent("architect")
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

        user_msg = f"Sub-task: {sub_task}"
        if feedback:
            user_msg += f"\n\nPrevious attempt failed. Critic feedback:\n{feedback}"
        user_msg += f"\n\nTask priority: {task_priority}"
        user_msg += f"\nEstimated complexity: {estimated_complexity}"
        if context:
            user_msg += f"\n\nContext:\n{context}"

        try:
            raw_text = provider.chat(
                system=ARCHITECT_SYSTEM,
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
            fallback = {
                "plan_summary": f"Direct execution: {sub_task[:80]}",
                "approach": "Execute the task directly with standard tools",
                "files_to_read": [],
                "files_to_modify": [],
                "commands_to_run": [],
                "success_criteria": "Task completes successfully",
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

    def _build_builder_dispatch(self, plan: dict, task_priority: str,
                                estimated_complexity: str) -> dict:
        """Create a lean builder dispatch contract for the next pipeline stage."""
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
        """Robustly parse JSON from LLM response."""
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        json_match = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', text, re.DOTALL)
        if json_match:
            try:
                return json.loads(json_match.group(1))
            except json.JSONDecodeError:
                pass

        json_match = re.search(r'\{.*\}', text, re.DOTALL)
        if json_match:
            try:
                return json.loads(json_match.group(0))
            except json.JSONDecodeError:
                pass

        raise ValueError(f"Could not parse JSON from response: {text[:200]}")
