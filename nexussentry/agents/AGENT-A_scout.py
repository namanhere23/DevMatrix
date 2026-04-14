# nexussentry/agents/scout.py
"""
Agent A — The Scout
━━━━━━━━━━━━━━━━━━━
Receives a high-level user goal and either:
  1. Decomposes code generation requests into 3-5 concrete, actionable sub-tasks
  2. Returns single "respond" task for knowledge queries

Role in the swarm: First contact. Query classifier & decomposition specialist.
Provider preference: Gemini (fast, cheap decomposition)
Shared Context: Emits execution_type as common pool for all downstream agents
"""

import logging
import re

from langchain_core.output_parsers import JsonOutputParser
from langchain_core.prompts import PromptTemplate
from nexussentry.providers.llm_provider import get_provider
from nexussentry.utils.response_cache import get_cache

logger = logging.getLogger("Scout")

# Detection patterns for query type
_FILE_GENERATION_KEYWORDS = [
    r"\bhtml\b", r"\bjavascript\b", r"\bjava\b", r"\bpython\b", r"\bc\+\+\b",
    r"\bcss\b", r"\breact\b", r"\bnode\b", r"\bapi\b", r"\bfunction\b",
    r"\bbuild\b", r"\bwrite\b", r"\bcode\b", r"\bimplementation\b", r"\bprovider",
    r"\bsite\b", r"\bapp\b", r"\bapplication\b", r"\bcomponent\b", r"\bendpoint\b",
    r"\bdashboard\b", r"\bcalculator\b", r"\btodo\b", r"\bform\b", r"\bui\b",
]

_KNOWLEDGE_KEYWORDS = [
    r"\bwhat\s+is\b", r"\bhow\s+does?\b", r"\bexplain\b", r"\bwhy\b", r"\btell\b",
    r"\bdefine\b", r"\bcomment\b", r"\bquestion\b", r"\bwho\b", r"\bwhere\b",
    r"\bsummarize\b", r"\bdescribe\b", r"\bconcept\b", r"\btheory\b", r"\bknowledge\b",
]

SCOUT_SYSTEM = """You are The Scout — a task decomposer and query classifier.

FIRST: Classify the goal as either GENERATION or KNOWLEDGE
  - GENERATION: code/files/artifacts need to be produced (HTML, APIs, components, etc.)
  - KNOWLEDGE: answer question or explain concept (no file output)
  - The system will handle KNOWLEDGE queries separately, so focus on GENERATION

FOR GENERATION TASKS:
Assess difficulty, scale sub-task count accordingly:
- easy   → 1-2 sub-tasks
- medium → 3-4 sub-tasks
- hard   → 5-7 sub-tasks

Each sub-task must be self-contained, specific, actionable.

Rules:
- STRICT JSON only
- Use minimal wording
- IDs must be sequential: 1..N
- Keep task text short (3-14 words)
- Use depends_on for real prerequisites only

Respond ONLY with valid JSON:
{
  "goal_summary": "short summary",
  "difficulty": "easy/medium/hard",
  "sub_tasks": [
    {"id": 1, "task": "short task", "priority": "high/medium/low", "depends_on": []}
  ],
  "estimated_complexity": "simple/medium/complex",
  "complexity_signals": {
    "requires_multi_file_changes": true/false,
    "involves_external_apis": true/false,
    "security_sensitive": true/false,
    "estimated_tokens_needed": 2000
  }
}"""


SCOUT_USER_PROMPT = PromptTemplate.from_template(
    """Goal: {user_goal}
Difficulty: {difficulty}
Target task count: {task_target}
Use strict JSON only. Keep wording short."""
)


