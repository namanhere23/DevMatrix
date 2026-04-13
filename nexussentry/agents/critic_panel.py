# nexussentry/agents/critic_panel.py
"""
Critic Panel v3.0 — Multi-Agent Debate (MoA)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Three specialized judges evaluate independently, then debate to consensus.
Implements the Mixture-of-Agents pattern from NeurIPS 2025 research.

Replaces the single Critic with:
  - Correctness Judge (Groq — fast reasoning)
  - Security Auditor (Gemini — thorough analysis)
  - Architecture Reviewer (OpenRouter — diverse models)

Each judge sees others' verdicts in Round 2 before finalizing.
"""

import asyncio
import json
import logging
import time
from typing import List, Dict, Any, Optional

from langchain_core.output_parsers import JsonOutputParser
from nexussentry.providers.llm_provider import get_provider

logger = logging.getLogger("CriticPanel")

# ═══════════════════════════════════════════
# Multi-Dimensional Rubric
# ═══════════════════════════════════════════

CRITIC_RUBRIC = {
    "correctness": {
        "weight": 0.30,
        "dimensions": {
            "solves_stated_problem": 10,
            "handles_edge_cases": 10,
            "tests_would_pass": 10,
        },
    },
    "security": {
        "weight": 0.30,
        "dimensions": {
            "no_injection_risks": 10,
            "no_data_exposure": 10,
            "no_hardcoded_secrets": 10,
        },
    },
    "architecture": {
        "weight": 0.25,
        "dimensions": {
            "follows_existing_patterns": 10,
            "no_unnecessary_dependencies": 5,
            "readable_and_documented": 5,
            "reversible": 10,
        },
    },
    "completeness": {
        "weight": 0.15,
        "dimensions": {
            "all_files_addressed": 10,
            "no_todos_left": 5,
            "error_handling_present": 5,
        },
    },
}


def _build_rubric_prompt() -> str:
    """Build a structured rubric string for judge prompts."""
    lines = ["EVALUATION RUBRIC (score each dimension 0-10):"]
    for category, config in CRITIC_RUBRIC.items():
        weight_pct = int(config["weight"] * 100)
        lines.append(f"\n{category.upper()} ({weight_pct}% weight):")
        for dim, max_score in config["dimensions"].items():
            lines.append(f"  - {dim}: 0-{max_score}")
    return "\n".join(lines)


RUBRIC_PROMPT = _build_rubric_prompt()

# ═══════════════════════════════════════════
# Judge Configurations
# ═══════════════════════════════════════════

JUDGES = {
    "correctness": {
        "provider_pref": "groq",
        "focus": "functional correctness, test coverage, edge cases",
        "weight": 0.4,
        "system": """You are a CORRECTNESS specialist judge in a code review panel.
Focus EXCLUSIVELY on:
- Does the plan/code actually solve the stated problem?
- Are edge cases handled?
- Would tests pass if written for this code?
- Is the logic sound?

{rubric}

IMPORTANT: If execution_mode is "python" or "simulated", that is NORMAL. Judge the code LOGIC, not physical file changes.

Respond ONLY with valid JSON:
{{
  "judge_id": "correctness",
  "score": 0-100,
  "reasoning": "detailed explanation focusing on correctness",
  "issues": ["issue 1", "issue 2"],
  "dimension_scores": {{"solves_stated_problem": 0-10, "handles_edge_cases": 0-10, "tests_would_pass": 0-10}}
}}""",
    },
    "security": {
        "provider_pref": "gemini",
        "focus": "vulnerabilities, injection risks, data exposure, OWASP Top 10",
        "weight": 0.35,
        "system": """You are a SECURITY AUDITOR judge in a code review panel.
Focus EXCLUSIVELY on:
- SQL injection, XSS, CSRF vulnerabilities
- Hardcoded credentials or API keys
- Data exposure risks
- Authentication/authorization bypass
- OWASP Top 10 compliance

{rubric}

IMPORTANT: If execution_mode is "python" or "simulated", that is NORMAL. Judge the code LOGIC, not physical file changes.

Respond ONLY with valid JSON:
{{
  "judge_id": "security",
  "score": 0-100,
  "reasoning": "detailed explanation focusing on security",
  "issues": ["vulnerability 1", "risk 2"],
  "dimension_scores": {{"no_injection_risks": 0-10, "no_data_exposure": 0-10, "no_hardcoded_secrets": 0-10}}
}}""",
    },
    "architecture": {
        "provider_pref": "openrouter",
        "focus": "design patterns, coupling, maintainability, scalability",
        "weight": 0.25,
        "system": """You are an ARCHITECTURE REVIEWER judge in a code review panel.
Focus EXCLUSIVELY on:
- Does it follow existing architectural patterns?
- Is coupling minimized?
- Is the code maintainable and readable?
- Can changes be rolled back safely?
- Are unnecessary dependencies introduced?

{rubric}

IMPORTANT: If execution_mode is "python" or "simulated", that is NORMAL. Judge the code LOGIC, not physical file changes.

Respond ONLY with valid JSON:
{{
  "judge_id": "architecture",
  "score": 0-100,
  "reasoning": "detailed explanation focusing on architecture",
  "issues": ["design issue 1"],
  "dimension_scores": {{"follows_existing_patterns": 0-10, "no_unnecessary_dependencies": 0-5, "readable_and_documented": 0-5, "reversible": 0-10}}
}}""",
    },
}


