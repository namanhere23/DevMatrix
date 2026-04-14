"""
Agent E — QA Verifier
━━━━━━━━━━━━━━━━━━━━━
Validates integrated artifacts before they reach the Critic.

Runs deterministic pre-checks BEFORE any LLM verdict:
    1. Truncation / placeholder detection
    2. Single-file web integrity (inline <style>/<script>, no sidecar refs)
    3. DOM selector cross-check (JS references exist in HTML)

If deterministic checks fail, skips LLM QA entirely.
"""

import logging
import re

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

QA_USER_PROMPT = PromptTemplate.from_template(
        """Plan summary: {plan_summary}
Generated files: {generated_files}
Missing files: {missing_files}
Builder count: {builder_count}

Return a strict JSON QA verdict."""
)

_PLACEHOLDER_PATTERNS = [
    r"\btodo\b",
    r"\bfixme\b",
    r"add\s+code\s+here",
    r"implement\s+this",
    r"your\s+code\s+here",
    r"\[placeholder\]",
    r"\.\.\.\s*$",        # trailing ellipsis at end of line
    r"<!--\s*more\s*-->",  # HTML more marker
]

_SIDECAR_PATTERNS = [
    r'<link\s+[^>]*rel=["\']stylesheet["\'][^>]*href=["\'](?!https?://)',    # local CSS link
    r'<script\s+[^>]*src=["\'](?!https?://)',                                # local JS script
]


def _check_truncation(content: str, filename: str) -> list[str]:
    """Detect truncated or incomplete content."""
    issues = []
    stripped = content.strip()

    if not stripped:
        issues.append(f"{filename} is empty")
        return issues

    # Check for unclosed HTML tags (very basic)
    if filename.endswith(".html") or filename.endswith(".htm"):
        if "<html" in stripped.lower() and "</html>" not in stripped.lower():
            issues.append(f"{filename}: unclosed <html> tag — likely truncated")
        if "<body" in stripped.lower() and "</body>" not in stripped.lower():
            issues.append(f"{filename}: unclosed <body> tag — likely truncated")
        if "<script" in stripped.lower():
            open_count = len(re.findall(r"<script", stripped, re.IGNORECASE))
            close_count = len(re.findall(r"</script>", stripped, re.IGNORECASE))
            if open_count > close_count:
                issues.append(f"{filename}: unclosed <script> tag — likely truncated")
        if "<style" in stripped.lower():
            open_count = len(re.findall(r"<style", stripped, re.IGNORECASE))
            close_count = len(re.findall(r"</style>", stripped, re.IGNORECASE))
            if open_count > close_count:
                issues.append(f"{filename}: unclosed <style> tag — likely truncated")

    # Check for trailing truncation markers
    if stripped.endswith("...") or stripped.endswith("…"):
        issues.append(f"{filename}: content ends with ellipsis — likely truncated")

    return issues


def _check_placeholders(content: str, filename: str) -> list[str]:
    """Detect placeholder text in content."""
    issues = []
    lowered = content.lower()
    for pattern in _PLACEHOLDER_PATTERNS:
        if re.search(pattern, lowered, re.MULTILINE):
            issues.append(f"{filename}: contains placeholder text matching '{pattern}'")
            break  # One placeholder issue per file is enough
    return issues


def _check_single_file_web_integrity(content: str, filename: str) -> list[str]:
    """For single-file HTML: ensure assets stay inline when present and no sidecar refs."""
    issues = []

    if not (filename.endswith(".html") or filename.endswith(".htm")):
        return issues

    # Must NOT have sidecar references
    for pattern in _SIDECAR_PATTERNS:
        match = re.search(pattern, content, re.IGNORECASE)
        if match:
            issues.append(
                f"{filename}: references external sidecar file '{match.group(0).strip()}' — "
                f"not allowed in single-file mode"
            )

    return issues


def _check_dom_selector_crossref(content: str, filename: str) -> list[str]:
    """Cross-check: JS selectors must reference IDs/classes that exist in HTML."""
    issues = []

    if not (filename.endswith(".html") or filename.endswith(".htm")):
        return issues

    # Extract JS getElementById references
    id_refs = re.findall(
        r"""getElementById\s*\(\s*['"]([^'"]+)['"]\s*\)""",
        content,
    )

    # Extract IDs defined in the HTML markup
    defined_ids = set(re.findall(
        r"""id\s*=\s*['"]([^'"]+)['"]""",
        content,
        re.IGNORECASE,
    ))

    for ref_id in id_refs:
        if ref_id not in defined_ids:
            issues.append(
                f"{filename}: JS references getElementById('{ref_id}') but no element has id='{ref_id}'"
            )

    # Extract querySelector by ID references
    qs_id_refs = re.findall(
        r"""querySelector\s*\(\s*['"]#([^'"]+)['"]\s*\)""",
        content,
    )
    for ref_id in qs_id_refs:
        if ref_id not in defined_ids:
            issues.append(
                f"{filename}: JS references querySelector('#{ref_id}') but no element has id='{ref_id}'"
            )

    return issues


