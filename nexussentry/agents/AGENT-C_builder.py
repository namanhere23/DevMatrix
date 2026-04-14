"""
Agent C — Builder Pool
━━━━━━━━━━━━━━━━━━━━━━
Executes Architect plans by fanning work out to specialized builders.

Role in the swarm: Parallel implementation layer.
Provider preference: auto (with Hugging Face prompts for code generation).
"""

import logging
import ast
import re
import json
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

from langchain_core.output_parsers import JsonOutputParser
from langchain_core.prompts import PromptTemplate

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

# ═══════════════════════════════════════════════════════════════════════════
# LangChain Prompt Templates
# ═══════════════════════════════════════════════════════════════════════════

BUILDER_TASK_TEMPLATE = PromptTemplate.from_template(
    """Builder role: {builder_name}
    Assigned files: {assigned_files}
    Plan summary: {plan_summary}
    Approach: {approach}
    Overall files in task: {all_files}

    You must only work on the assigned files. Return strict JSON with builder_name,
    output, generated_files, files_modified."""
)

CODE_GEN_TEMPLATE = PromptTemplate.from_template(
    """Generate the COMPLETE, WORKING source code for: {safe_name}

PLAN: {plan_summary}
APPROACH: {approach}
ALL FILES: {all_files}

{file_type_hints}

Return only raw source code."""
)


class BuilderAgent:
    """Runs dynamic builder fan-out and returns generated artifacts."""

    MAX_BUILDERS = 5
    # In-process LLM code generation (no external sandbox binary).
    execution_mode = "python"

    def build(self, plan: dict, tracer=None) -> dict:
        """Run specialized builders according to Architect dispatch metadata."""
        files_to_modify = plan.get("files_to_modify", []) or []
        provider = get_provider()
        provider_name = provider.get_provider_for_agent("builder")

        if tracer:
            tracer.log("Builder", "build_start", {
                "provider": provider_name,
                "execution_mode": self.execution_mode,
            })

        if not files_to_modify:
            result = {
                "success": True,
                "execution_mode": self.execution_mode,
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
        execution_profile = str(dispatch.get("execution_profile", "sequential")).lower()
        builder_count = max(1, min(self.MAX_BUILDERS, requested_builders, len(files_to_modify)))
        file_groups = self._partition_files(files_to_modify, builder_count)

        if execution_profile == "parallel" and len(file_groups) > 1:
            reports = self._run_parallel_builders(plan, provider, files_to_modify, file_groups)
        else:
            reports = [
                self._run_builder_slot(idx, group, plan, provider, files_to_modify)
                for idx, group in enumerate(file_groups, start=1)
            ]

        reports.sort(key=lambda report: report.get("builder_name", ""))

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
            "execution_mode": self.execution_mode,
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
                "execution_profile": execution_profile,
                "builders_used": len(reports),
                "files_modified": result["files_modified"],
            })

        return result

    def _run_parallel_builders(self, plan: dict, provider, files_to_modify: list[str], file_groups: list[list[str]]) -> list[dict]:
        reports: list[dict] = []
        max_workers = max(1, min(len(file_groups), self.MAX_BUILDERS))
        with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="builder-slot") as executor:
            futures = [
                executor.submit(self._run_builder_slot, idx, group, plan, provider, files_to_modify)
                for idx, group in enumerate(file_groups, start=1)
            ]
            for future in as_completed(futures):
                reports.append(future.result())
        return reports

    def _run_builder_slot(self, idx: int, group: list[str], plan: dict, provider, files_to_modify: list[str]) -> dict:
        builder_name = f"builder-{idx}"
        
        # Use LangChain template to format prompt
        prompt = BUILDER_TASK_TEMPLATE.format(
            builder_name=builder_name,
            assigned_files=', '.join(group),
            plan_summary=plan.get('plan_summary', ''),
            approach=plan.get('approach', ''),
            all_files=', '.join(files_to_modify),
        )

        raw = provider.chat(
            system=BUILDER_SYSTEM,
            user_msg=prompt,
            max_tokens=3000,
            prefer="auto",
            agent_name="builder",
        )
        
        # Use wrapper method for backward compatibility with mocking
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

        return report

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

            # Use LangChain template to format prompt
            prompt = CODE_GEN_TEMPLATE.format(
                safe_name=safe_name,
                plan_summary=plan_summary,
                approach=approach,
                all_files=', '.join(files_to_modify),
                file_type_hints=file_type_hints,
            )

            raw_code = provider.chat(
                system=CODE_GEN_SYSTEM,
                user_msg=prompt,
                max_tokens=4000,
                agent_name="builder",
            )
            code = self._clean_code_response(raw_code)
            if code and len(code.strip()) > 20:
                generated_files[safe_name] = code

        return generated_files

    def _get_file_type_hints(self, ext: str) -> str:
        if ext == ".html":
            return (
                "CRITICAL: HTML must be COMPLETELY STANDALONE.\n"
                "- ALL CSS must be inside <style> tags in the <head>. Do NOT use <link> to external .css files.\n"
                "- ALL JavaScript must be inside <script> tags. Do NOT use <script src='...'> to external .js files.\n"
                "- Do NOT reference any external files (no style.css, no script.js, no images from relative paths).\n"
                "- The file must be fully functional when opened directly in a browser with no server.\n"
                "- Include responsive design, modern styling, and proper semantic HTML5."
            )
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
        """Parse JSON response using LangChain's JsonOutputParser with fallback."""
        try:
            # Primary: LangChain's JsonOutputParser
            parsed = self.json_parser.parse(text)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            pass

        # Fallback: Regex extraction + json.loads
        json_block = re.search(r"\{[\s\S]*\}", text)
        if json_block:
            candidate = json_block.group(0)
            try:
                parsed_json = json.loads(candidate)
                if isinstance(parsed_json, dict):
                    return parsed_json
            except Exception:
                pass

            # Secondary fallback: ast.literal_eval
            try:
                parsed_literal = ast.literal_eval(candidate)
                if isinstance(parsed_literal, dict):
                    return parsed_literal
            except Exception:
                pass

        return {
            "output": text[:200],
            "generated_files": {},
            "files_modified": [],
            "commands_run": [],
            "errors": ["Could not parse builder response as JSON"],
        }
