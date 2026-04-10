# nexussentry/agents/scout.py
"""
Agent A — The Scout
━━━━━━━━━━━━━━━━━━━
Receives a high-level user goal and decomposes it into
3-5 concrete, sequential, actionable sub-tasks.

Role in the swarm: First contact. Task decomposition specialist.
Provider preference: Gemini (fast, cheap decomposition)
"""

import json
import logging

from nexussentry.providers.llm_provider import get_provider
from nexussentry.utils.response_cache import get_cache

logger = logging.getLogger("Scout")

SCOUT_SYSTEM = """You are The Scout — a master task decomposer.

When given a high-level goal, break it into 3-5 concrete, sequential sub-tasks.
Each sub-task must be:
- Self-contained (can be worked on independently)
- Specific (not vague like "improve code")
- Actionable (a developer could start immediately)

Respond ONLY with valid JSON — no preamble, no markdown:
{
  "goal_summary": "one sentence summary",
  "sub_tasks": [
    {"id": 1, "task": "specific task description", "priority": "high/medium/low"}
  ],
  "estimated_complexity": "simple/medium/complex"
}"""


class ScoutAgent:
    """Receives user goal → decomposes into sub-tasks."""

    def decompose(self, user_goal: str, tracer=None) -> dict:
        if tracer:
            tracer.log("Scout", "decompose_start", {"goal": user_goal})

        cache = get_cache()
        provider = get_provider()
        provider_name = provider.get_provider_for_agent("scout")

        # Check cache first
        cache_key = f"scout::{user_goal}"
        cached = cache.get(cache_key, model=provider_name)
        if cached is not None:
            print(f"\n🔍 Scout (cached) decomposed '{cached.get('goal_summary', '...')}':") 
            for t in cached.get("sub_tasks", []):
                print(f"   [{t['priority'].upper()}] {t['id']}. {t['task']}")
            if tracer:
                tracer.log("Scout", "decompose_done", {**cached, "from_cache": True, "provider": "cache"})
            return cached

        try:
            raw_text = provider.chat(
                system=SCOUT_SYSTEM,
                user_msg=user_goal,
                max_tokens=1000,
                agent_name="scout"
            )

            # Robust JSON extraction — handle markdown-wrapped responses
            result = self._parse_json_response(raw_text)

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
            fallback = {
                "goal_summary": user_goal[:100],
                "sub_tasks": [
                    {"id": 1, "task": user_goal, "priority": "high"}
                ],
                "estimated_complexity": "medium"
            }
            print(f"\n🔍 Scout (fallback mode): Using original goal as single task")
            if tracer:
                tracer.log("Scout", "decompose_fallback", {"error": str(e)})
            return fallback

    def _parse_json_response(self, text: str) -> dict:
        """
        Robustly parse JSON from LLM response.
        Handles cases where the LLM wraps JSON in markdown code blocks.
        """
        # Try direct parse first
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # Try extracting from markdown code block
        import re
        json_match = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', text, re.DOTALL)
        if json_match:
            try:
                return json.loads(json_match.group(1))
            except json.JSONDecodeError:
                pass

        # Try finding JSON object pattern
        json_match = re.search(r'\{.*\}', text, re.DOTALL)
        if json_match:
            try:
                return json.loads(json_match.group(0))
            except json.JSONDecodeError:
                pass

        raise ValueError(f"Could not parse JSON from response: {text[:200]}")
