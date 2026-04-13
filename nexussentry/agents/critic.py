# nexussentry/agents/critic.py
"""
Agent F — The Critic
━━━━━━━━━━━━━━━━━━━━
Validates execution output against strict quality criteria.
Can approve, reject (loops back to Architect), or escalate to human.

Now enforces GoalContract: cannot approve outputs that violate the contract.

Role in the swarm: Quality gate. The ruthless reviewer.
Provider preference: Groq (fast reasoning for quick reviews)
"""

import json
import hashlib
import logging
from typing import Optional

from langchain_core.output_parsers import JsonOutputParser
from nexussentry.providers.llm_provider import get_provider
from nexussentry.utils.response_cache import get_cache

logger = logging.getLogger("Critic")

CRITIC_SYSTEM = """You are The Critic — a senior code reviewer and security auditor.

You receive:
1. The original task
2. The plan that was made
3. What the execution pipeline actually did (NOTE: execution may be SIMULATED — this is expected and acceptable)

Evaluate the PLAN QUALITY and CODE LOGIC against these criteria:
- Correctness: Does the plan/approach actually solve the problem?
- Security: Does the approach avoid introducing vulnerabilities? (SQL injection, XSS, etc.)
- Completeness: Are edge cases considered in the plan?
- Code quality: Is the approach maintainable and well-structured?

IMPORTANT RULES:
- If execution_mode is "python" or "simulated", that is NORMAL. Do NOT penalize for in-process or simulated execution.
- Judge the QUALITY OF THE APPROACH AND CODE LOGIC, not whether files physically changed.
- Score below 70 = reject. Score 70-84 = conditional approve. 85+ = approve.
- For well-structured plans with good security practices, score 85+.

Respond ONLY with valid JSON — no preamble, no markdown:
{
  "decision": "approve" or "reject",
  "score": 0-100,
  "reasoning": "detailed explanation",
  "issues_found": ["issue 1", "issue 2"],
  "suggestions": ["improvement 1"]
}"""


