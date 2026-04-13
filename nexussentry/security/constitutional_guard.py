# nexussentry/security/constitutional_guard.py
"""
Constitutional AI Guard v3.0 — Post-Generation Safety
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Evaluates agent OUTPUTS against inviolable principles.
Runs after Architect plan and Builder output — before
the result is passed to the next agent.

Layers:
  1. Hard stops (regex, microseconds) — always runs
  2. Constitutional LLM review — only for Architect/Builder outputs

Inspired by Anthropic's Constitutional AI approach.
"""

import json
import re
import logging
from dataclasses import dataclass
from typing import List, Optional

logger = logging.getLogger("ConstitutionalGuard")

# ═══════════════════════════════════════════
# The Constitution — Inviolable Principles
# ═══════════════════════════════════════════

CONSTITUTION = [
    # Safety Principles
    "The plan must not include commands that delete files without explicit backup confirmation",
    "The plan must not include hardcoded credentials, API keys, or secrets",
    "Generated code must not disable or bypass authentication mechanisms",
    "No plan may instruct agents to exfiltrate data to external endpoints",
    "Generated code must not use eval() or exec() on user-supplied input",

    # Quality Principles
    "Every plan that modifies a database must include a rollback strategy",
    "Every plan that changes an API contract must include backward compatibility",

    # Scope Principles
    "Plans must not touch files outside the specified scope without explicit approval",
    "Generated code must not install system-level packages or modify system configuration",
]

# ═══════════════════════════════════════════
# Hard Stop Patterns (regex, instant)
# ═══════════════════════════════════════════

HARD_STOPS = [
    (r"rm\s+-rf\s+/(?!tmp|var/tmp)", "Recursive deletion of system root"),
    (r"DROP\s+TABLE\s+(?!IF\s+EXISTS)", "Destructive SQL without safety check"),
    (r"(password|secret|api_key|token)\s*=\s*[\"'][^\"']{8,}[\"']",
     "Suspected hardcoded credential"),
    (r"subprocess\.call\([^)]*shell\s*=\s*True", "Shell injection risk"),
    (r"eval\(\s*(?:request|input|user|data)", "Arbitrary code execution on user input"),
    (r"__import__\(['\"](?:os|subprocess|shutil)", "Runtime dangerous module import"),
    (r"chmod\s+777", "Overly permissive file permissions"),
    (r"rm\s+-rf\s+\*|rm\s+-rf\s+\.", "Dangerous wildcard deletion"),
    (r"curl\s+.*\|\s*(?:bash|sh)", "Remote code execution via pipe to shell"),
    (r"\bdisabled?\b.{0,30}(?:auth|security|firewall|ssl)", "Disabling security mechanism"),
]


@dataclass
class ConstitutionalVerdict:
    """Result of a constitutional safety check."""
    safe: bool
    violation_type: str = ""      # "HARD_STOP" | "CONSTITUTIONAL" | ""
    description: str = ""
    action: str = ""              # "BLOCK_AND_ESCALATE" | "REJECT_WITH_FEEDBACK" | ""
    matched_pattern: str = ""


class ConstitutionalGuard:
    """
    Post-generation safety check. Runs after every Architect plan
    and Builder output. Fast enough to not be a bottleneck.
    """

    # Expose module-level constants as class attributes for introspection
    CONSTITUTION = CONSTITUTION
    HARD_STOPS = HARD_STOPS

    def __init__(self):
        self.checks_performed = 0
        self.violations_caught = 0

    def check_output(self, agent_name: str, output: dict) -> ConstitutionalVerdict:
        """
        Check an agent's output against constitutional principles.
        Returns immediately on hard stops; runs LLM check for subtle violations.
        """
        self.checks_performed += 1
        output_text = json.dumps(output, default=str)

        # Layer 1: Hard stops (regex, always runs)
        for pattern, violation in HARD_STOPS:
            match = re.search(pattern, output_text, re.IGNORECASE)
            if match:
                self.violations_caught += 1
                logger.warning(
                    f"Constitutional HARD STOP in {agent_name}: {violation} "
                    f"(matched: '{match.group(0)[:50]}')"
                )
                return ConstitutionalVerdict(
                    safe=False,
                    violation_type="HARD_STOP",
                    description=violation,
                    action="BLOCK_AND_ESCALATE",
                    matched_pattern=match.group(0)[:100],
                )

        # Layer 2: Constitutional LLM review (only for Architect and Builder)
        if agent_name.lower() in ("architect", "builder"):
            llm_verdict = self._llm_constitutional_review(agent_name, output_text)
            if llm_verdict and not llm_verdict.safe:
                self.violations_caught += 1
                return llm_verdict

        return ConstitutionalVerdict(safe=True)

    def _llm_constitutional_review(self, agent_name: str,
                                    output_text: str) -> Optional[ConstitutionalVerdict]:
        """
        Ask the LLM to evaluate output against the constitution.
        Uses the cheapest/fastest model — this is a safety check, not quality.
        """
        try:
            from nexussentry.providers.llm_provider import get_provider

            provider = get_provider()
            if provider.mock_mode:
                return None

            constitution_str = "\n".join(f"- {p}" for p in CONSTITUTION)
            prompt = f"""You are a constitutional safety reviewer.

CONSTITUTION (inviolable rules):
{constitution_str}

OUTPUT TO REVIEW (from {agent_name} agent):
{output_text[:2000]}

Does this output violate any constitutional rule?
Respond ONLY with JSON: {{"violation": true/false, "rule": "rule text or null", "explanation": "brief explanation"}}"""

            raw = provider.chat(
                system="You are a safety reviewer. Be strict but fair. Only flag ACTUAL violations.",
                user_msg=prompt,
                max_tokens=200,
                prefer="gemini",  # Cheapest/fastest for safety checks
                agent_name="guardian",
            )

            # Parse response
            import json as json_mod
            # Extract JSON from response
            json_match = re.search(r'\{[^}]+\}', raw)
            if json_match:
                result = json_mod.loads(json_match.group(0))
                if result.get("violation"):
                    return ConstitutionalVerdict(
                        safe=False,
                        violation_type="CONSTITUTIONAL",
                        description=result.get("explanation", "Constitutional violation detected"),
                        action="REJECT_WITH_FEEDBACK",
                    )

        except Exception as e:
            logger.debug(f"Constitutional LLM review skipped: {e}")

        return None

    def stats(self) -> dict:
        """Return constitutional guard statistics."""
        return {
            "checks_performed": self.checks_performed,
            "violations_caught": self.violations_caught,
            "violation_rate": (
                f"{(self.violations_caught / max(1, self.checks_performed)) * 100:.1f}%"
            ),
        }
