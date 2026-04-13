# nexussentry/agents/critics/security_judge.py
"""Security specialist — focuses on OWASP Top 10 and adversarial attack vectors."""
from nexussentry.agents.critics.base_judge import BaseJudge


class SecurityJudge(BaseJudge):
    judge_id = "security"
    focus = "OWASP Top 10 vulnerabilities, injection risks, secret exposure, auth flaws"
    preferred_provider = "gemini"  # Fast + good security reasoning

    def _system_prompt(self) -> str:
        return """You are a Security Auditor — an adversarial security reviewer.
You look for ways attackers could exploit this code.

Evaluation rubric:
- No SQL/command/path injection: 0 or 30 points (binary)
- No hardcoded secrets or credentials: 0 or 25 points (binary)
- No authentication/authorization bypass: 0 or 25 points (binary)
- No sensitive data exposure: 0-20 points

A SINGLE critical vulnerability = score of 0. No exceptions.
If no security-sensitive code is present, score 90 and approve.
IMPORTANT: If execution_mode is "simulated", that is NORMAL. Judge the code LOGIC, not physical file changes.
Respond ONLY with the JSON format requested."""