class ScoutAgent:
    """Receives user goal → classifies & decomposes into sub-tasks OR returns knowledge response."""

    json_parser = JsonOutputParser()
    _HARD_PATTERNS = [
        r"\bauth\b", r"\bsecurity\b", r"\bpayment\b", r"\bdatabase\b",
        r"\bmicroservice\b", r"\bci/cd\b", r"\bkubernetes\b", r"\bdistributed\b",
        r"\bwebsocket\b", r"\bstream\b", r"\bqueue\b", r"\brole[- ]based\b",
    ]
    _EASY_PATTERNS = [
        r"\bsingle file\b", r"\bsmall\b", r"\bsimple\b", r"\blanding page\b",
        r"\btodo\b", r"\bfix typo\b", r"\brename\b", r"\bcss tweak\b",
    ]

    def decompose(self, user_goal: str, tracer=None) -> dict:
        """
        Analyze goal and decompose into sub-tasks (generation) or return knowledge response.
        
        No rigid contracts—Scout decides execution_type dynamically and emits it
        as part of shared context dict (execution_type becomes common pool for all agents).
        
        Model handles: file constraints, single/multi-file logic, output file decisions
        All hints are inferred from query text, no pre-determined contracts.
        """
        if tracer:
            tracer.log("Scout", "decompose_start", {"goal": user_goal})

        cache = get_cache()
        provider = get_provider()
        provider_name = provider.get_provider_for_agent("scout")
        
        # Step 1: Classify execution type (generation vs knowledge)
        execution_type = self._classify_execution_type(user_goal)
        
        # Step 2: For knowledge queries, return immediately with single "respond" task
        if execution_type == "knowledge":
            result = {
                "goal_summary": user_goal[:120],
                "execution_type": "knowledge",
                "difficulty": "simple",
                "sub_tasks": [
                    {
                        "id": 1,
                        "task": "Respond to user query",
                        "priority": "high",
                        "depends_on": []
                    }
                ],
                "estimated_complexity": "simple",
                "complexity_signals": {
                    "requires_multi_file_changes": False,
                    "involves_external_apis": False,
                    "security_sensitive": False,
                    "estimated_tokens_needed": 500
                }
            }
            print(f"\n❓ Scout classified as KNOWLEDGE RESPONSE: {user_goal[:80]}...")
            if tracer:
                tracer.log("Scout", "decompose_done", {**result, "provider": "knowledge_shortcut"})
            return result

        # Step 3: For generation tasks, proceed with full decomposition
        difficulty = self._classify_difficulty(user_goal)
        task_target = self._task_target_for_difficulty(difficulty)

        # Use execution_type + difficulty for cache key to ensure consistency
        cache_key = f"scout::{execution_type}::{difficulty}::{user_goal}"
        cached = cache.get(cache_key, model=provider_name)
        if cached is not None:
            cached["execution_type"] = "generation"  # Ensure field is set
            print(f"\n🔍 Scout (cached) decomposed '{cached.get('goal_summary', '...')}':")
            for t in cached.get("sub_tasks", []):
                print(f"   [{t['priority'].upper()}] {t['id']}. {t['task']}")
            if tracer:
                tracer.log("Scout", "decompose_done", {**cached, "from_cache": True, "provider": "cache"})
            return cached

        try:
            raw_text = provider.chat(
                system=SCOUT_SYSTEM,
                user_msg=self._build_user_prompt(user_goal, difficulty, task_target),
                max_tokens=1000,
                agent_name="scout"
            )

            # Robust JSON extraction
            result = self._parse_json_response(raw_text)
            result = self._normalize_result(result, user_goal, difficulty)
            
            # Ensure execution_type is set to "generation" for generation tasks
            result["execution_type"] = "generation"

            # v3.0: Ensure complexity_signals exist with defaults
            result.setdefault("complexity_signals", {})
            signals = result["complexity_signals"]
            signals.setdefault("requires_multi_file_changes", len(result.get("sub_tasks", [])) > 2)
            signals.setdefault("involves_external_apis", False)
            signals.setdefault("security_sensitive", False)
            signals.setdefault("estimated_tokens_needed", 2000)

            print(f"\n🔍 Scout decomposed '{result['goal_summary']}' ({difficulty}, via {provider_name}):")
            for t in result["sub_tasks"]:
                print(f"   [{t['priority'].upper()}] {t['id']}. {t['task']}")

            # Cache for demo reliability
            cache.put(cache_key, result, model=provider_name)

            if tracer:
                tracer.log("Scout", "decompose_done", {**result, "provider": provider_name})

            return result

        except Exception as e:
            logger.error(f"Scout decomposition failed: {e}")
            # Graceful fallback
            fallback = {
                "goal_summary": user_goal[:80],
                "execution_type": "generation",
                "difficulty": difficulty,
                "sub_tasks": [
                    {"id": 1, "task": user_goal, "priority": "high", "depends_on": []}
                ],
                "estimated_complexity": self._complexity_for_difficulty(difficulty),
                "complexity_signals": {
                    "requires_multi_file_changes": False,
                    "involves_external_apis": False,
                    "security_sensitive": False,
                    "estimated_tokens_needed": 2000
                }
            }
            print(f"\n🔍 Scout (fallback mode): Using original goal as single task")
            if tracer:
                tracer.log("Scout", "decompose_fallback", {"error": str(e)})
            return fallback

    def _classify_execution_type(self, user_goal: str) -> str:
        """
        Determine if user wants code/file generation or knowledge response.
        
        Model-driven based on keyword patterns, not rigid contracts.
        """
        goal_lower = (user_goal or "").lower()
        
        # Heuristic: count keyword hits
        generation_hits = sum(1 for p in _FILE_GENERATION_KEYWORDS if re.search(p, goal_lower))
        knowledge_hits = sum(1 for p in _KNOWLEDGE_KEYWORDS if re.search(p, goal_lower))
        
        # If goal has generation keywords and not strongly knowledge-focused: generation
        if generation_hits >= 1 and knowledge_hits <= 1:
            return "generation"
        
        # If goal starts with question words or is very short: knowledge
        if knowledge_hits >= 1 or len(goal_lower.split()) <= 5:
            return "knowledge"
        
        # Default: assume generation for longer, less question-like goals
        return "generation"

    def _build_user_prompt(self, user_goal: str, difficulty: str, task_target: int) -> str:
        """Format user prompt using LangChain PromptTemplate."""
        return SCOUT_USER_PROMPT.format(
            user_goal=user_goal,
            difficulty=difficulty,
            task_target=task_target,
        )

    def _classify_difficulty(self, user_goal: str) -> str:
        goal = (user_goal or "").lower()
        hard_hits = sum(1 for p in self._HARD_PATTERNS if re.search(p, goal))
        easy_hits = sum(1 for p in self._EASY_PATTERNS if re.search(p, goal))
        word_count = len(goal.split())

        if hard_hits >= 2 or word_count >= 45:
            return "hard"
        if easy_hits >= 1 and word_count <= 20 and hard_hits == 0:
            return "easy"
        return "medium"

    def _task_target_for_difficulty(self, difficulty: str) -> int:
        if difficulty == "easy":
            return 2
        if difficulty == "hard":
            return 5
        return 3

    def _complexity_for_difficulty(self, difficulty: str) -> str:
        if difficulty == "easy":
            return "simple"
        if difficulty == "hard":
            return "complex"
        return "medium"

    def _normalize_result(self, result: dict, user_goal: str, difficulty: str) -> dict:
        sub_tasks = result.get("sub_tasks", [])
        if not isinstance(sub_tasks, list):
            sub_tasks = []

        normalized = []
        for idx, task in enumerate(sub_tasks, start=1):
            task_text = str(task.get("task", "")).strip()
            if not task_text:
                continue
            dep_ids = task.get("depends_on", [])
            if isinstance(dep_ids, (int, str)):
                dep_ids = [dep_ids]
            clean_deps = []
            for dep in dep_ids:
                try:
                    dep_id = int(dep)
                    if dep_id > 0 and dep_id != idx:
                        clean_deps.append(dep_id)
                except (TypeError, ValueError):
                    continue
            normalized.append({
                "id": idx,
                "task": " ".join(task_text.split())[:160],
                "priority": str(task.get("priority", "medium")).lower(),
                "depends_on": sorted(set(clean_deps)),
            })

        if not normalized:
            normalized = [{
                "id": 1,
                "task": " ".join((user_goal or "task").split())[:160],
                "priority": "high",
                "depends_on": [],
            }]

        valid_ids = {task["id"] for task in normalized}
        for task in normalized:
            task["depends_on"] = [dep for dep in task["depends_on"] if dep in valid_ids and dep < task["id"]]

        result["goal_summary"] = str(result.get("goal_summary", user_goal[:80] if user_goal else "goal")).strip()[:120]
        result["difficulty"] = str(result.get("difficulty", difficulty)).lower()
        result["estimated_complexity"] = self._complexity_for_difficulty(result["difficulty"])
        result["sub_tasks"] = normalized
        return result

    def _parse_json_response(self, text: str) -> dict:
        """Parse JSON response using LangChain's class-level JsonOutputParser."""
        parsed = self.json_parser.parse(text)
        if isinstance(parsed, dict):
            return parsed
        raise ValueError(f"Could not parse JSON from response: {text[:200]}")
