# nexussentry/agents/scout.py
"""
Agent A — The Scout
━━━━━━━━━━━━━━━━━━━
Receives a high-level user goal and decomposes it into
3-5 concrete, actionable sub-tasks with explicit dependencies.

Role in the swarm: First contact. Task decomposition specialist.
Provider preference: Gemini (fast, cheap decomposition)
"""

import logging
from typing import Optional

from langchain_core.output_parsers import JsonOutputParser
from nexussentry.providers.llm_provider import get_provider
from nexussentry.utils.response_cache import get_cache

logger = logging.getLogger("Scout")

SCOUT_SYSTEM = """You are The Scout — a master task decomposer.

When given a high-level goal, break it into 3-5 concrete sub-tasks with dependency metadata.
Each sub-task must be:
- Self-contained (can be worked on independently)
- Specific (not vague like "improve code")
- Actionable (a developer could start immediately)

Use dependency-based planning:
- Include "depends_on": [] for tasks with no prerequisites
- Include "depends_on": [id, ...] for tasks that require earlier tasks
- Prefer parallelizable tasks when feasible

Respond ONLY with valid JSON — no preamble, no markdown:
{
  "goal_summary": "one sentence summary",
  "sub_tasks": [
        {"id": 1, "task": "specific task description", "priority": "high/medium/low", "depends_on": []}
  ],
  "estimated_complexity": "simple/medium/complex",
  "complexity_signals": {
    "requires_multi_file_changes": true/false,
    "involves_external_apis": true/false,
    "security_sensitive": true/false,
    "estimated_tokens_needed": 2000
  }
}"""

SINGLE_FILE_CONSTRAINT = """
HARD CONSTRAINT — SINGLE FILE MODE:
The user requires ALL output in a single file: {entrypoint}.
Do NOT create separate CSS, JS, test, or helper files.
Do NOT decompose into tasks that produce separate files.

Collapse all work into a LINEAR CHAIN of at most 2 tasks:
  1. Implement the complete {entrypoint} with ALL HTML, CSS (inline <style>), and JS (inline <script>)
  2. Validate/refine the same {entrypoint}

The ONLY allowed output file is: {entrypoint}
Do NOT emit tasks for: separate stylesheets, separate scripts, test files, or config files.
"""


class ScoutAgent:
    """Receives user goal → decomposes into sub-tasks."""

    def decompose(self, user_goal: str, tracer=None, goal_contract=None) -> dict:
        if tracer:
            tracer.log("Scout", "decompose_start", {"goal": user_goal})

        cache = get_cache()
        provider = get_provider()
        provider_name = provider.get_provider_for_agent("scout")

        # Include contract fingerprint in cache key to bust stale decompositions
        contract_fp = goal_contract.fingerprint() if goal_contract else "none"
        cache_key = f"scout::{contract_fp}::{user_goal}"
        cached = cache.get(cache_key, model=provider_name)
        if cached is not None:
            print(f"\n🔍 Scout (cached) decomposed '{cached.get('goal_summary', '...')}':")
            for t in cached.get("sub_tasks", []):
                print(f"   [{t['priority'].upper()}] {t['id']}. {t['task']}")
            if tracer:
                tracer.log("Scout", "decompose_done", {**cached, "from_cache": True, "provider": "cache"})
            return cached

        # Build system prompt with contract constraints
        system_prompt = SCOUT_SYSTEM
        if goal_contract and goal_contract.single_file:
            entrypoint = goal_contract.preferred_entrypoint or "index.html"
            system_prompt += "\n\n" + SINGLE_FILE_CONSTRAINT.format(entrypoint=entrypoint)

        try:
            raw_text = provider.chat(
                system=system_prompt,
                user_msg=user_goal,
                max_tokens=1000,
                agent_name="scout"
            )

            # Robust JSON extraction — handle markdown-wrapped responses
            result = self._parse_json_response(raw_text)

            # v3.0: Ensure complexity_signals exist with defaults
            result.setdefault("complexity_signals", {})
            signals = result["complexity_signals"]
            signals.setdefault("requires_multi_file_changes", len(result.get("sub_tasks", [])) > 2)
            signals.setdefault("involves_external_apis", False)
            signals.setdefault("security_sensitive", False)
            signals.setdefault("estimated_tokens_needed", 2000)

            # Post-process: enforce single-file contract
            if goal_contract and goal_contract.single_file:
                result = self._enforce_single_file_contract(result, goal_contract)

            print(f"\n🔍 Scout decomposed '{result['goal_summary']}' (via {provider_name}):")
            for t in result["sub_tasks"]:
                print(f"   [{t['priority'].upper()}] {t['id']}. {t['task']}")

            # Cache for demo reliability
            cache.put(cache_key, result, model=provider_name)

            if tracer:
                tracer.log("Scout", "decompose_done", {**result, "provider": provider_name})

            return result

        except Exception as e:
            logger.error(f"Scout decomposition failed: {e}")
            # Graceful fallback — return a single-task decomposition
            if goal_contract and goal_contract.single_file:
                entrypoint = goal_contract.preferred_entrypoint or "index.html"
                fallback = {
                    "goal_summary": user_goal[:100],
                    "sub_tasks": [
                        {"id": 1, "task": f"Implement complete {entrypoint} with inline CSS and JS", "priority": "high", "depends_on": []},
                        {"id": 2, "task": f"Validate and refine {entrypoint}", "priority": "high", "depends_on": [1]},
                    ],
                    "estimated_complexity": "medium"
                }
            else:
                fallback = {
                    "goal_summary": user_goal[:100],
                    "sub_tasks": [
                        {"id": 1, "task": user_goal, "priority": "high", "depends_on": []}
                    ],
                    "estimated_complexity": "medium"
                }
            print(f"\n🔍 Scout (fallback mode): Using original goal as single task")
            if tracer:
                tracer.log("Scout", "decompose_fallback", {"error": str(e)})
            return fallback

    def _enforce_single_file_contract(self, result: dict, goal_contract) -> dict:
        """Post-process Scout output to enforce single-file constraints."""
        entrypoint = goal_contract.preferred_entrypoint or "index.html"

        # Collapse to at most 2 tasks in a linear chain
        sub_tasks = result.get("sub_tasks", [])
        if len(sub_tasks) > 2:
            # Merge all tasks into a 2-task linear chain
            all_task_descs = [t.get("task", "") for t in sub_tasks]
            merged_desc = f"Implement complete {entrypoint}: " + "; ".join(all_task_descs)
            sub_tasks = [
                {"id": 1, "task": merged_desc[:300], "priority": "high", "depends_on": []},
                {"id": 2, "task": f"Validate and refine {entrypoint}", "priority": "high", "depends_on": [1]},
            ]
            result["sub_tasks"] = sub_tasks

        # Ensure linear dependency chain
        for i, task in enumerate(result["sub_tasks"]):
            if i == 0:
                task["depends_on"] = []
            else:
                task["depends_on"] = [result["sub_tasks"][i - 1]["id"]]

        return result

    def _parse_json_response(self, text: str) -> dict:
        parsed = JsonOutputParser().parse(text)
        if isinstance(parsed, dict):
            return parsed
        raise ValueError(f"Could not parse JSON from response: {text[:200]}")
