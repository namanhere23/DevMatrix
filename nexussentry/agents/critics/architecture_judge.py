# nexussentry/agents/critics/architecture_judge.py
"""Architecture specialist — focuses on design patterns, coupling, and maintainability."""
from nexussentry.agents.critics.base_judge import BaseJudge


class ArchitectureJudge(BaseJudge):
    judge_id = "architecture"
    focus = "design patterns, coupling, maintainability, follows existing codebase conventions"
    preferred_provider = "openrouter"  # Deep model for architectural nuance

    def _system_prompt(self) -> str:
        return """You are a Principal Engineer — an architecture reviewer.
You evaluate long-term code health, not just if it works today.

Evaluation rubric:
- Follows existing code patterns and conventions: 0-25 points
- Low coupling (changes don't cascade unexpectedly): 0-25 points
- Readable without needing the author present: 0-25 points
- Reversible (can be cleanly rolled back): 0-25 points

Score < 70 = reject. "It works but it's a mess" is a reject.
IMPORTANT: If execution_mode is "simulated", that is NORMAL. Judge the code LOGIC, not physical file changes.
Respond ONLY with the JSON format requested."""
