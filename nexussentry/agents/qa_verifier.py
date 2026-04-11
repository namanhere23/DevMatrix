"""
Agent E — QA Verifier
━━━━━━━━━━━━━━━━━━━━━
Validates integrated artifacts before they reach the Critic.
"""

import json
import logging

from langchain_core.output_parsers import JsonOutputParser
from langchain_core.prompts import PromptTemplate

from nexussentry.providers.llm_provider import get_provider

logger = logging.getLogger("QAVerifier")

QA_SYSTEM = """You are the QA verifier for a multi-builder code pipeline.
Check whether the generated files match the plan, contain no placeholders, and are complete.

Respond ONLY with valid JSON:
{
  "decision": "pass" or "fail",
  "score": 0-100,
  "issues_found": ["issue 1"],
  "suggestions": ["suggestion 1"],
  "summary": "short verification summary"
}"""


class QAVerifierAgent:
    """Runs deterministic and LLM-assisted QA checks on integrated artifacts."""

    def verify(self, plan: dict, generated_files: dict,
               builder_reports: list, tracer=None) -> dict:
        provider = get_provider()
        provider_name = provider.get_provider_for_agent("qa_verifier")
        expected_files = set(plan.get("files_to_modify", []) or [])
        issues = []

        missing_files = sorted(expected_files - set(generated_files.keys()))
        if missing_files:
            issues.append(f"Missing generated files: {', '.join(missing_files)}")

        for filename, content in generated_files.items():
            if not content or not content.strip():
                issues.append(f"{filename} is empty")
            lowered = content.lower()
            if "todo" in lowered or "add code here" in lowered:
                issues.append(f"{filename} still contains placeholder text")

        prompt = self._format_prompt("""Plan summary: {plan_summary}
    Generated files: {generated_files}
    Missing files: {missing_files}
    Builder count: {builder_count}

    Return a strict JSON QA verdict.""",
            plan_summary=plan.get('plan_summary', ''),
            generated_files=', '.join(sorted(generated_files.keys())),
            missing_files=', '.join(missing_files) if missing_files else 'none',
            builder_count=len(builder_reports),
        )

        try:
            raw = provider.chat(
                system=QA_SYSTEM,
                user_msg=prompt,
                max_tokens=800,
                prefer="auto",
                agent_name="qa_verifier",
            )
            qa_verdict = self._parse_json_response(raw)
        except Exception as exc:
            logger.warning("QA verifier unavailable: %s", exc)
            qa_verdict = {
                "decision": "fail",
                "score": 0,
                "issues_found": [f"QA verifier unavailable: {exc}"],
                "suggestions": ["Review generated files manually"],
                "summary": "QA verifier failed",
            }

        qa_issues = list(qa_verdict.get("issues_found", []))
        combined_issues = issues + qa_issues
        passed = not combined_issues and qa_verdict.get("decision", "pass") == "pass"

        result = {
            "passed": passed,
            "decision": "pass" if passed else "fail",
            "score": qa_verdict.get("score", 100 if passed else 60),
            "issues_found": combined_issues,
            "suggestions": qa_verdict.get("suggestions", []),
            "summary": qa_verdict.get("summary", "QA completed"),
        }

        if tracer:
            tracer.log("QAVerifier", "qa_done", {
                **result,
                "provider": provider_name,
            })

        return result

    def _format_prompt(self, template: str, **kwargs) -> str:
        return PromptTemplate.from_template(template).format(**kwargs)

    def _parse_json_response(self, text: str) -> dict:
        parsed = JsonOutputParser().parse(text)
        if isinstance(parsed, dict):
            return parsed
        raise ValueError(f"Could not parse QA response as JSON: {text[:200]}")
