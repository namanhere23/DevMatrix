"""Dynamic pipeline assembly heuristics for NexusSentry v3.0."""

from __future__ import annotations

import re


class AgentFactory:
    """Assemble a lightweight agent pipeline from task descriptions."""

    _SECURITY_PATTERNS = (
        r"\bauth\b",
        r"oauth",
        r"\bjwt\b",
        r"\bsecurity\b",
        r"\bencrypt",
        r"\bpermission",
        r"\baccess control\b",
        r"\bvulnerab",
    )

    _TEST_PATTERNS = (
        r"\btest\b",
        r"\bqa\b",
        r"\bverify\b",
        r"\bvalidation\b",
    )

    def assemble_pipeline(self, sub_tasks: list[dict]) -> list[str]:
        """Return the agent stages best suited for the given task set."""
        task_text = " ".join(str(item.get("task", "")) for item in sub_tasks).lower()

        pipeline = [
            "scout",
            "architect",
            "builder",
            "integrator",
        ]

        if self._matches(task_text, self._SECURITY_PATTERNS):
            pipeline.append("security_auditor")

        if self._matches(task_text, self._TEST_PATTERNS) or "security_auditor" not in pipeline:
            pipeline.append("qa_verifier")

        pipeline.append("critic")
        return pipeline

    def _matches(self, text: str, patterns: tuple[str, ...]) -> bool:
        return any(re.search(pattern, text, re.IGNORECASE) for pattern in patterns)