class CriticPanel:
    """
    Three specialized judges evaluate independently, then debate to consensus.
    Implements the MoA pattern: each judge sees others' verdicts before finalizing.
    """

    def __init__(self, max_rejections: int = 2):
        self.max_rejections = max_rejections
        self.rejection_count = 0
        self.total_reviews = 0

    def review(self, original_task: str, plan: dict,
               execution_result: dict, tracer=None,
               goal_contract=None) -> dict:
        """
        Run the full MoA debate panel review.
        Synchronous wrapper around async internals for compatibility.
        """
        self.total_reviews += 1

        if tracer:
            tracer.log("Critic", "panel_review_start", {
                "task": original_task,
                "judges": list(JUDGES.keys()),
            })

        # ── Pre-check: GoalContract enforcement ──
        contract_violations = self._check_contract_violations(
            execution_result, goal_contract
        )
        if contract_violations:
            verdict = {
                "decision": "reject",
                "score": 0,
                "reasoning": "Output violates GoalContract. Panel cannot approve.",
                "issues_found": contract_violations,
                "suggestions": [f"Fix contract violation: {v}" for v in contract_violations[:3]],
                "panel_breakdown": {},
            }
            print(f"\n📋 Panel REJECTED — GoalContract violations: {len(contract_violations)}")
            for v in contract_violations:
                print(f"   ⛔ {v}")
            return self._process_verdict(verdict, tracer)

        # Build review input
        qa_result = execution_result.get("qa_result", {})
        det_qa = qa_result.get("deterministic_qa", {})

        review_input = f"""ORIGINAL TASK: {original_task}

PLAN THAT WAS MADE:
{json.dumps(plan, indent=2, default=str)}

WHAT EXECUTION PIPELINE DID:
{json.dumps(execution_result, indent=2, default=str)}

DETERMINISTIC QA EVIDENCE:
{json.dumps(det_qa, indent=2, default=str) if det_qa else "No deterministic QA data."}"""

        # ── Round 1: Independent evaluation ──
        round1_verdicts = self._run_round1(review_input)

        # ── Check for early consensus ──
        if self._consensus_reached(round1_verdicts):
            final = self._aggregate(round1_verdicts)
            if tracer:
                tracer.log("Critic", "panel_consensus_r1", {
                    "round": 1,
                    "scores": {v["judge_id"]: v["score"] for v in round1_verdicts},
                })
            return self._process_verdict(final, tracer)

        # ── Round 2: MoA Debate — each judge sees others' verdicts ──
        round2_verdicts = self._run_round2(review_input, round1_verdicts)

        # ── Final aggregation ──
        final = self._aggregate(round2_verdicts)

        if tracer:
            tracer.log("Critic", "panel_review_done", {
                **final,
                "rounds": 2,
                "r1_scores": {v["judge_id"]: v["score"] for v in round1_verdicts},
                "r2_scores": {v["judge_id"]: v["score"] for v in round2_verdicts},
            })

        return self._process_verdict(final, tracer)

    def _run_round1(self, review_input: str) -> List[Dict[str, Any]]:
        """Round 1: Independent evaluation — no cross-contamination."""
        verdicts = []
        provider = get_provider()

        for judge_id, config in JUDGES.items():
            try:
                system = config["system"].format(rubric=RUBRIC_PROMPT)
                raw = provider.chat(
                    system=system,
                    user_msg=review_input[:4000],  # Trim to prevent token overflow
                    max_tokens=800,
                    prefer=config["provider_pref"],
                    agent_name="critic",
                )
                verdict = self._parse_verdict(raw, judge_id)
                verdicts.append(verdict)
            except Exception as e:
                logger.warning(f"Judge '{judge_id}' failed in Round 1: {e}")
                verdicts.append({
                    "judge_id": judge_id,
                    "score": 70,
                    "reasoning": f"Judge unavailable: {e}",
                    "issues": [],
                    "dimension_scores": {},
                })

        return verdicts

    def _run_round2(self, review_input: str, round1_verdicts: List[Dict]) -> List[Dict[str, Any]]:
        """Round 2: MoA Debate — each judge refines after seeing peers' analysis."""
        verdicts = []
        provider = get_provider()

        for judge_id, config in JUDGES.items():
            # Build context from other judges' Round 1 verdicts
            other_verdicts = [v for v in round1_verdicts if v["judge_id"] != judge_id]
            peer_context = "\n".join([
                f"{v['judge_id']} judge scored {v['score']}/100: {v['reasoning'][:200]}"
                for v in other_verdicts
            ])

            debate_system = f"""{config['system'].format(rubric=RUBRIC_PROMPT)}

ROUND 2 — DEBATE CONTEXT:
Other panel members have provided these preliminary assessments:
{peer_context}

Consider their perspectives, but evaluate independently based on your specialty: {config['focus']}.
You may revise your score based on their insights. Provide your FINAL verdict."""

            try:
                raw = provider.chat(
                    system=debate_system,
                    user_msg=review_input[:3500],
                    max_tokens=800,
                    prefer=config["provider_pref"],
                    agent_name="critic",
                )
                verdict = self._parse_verdict(raw, judge_id)
                verdicts.append(verdict)
            except Exception as e:
                logger.warning(f"Judge '{judge_id}' failed in Round 2: {e}")
                # Fall back to Round 1 verdict
                r1 = next((v for v in round1_verdicts if v["judge_id"] == judge_id), None)
                verdicts.append(r1 or {
                    "judge_id": judge_id,
                    "score": 70,
                    "reasoning": f"Judge unavailable in Round 2: {e}",
                    "issues": [],
                })

        return verdicts

    def _consensus_reached(self, verdicts: List[Dict]) -> bool:
        """
        Adaptive stopping: if all judges agree within 15 points, no need for Round 2.
        Based on NeurIPS 2025 stability detection.
        """
        scores = [v.get("score", 0) for v in verdicts]
        if not scores:
            return False
        return (max(scores) - min(scores)) < 15

    def _aggregate(self, verdicts: List[Dict]) -> Dict[str, Any]:
        """Weighted average aggregation when consensus is clear."""
        if not verdicts:
            return {
                "decision": "reject",
                "score": 0,
                "reasoning": "No judge verdicts available",
                "issues_found": ["All judges failed"],
                "suggestions": [],
                "panel_breakdown": {},
            }

        # Calculate weighted score
        total_weight = 0
        weighted_score = 0
        for v in verdicts:
            judge_id = v.get("judge_id", "unknown")
            weight = JUDGES.get(judge_id, {}).get("weight", 0.33)
            weighted_score += v.get("score", 0) * weight
            total_weight += weight

        final_score = round(weighted_score / total_weight) if total_weight > 0 else 0

        # Collect all issues (deduplicated)
        all_issues = []
        seen = set()
        for v in verdicts:
            for issue in v.get("issues", []):
                if issue not in seen:
                    all_issues.append(issue)
                    seen.add(issue)

        # Decision based on final score
        if final_score >= 72:
            decision = "approve"
        else:
            decision = "reject"

        return {
            "decision": decision,
            "score": final_score,
            "reasoning": f"Panel consensus: {final_score}/100 ({len(verdicts)} judges)",
            "issues_found": all_issues,
            "suggestions": [],
            "panel_breakdown": {v.get("judge_id", "?"): v.get("score", 0) for v in verdicts},
            "dimension_scores": self._merge_dimension_scores(verdicts),
        }

    def _merge_dimension_scores(self, verdicts: List[Dict]) -> Dict[str, Any]:
        """Merge dimension scores from all judges into a single report."""
        merged = {}
        for v in verdicts:
            judge_id = v.get("judge_id", "unknown")
            dims = v.get("dimension_scores", {})
            for dim, score in dims.items():
                merged[f"{judge_id}.{dim}"] = score
        return merged

    def _parse_verdict(self, raw: str, judge_id: str) -> Dict[str, Any]:
        """Parse a judge's JSON response with fallback handling."""
        try:
            parsed = JsonOutputParser().parse(raw)
            if isinstance(parsed, dict):
                parsed.setdefault("judge_id", judge_id)
                parsed.setdefault("score", 70)
                parsed.setdefault("reasoning", "No reasoning provided")
                parsed.setdefault("issues", [])
                parsed.setdefault("dimension_scores", {})
                return parsed
        except Exception:
            pass

        # Fallback: extract score from raw text
        import re
        score_match = re.search(r'"score"\s*:\s*(\d+)', raw)
        score = int(score_match.group(1)) if score_match else 70

        return {
            "judge_id": judge_id,
            "score": score,
            "reasoning": raw[:200],
            "issues": [],
            "dimension_scores": {},
        }

    def _check_contract_violations(self, execution_result: dict,
                                   goal_contract) -> List[str]:
        """Check if execution result violates the GoalContract (reused from CriticAgent)."""
        if not goal_contract:
            return []

        violations = []
        generated_files = execution_result.get("generated_files", {})

        if goal_contract.allowed_output_files:
            allowed = set(goal_contract.allowed_output_files)
            actual = set(generated_files.keys())
            extra = actual - allowed
            if extra:
                violations.append(
                    f"Extra files not in allowed list: {sorted(extra)} "
                    f"(allowed: {sorted(allowed)})"
                )

        if goal_contract.single_file and not goal_contract.allow_sidecar_assets:
            import re
            for fname, content in generated_files.items():
                if fname.endswith(".html") or fname.endswith(".htm"):
                    if re.search(r'<link\s+[^>]*href=["\'](?!https?://)', content, re.IGNORECASE):
                        violations.append(f"{fname} references local CSS sidecar — forbidden")
                    if re.search(r'<script\s+[^>]*src=["\'](?!https?://)', content, re.IGNORECASE):
                        violations.append(f"{fname} references local JS sidecar — forbidden")

        return violations

    def _process_verdict(self, verdict: dict, tracer=None) -> dict:
        """Process and print the panel's verdict."""
        if verdict["decision"] == "reject":
            self.rejection_count += 1
            breakdown = verdict.get("panel_breakdown", {})
            breakdown_str = ", ".join(f"{k}={v}" for k, v in breakdown.items()) if breakdown else "N/A"
            print(f"\n📋 Panel REJECTED (score {verdict['score']}/100) [{breakdown_str}]")

            if verdict.get("issues_found"):
                for issue in verdict["issues_found"][:3]:
                    print(f"   ⚠️  {issue}")

            if self.rejection_count >= self.max_rejections:
                print("⚠️  Max rejections hit. Escalating to human.")
                verdict["decision"] = "escalate_to_human"
        else:
            breakdown = verdict.get("panel_breakdown", {})
            breakdown_str = ", ".join(f"{k}={v}" for k, v in breakdown.items()) if breakdown else ""
            print(f"\n📋 Panel APPROVED ✅ (score {verdict['score']}/100) [{breakdown_str}]")

        if tracer:
            tracer.log("Critic", "review_done", {**verdict, "provider": "panel"})

        return verdict
