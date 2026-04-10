# nexussentry/agents/critic.py
"""
Agent D — The Critic
━━━━━━━━━━━━━━━━━━━━
Validates the Fixer's output against strict quality criteria.
Can approve, reject (loops back to Architect), or escalate to human.

Role in the swarm: Quality gate. The ruthless reviewer.
Provider preference: Grok (fast reasoning for quick reviews)
"""

import json
import re
import hashlib
import logging

from nexussentry.providers.llm_provider import get_provider
from nexussentry.utils.response_cache import get_cache

logger = logging.getLogger("Critic")

CRITIC_SYSTEM = """You are The Critic — a ruthless senior code reviewer and security auditor.

You receive:
1. The original task
2. The plan that was made
3. What the Fixer actually did

Evaluate against ALL criteria:
- Correctness: Does it actually solve the problem?
- Security: Does it introduce vulnerabilities? (SQL injection, XSS, etc.)
- Regressions: Could it break existing functionality?
- Completeness: Are edge cases handled?
- Code quality: Is it maintainable?

IMPORTANT: Score below 70 = reject. Score 70-84 = conditional approve. 85+ = approve.

Respond ONLY with valid JSON — no preamble, no markdown:
{
  "decision": "approve" or "reject",
  "score": 0-100,
  "reasoning": "detailed explanation",
  "issues_found": ["issue 1", "issue 2"],
  "suggestions": ["improvement 1"]
}"""


class CriticAgent:
    """Validates Fixer output. Returns approve/reject with feedback."""

    def __init__(self, max_rejections: int = 2):
        self.max_rejections = max_rejections
        self.rejection_count = 0
        self.total_reviews = 0

    def review(self, original_task: str, plan: dict,
               fixer_result: dict, tracer=None) -> dict:
        self.total_reviews += 1

        if tracer:
            tracer.log("Critic", "review_start", {"task": original_task})

        review_input = f"""
ORIGINAL TASK: {original_task}

PLAN THAT WAS MADE:
{json.dumps(plan, indent=2, default=str)}

WHAT FIXER DID:
{json.dumps(fixer_result, indent=2, default=str)}
"""
        cache = get_cache()
        provider = get_provider()
        provider_name = provider.get_provider_for_agent("critic")
        # Cache key hashes the FULL review input so each unique plan+result gets its own entry
        review_hash = hashlib.md5(review_input.encode()).hexdigest()[:12]
        cache_key = f"review::{original_task[:50]}::hash={review_hash}"

        # Check cache
        cached = cache.get(cache_key, model=provider_name)
        if cached is not None:
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
        """Robustly parse JSON from LLM response."""
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        json_match = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', text, re.DOTALL)
        if json_match:
            try:
                return json.loads(json_match.group(1))
            except json.JSONDecodeError:
                pass

        json_match = re.search(r'\{.*\}', text, re.DOTALL)
        if json_match:
            try:
                return json.loads(json_match.group(0))
            except json.JSONDecodeError:
                pass

        raise ValueError(f"Could not parse JSON from response: {text[:200]}")
