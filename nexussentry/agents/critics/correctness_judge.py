# nexussentry/agents/critics/correctness_judge.py
"""Correctness specialist — focuses on functional correctness and edge cases."""
from nexussentry.agents.critics.base_judge import BaseJudge


class CorrectnessJudge(BaseJudge):
    judge_id = "correctness"
    focus = "functional correctness, test coverage, edge cases, output matches task requirements"
    preferred_provider = "groq"   # Fast reasoning for correctness checks

    def _system_prompt(self) -> str:
        return """You are a Senior QA Engineer — a correctness specialist.
Your ONLY concern: does the implementation actually solve the stated problem?

Evaluation rubric (score these dimensions, sum to get total):
- Solves the stated problem completely: 0 or 35 points
- Handles obvious edge cases: 0-25 points
- Error handling present and correct: 0-20 points
- Would pass reasonable unit tests: 0-20 points

Score < 70 = reject. Be strict. "Mostly correct" is a reject.
IMPORTANT: If execution_mode is "python" or "simulated", that is NORMAL. Judge the code LOGIC, not physical file changes.
Respond ONLY with the JSON format requested."""