def run_deterministic_qa(generated_files: dict) -> dict:
    """
    Run all deterministic pre-checks before LLM QA.

    Returns:
        {"passed": bool, "issues": list[str], "checks_run": list[str]}
    """
    issues = []
    checks_run = []

    # Per-file checks
    for filename, content in generated_files.items():
        # Empty file check
        if not content or not content.strip():
            checks_run.append(f"empty:{filename}")
            issues.append(f"{filename} is empty")
            continue  # No point running further checks on empty file

        # Truncation
        checks_run.append(f"truncation:{filename}")
        issues.extend(_check_truncation(content, filename))

        # Placeholders (always runs)
        checks_run.append(f"placeholders:{filename}")
        issues.extend(_check_placeholders(content, filename))

        # Single-file web integrity
        checks_run.append(f"inline_assets:{filename}")
        issues.extend(_check_single_file_web_integrity(content, filename))

        # DOM selector cross-check
        if filename.endswith(".html") or filename.endswith(".htm"):
            checks_run.append(f"dom_crossref:{filename}")
            issues.extend(_check_dom_selector_crossref(content, filename))

    return {
        "passed": len(issues) == 0,
        "issues": issues,
        "checks_run": checks_run,
    }


# ═══════════════════════════════════════════
# QA Verifier Agent
# ═══════════════════════════════════════════

class QAVerifierAgent:
    """Runs deterministic and LLM-assisted QA checks on integrated artifacts."""

    json_parser = JsonOutputParser()

    def verify(self, plan: dict, generated_files: dict,
               builder_reports: list, tracer=None) -> dict:

        # ── Phase 1: Deterministic pre-checks ──
        det_result = run_deterministic_qa(generated_files)

        if not det_result["passed"]:
            # Hard fail: skip LLM QA entirely, give actionable feedback
            result = {
                "passed": False,
                "decision": "fail",
                "score": 0,
                "issues_found": det_result["issues"],
                "suggestions": [
                    f"Fix: {issue}" for issue in det_result["issues"][:5]
                ],
                "improvements": [
                    f"Fix: {issue}" for issue in det_result["issues"][:5]
                ],
                "summary": f"Deterministic QA failed with {len(det_result['issues'])} issue(s). LLM QA skipped.",
                "deterministic_qa": det_result,
            }
            if tracer:
                tracer.log("QAVerifier", "qa_done", {
                    **result,
                    "provider": "deterministic",
                    "skipped_llm": True,
                })
            return result

        # ── Phase 2: LLM-assisted QA (only if deterministic checks pass) ──
        provider = get_provider()
        provider_name = provider.get_provider_for_agent("qa_verifier")
        expected_files = set(plan.get("files_to_modify", []) or [])
        issues = []

        missing_files = sorted(expected_files - set(generated_files.keys()))
        if missing_files:
            issues.append(f"Missing generated files: {', '.join(missing_files)}")

        if issues:
            result = {
                "passed": False,
                "decision": "fail",
                "score": 0,
                "issues_found": issues,
                "suggestions": ["Regenerate missing files or adjust plan.files_to_modify"],
                "improvements": ["Regenerate missing files or adjust plan.files_to_modify"],
                "summary": "Plan/file mismatch — LLM QA skipped",
                "deterministic_qa": det_result,
            }
            if tracer:
                tracer.log("QAVerifier", "qa_done", {
                    **result,
                    "provider": "deterministic",
                    "skipped_llm": True,
                })
            return result

        prompt = QA_USER_PROMPT.format(
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
            "improvements": [] if passed else list(qa_verdict.get("suggestions", []) or []),
            "summary": qa_verdict.get("summary", "QA completed"),
            "deterministic_qa": det_result,
        }

        if not passed and not result["improvements"]:
            result["improvements"] = [f"Fix: {issue}" for issue in combined_issues[:5]]

        if tracer:
            tracer.log("QAVerifier", "qa_done", {
                **result,
                "provider": provider_name,
                "skipped_llm": False,
            })

        return result

    def _parse_json_response(self, text: str) -> dict:
        parsed = self.json_parser.parse(text)
        if isinstance(parsed, dict):
            return parsed
        raise ValueError(f"Could not parse QA response as JSON: {text[:200]}")