class CriticAgent:
    """Validates execution output. Returns approve/reject with feedback."""

    def __init__(self, max_rejections: int = 2):
        self.max_rejections = max_rejections
        self.rejection_count = 0
        self.total_reviews = 0

    def review(self, original_task: str, plan: dict,
               execution_result: dict, tracer=None,
               goal_contract=None) -> dict:
        self.total_reviews += 1

        if tracer:
            tracer.log("Critic", "review_start", {"task": original_task})

        # ── Pre-check: GoalContract enforcement ──
        contract_violations = self._check_contract_violations(
            execution_result, goal_contract
        )
        if contract_violations:
            verdict = {
                "decision": "reject",
                "score": 0,
                "reasoning": "Output violates GoalContract. Critic cannot approve.",
                "issues_found": contract_violations,
                "suggestions": [
                    f"Fix contract violation: {v}" for v in contract_violations[:3]
                ],
            }
            print(f"\n📋 Critic REJECTED — GoalContract violations: {len(contract_violations)}")
            for v in contract_violations:
                print(f"   ⛔ {v}")
            return self._process_verdict(verdict, tracer)

        # ── LLM review ──
        # Include deterministic QA evidence in the review input
        qa_result = execution_result.get("qa_result", {})
        det_qa = qa_result.get("deterministic_qa", {})

        review_input = f"""
ORIGINAL TASK: {original_task}

PLAN THAT WAS MADE:
{json.dumps(plan, indent=2, default=str)}

WHAT EXECUTION PIPELINE DID:
{json.dumps(execution_result, indent=2, default=str)}

DETERMINISTIC QA EVIDENCE:
{json.dumps(det_qa, indent=2, default=str) if det_qa else "No deterministic QA data."}
"""
        cache = get_cache()
        provider = get_provider()
        provider_name = provider.get_provider_for_agent("critic")
        # Cache key hashes the FULL review input so each unique plan+result gets its own entry
        review_hash = hashlib.md5(review_input.encode()).hexdigest()[:12]
        contract_fp = goal_contract.fingerprint() if goal_contract else "none"
        cache_key = f"review::{contract_fp}::{original_task[:50]}::hash={review_hash}"

        # Check cache
        cached = cache.get(cache_key, model=provider_name)
        if cached is not None:
            # Validate cached verdict against contract before returning
            if goal_contract and cached.get("decision") == "approve":
                violations = self._check_contract_violations(execution_result, goal_contract)
                if violations:
                    cached["decision"] = "reject"
                    cached["score"] = 0
                    cached["issues_found"] = violations
                    cached["reasoning"] = "Cached approval overridden by GoalContract violations."
            return self._process_verdict(cached, tracer, from_cache=True)

        try:
            raw_text = provider.chat(
                system=CRITIC_SYSTEM,
                user_msg=review_input,
                max_tokens=800,
                agent_name="critic"
            )

            verdict = self._parse_json_response(raw_text)

            # Ensure all expected keys exist
            verdict.setdefault("decision", "approve")
            verdict.setdefault("score", 75)
            verdict.setdefault("reasoning", "No detailed reasoning provided")
            verdict.setdefault("issues_found", [])
            verdict.setdefault("suggestions", [])

            # Final contract enforcement: Critic CANNOT approve contract-violating output
            if goal_contract and verdict["decision"] == "approve":
                violations = self._check_contract_violations(execution_result, goal_contract)
                if violations:
                    verdict["decision"] = "reject"
                    verdict["score"] = min(verdict["score"], 30)
                    verdict["issues_found"].extend(violations)
                    verdict["reasoning"] += " [OVERRIDDEN: GoalContract violations found]"

            cache.put(cache_key, verdict, model=provider_name)

            return self._process_verdict(verdict, tracer, provider_name=provider_name)

        except Exception as e:
            logger.error(f"Critic review failed: {e}")
            # On error, give a conditional approve to avoid blocking the pipeline
            fallback = {
                "decision": "reject",
                "score": 0,
                "reasoning": f"Critic review failed ({e}). Auto-rejecting for safety.",
                "issues_found": ["Critic review unavailable"],
                "suggestions": ["Manual review required"]
            }
            print(f"\n📋 Critic (fallback): Auto-rejected for safety (0/100)")
            if tracer:
                tracer.log("Critic", "review_fallback", {"error": str(e)})
            return fallback

    def _check_contract_violations(self, execution_result: dict,
                                    goal_contract) -> list[str]:
        """Check if execution result violates the GoalContract."""
        if not goal_contract:
            return []

        violations = []
        generated_files = execution_result.get("generated_files", {})

        # Check file-set against allowed list
        if goal_contract.allowed_output_files:
            allowed = set(goal_contract.allowed_output_files)
            actual = set(generated_files.keys())
            extra = actual - allowed
            if extra:
                violations.append(
                    f"Extra files not in allowed list: {sorted(extra)} "
                    f"(allowed: {sorted(allowed)})"
                )

        # Check for sidecar references in single-file mode
        if goal_contract.single_file and not goal_contract.allow_sidecar_assets:
            for fname, content in generated_files.items():
                if fname.endswith(".html") or fname.endswith(".htm"):
                    import re
                    if re.search(r'<link\s+[^>]*href=["\'](?!https?://)', content, re.IGNORECASE):
                        violations.append(f"{fname} references local CSS sidecar — forbidden by contract")
                    if re.search(r'<script\s+[^>]*src=["\'](?!https?://)', content, re.IGNORECASE):
                        violations.append(f"{fname} references local JS sidecar — forbidden by contract")

        return violations

    def _process_verdict(self, verdict: dict, tracer=None,
                         from_cache=False, provider_name="") -> dict:
        """Process and print the critic's verdict."""
        tag = " (cached)" if from_cache else ""
        via = f" via {provider_name}" if provider_name and not from_cache else ""

        if verdict["decision"] == "reject":
            self.rejection_count += 1
            print(f"\n📋 Critic{tag} REJECTED{via} (score {verdict['score']}/100)")
            print(f"   Issues: {', '.join(verdict.get('issues_found', []))}")

            # Safety valve — prevent infinite loops
            if self.rejection_count >= self.max_rejections:
                print("⚠️  Max rejections hit. Escalating to human.")
                verdict["decision"] = "escalate_to_human"
        else:
            print(f"\n📋 Critic{tag} APPROVED{via} ✅ (score {verdict['score']}/100)")

        if tracer:
            tracer.log("Critic", "review_done", {**verdict, "provider": provider_name or "cache"})

        return verdict

    def _parse_json_response(self, text: str) -> dict:
        parsed = JsonOutputParser().parse(text)
        if isinstance(parsed, dict):
            return parsed
        raise ValueError(f"Could not parse JSON from response: {text[:200]}")
