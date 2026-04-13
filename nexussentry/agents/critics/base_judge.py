# nexussentry/agents/critics/base_judge.py
"""
Base interface for all specialist judges in the CriticPanel.
Provides common prompt building, LLM invocation, and response parsing.
"""
import json
import logging
import re
from abc import ABC, abstractmethod
from typing import Dict, List, Optional
from nexussentry.providers.llm_provider import get_provider

log = logging.getLogger(__name__)


class BaseJudge(ABC):
    """All specialist judges inherit from this."""

    judge_id: str = "base"
    focus: str = "general quality"
    preferred_provider: str = "auto"

    def __init__(self):
        self.provider = get_provider()

    async def evaluate(self, task: str, plan: dict, result: dict,
                        peer_context: str = "") -> Dict:
        """
        peer_context: in MoA Round 2, this contains other judges' Round 1 verdicts.
        Empty string in Round 1.
        """
        prompt = self._build_prompt(task, plan, result, peer_context)
        raw = self.provider.chat(
            system=self._system_prompt(),
            user_msg=prompt,
            agent_name=f"critic_{self.judge_id}"
        )
        return self._parse_verdict(raw)

    def _build_prompt(self, task, plan, result, peer_context) -> str:
        base = f"""TASK: {task}

PLAN THAT WAS MADE:
{json.dumps(plan, indent=2, default=str)[:1500]}

RESULT / IMPLEMENTATION:
{json.dumps(result, indent=2, default=str)[:1500]}"""

        if peer_context:
            base += f"""

OTHER JUDGES' PRELIMINARY ASSESSMENTS:
{peer_context}

Consider their perspectives but evaluate based on YOUR specialty: {self.focus}
You MAY revise your score based on their insights."""

        base += f"""

Evaluate ONLY based on: {self.focus}

Respond ONLY with valid JSON:
{{
  "judge_id": "{self.judge_id}",
  "score": <0-100 integer>,
  "decision": "approve" or "reject",
  "issues": ["specific issue 1", "specific issue 2"],
  "reasoning": "2-3 sentence explanation",
  "suggestions": ["actionable fix 1"]
}}"""
        return base

    def _parse_verdict(self, raw: str) -> Dict:
        try:
            return json.loads(raw)
        except Exception:
            match = re.search(r'\{.*\}', raw, re.DOTALL)
            if match:
                try:
                    return json.loads(match.group(0))
                except Exception:
                    pass
        # Fallback verdict
        return {
            "judge_id": self.judge_id, "score": 60,
            "decision": "reject", "issues": ["Parse failed — treating as reject"],
            "reasoning": "Could not parse judge response", "suggestions": []
        }

    @abstractmethod
    def _system_prompt(self) -> str:
        pass
