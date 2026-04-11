"""
Agent C — Builder Pool
━━━━━━━━━━━━━━━━━━━━━━
Executes Architect plans by fanning work out to specialized builders.

Role in the swarm: Parallel implementation layer.
Provider preference: auto (with Hugging Face prompts for code generation).
"""

import json
import logging
import re
from pathlib import Path

from nexussentry.adapters.claw_bridge import ClawBridge
from nexussentry.providers.llm_provider import get_provider

logger = logging.getLogger("Builder")

BUILDER_SYSTEM = """You are one specialized builder in a multi-agent execution pipeline.
You receive a narrow slice of the overall plan and must produce production-quality code only
for the files assigned to you.

Respond ONLY with valid JSON:
{
  "builder_name": "builder-1",
  "output": "short summary of what was built",
  "generated_files": {"file.py": "full file contents"},
  "files_modified": ["file.py"],
  "commands_run": ["pytest ..."],
  "errors": []
}"""

CODE_GEN_SYSTEM = """You are an expert full-stack developer. You write COMPLETE, WORKING,
PRODUCTION-QUALITY code. Never return placeholders, TODO comments, or partial snippets.
Respond ONLY with the raw source code for the target file."""

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


class BuilderAgent:
    """Runs dynamic builder fan-out and returns generated artifacts."""

    MAX_BUILDERS = 5

    def __init__(self):
        self.claw = ClawBridge()

    def build(self, plan: dict, tracer=None) -> dict:
        """Run specialized builders according to Architect dispatch metadata."""
        files_to_modify = plan.get("files_to_modify", []) or []
        provider = get_provider()
        provider_name = provider.get_provider_for_agent("builder")

        if tracer:
            tracer.log("Builder", "build_start", {
                "provider": provider_name,
                "execution_mode": self.claw.execution_mode,
            })

        if not files_to_modify:
            result = {
                "success": True,
                "execution_mode": self.claw.execution_mode,
                "builder_reports": [],
                "generated_files": {},
                "files_modified": [],
                "commands_run": [],
                "elapsed": 0,
            }
            if tracer:
                tracer.log("Builder", "build_done", result)
            return result

        dispatch = plan.get("builder_dispatch", {}) or {}
        requested_builders = int(dispatch.get("builder_count", 1) or 1)
        builder_count = max(1, min(self.MAX_BUILDERS, requested_builders, len(files_to_modify)))
        file_groups = self._partition_files(files_to_modify, builder_count)

        reports = []
        for idx, group in enumerate(file_groups, start=1):
            builder_name = f"builder-{idx}"
            prompt = f"""Builder role: {builder_name}
Assigned files: {', '.join(group)}
Plan summary: {plan.get('plan_summary', '')}
Approach: {plan.get('approach', '')}
Overall files in task: {', '.join(files_to_modify)}

You must only work on the assigned files. Return strict JSON with builder_name,
output, generated_files, files_modified, commands_run, and errors."""

            raw = provider.chat(
                system=BUILDER_SYSTEM,
                user_msg=prompt,
                max_tokens=3000,
                prefer="huggingface",
                agent_name="builder",
            )
            report = self._parse_json_response(raw)
            report.setdefault("builder_name", builder_name)
            report.setdefault("output", "")
            report.setdefault("generated_files", {})
            report.setdefault("files_modified", list(report.get("generated_files", {}).keys()))
            report.setdefault("commands_run", [])
            report.setdefault("errors", [])

            if not report["generated_files"]:
                report["generated_files"] = self._generate_code_files(
                    {**plan, "files_to_modify": group},
                    provider,
                )
                report["files_modified"] = list(report["generated_files"].keys())

            reports.append(report)

        generated_files = {}
        files_modified = []
        commands_run = []
        total_errors = []
        for report in reports:
            generated_files.update(report.get("generated_files", {}))
            files_modified.extend(report.get("files_modified", []))
            commands_run.extend(report.get("commands_run", []))
            total_errors.extend(report.get("errors", []))

        result = {
            "success": len(total_errors) == 0,
            "execution_mode": self.claw.execution_mode,
            "builder_reports": reports,
            "generated_files": generated_files,
            "files_modified": sorted(set(files_modified)),
            "commands_run": commands_run,
            "errors": total_errors,
            "elapsed": 0,
        }

        if tracer:
            tracer.log("Builder", "build_done", {
                "provider": provider_name,
                "execution_mode": result["execution_mode"],
                "builders_used": len(reports),
                "files_modified": result["files_modified"],
            })

        return result

    def _partition_files(self, files_to_modify: list, builder_count: int) -> list:
        """Split files into one group per active builder."""
        if not files_to_modify:
            return []

        group_count = max(1, min(builder_count, len(files_to_modify)))
        base_size, remainder = divmod(len(files_to_modify), group_count)

        groups = []
        start = 0
        for i in range(group_count):
            size = base_size + (1 if i < remainder else 0)
            end = start + size
            groups.append(files_to_modify[start:end])
            start = end

        return groups

    def _generate_code_files(self, plan: dict, provider) -> dict:
        files_to_modify = plan.get("files_to_modify", [])
        plan_summary = plan.get("plan_summary", "")
        approach = plan.get("approach", "")
        generated_files = {}

        for filename in files_to_modify:
            safe_name = re.sub(r'[<>:"|?*]', '_', Path(filename).name)
            if not safe_name:
                continue

            ext = Path(safe_name).suffix.lower()
            file_type_hints = self._get_file_type_hints(ext)

            prompt = f"""Generate the COMPLETE, WORKING source code for: {safe_name}

PLAN: {plan_summary}
APPROACH: {approach}
ALL FILES: {', '.join(files_to_modify)}

{file_type_hints}

Return only raw source code."""

            try:
                raw_code = provider.chat(
                    system=CODE_GEN_SYSTEM,
                    user_msg=prompt,
                    max_tokens=4000,
                    agent_name="builder",
                )
                code = self._clean_code_response(raw_code)
                if code and len(code.strip()) > 20:
                    generated_files[safe_name] = code
            except Exception as exc:
                logger.warning("Code generation failed for %s: %s", safe_name, exc)

        return generated_files

    def _get_file_type_hints(self, ext: str) -> str:
        if ext == ".html":
            return "HTML must be standalone with inline CSS and JS, no templates."
        if ext == ".py":
            return "Include imports, complete function bodies, and error handling."
        if ext in {".js", ".ts"}:
            return "Use modern syntax and complete executable logic."
        if ext == ".css":
            return "Return a complete stylesheet, not partial snippets."
        return f"Generate complete production-quality code for {ext} files."

    def _clean_code_response(self, raw: str) -> str:
        code = raw.strip()
        block_match = re.match(
            r'^```(?:html|css|javascript|js|python|py|jsx|tsx|typescript)?\s*\n(.*?)```\s*$',
            code,
            re.DOTALL | re.IGNORECASE,
        )
        if block_match:
            code = block_match.group(1)
        if code.startswith("```") and code.endswith("```"):
            lines = code.split("\n")
            code = "\n".join(lines[1:-1])
        return code.strip()

    def _parse_json_response(self, text: str) -> dict:
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

        return {
            "output": text[:200],
            "generated_files": {},
            "files_modified": [],
            "commands_run": [],
            "errors": ["Could not parse builder response as JSON"],
        }
