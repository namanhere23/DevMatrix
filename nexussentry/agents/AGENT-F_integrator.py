"""
Agent D — Integrator
━━━━━━━━━━━━━━━━━━━━
Merges builder outputs into a single coherent artifact set and saves files.

Uses RunContext to write into one canonical run directory:
    output/session_<run_id>/
    ├── attempts/task_<id>/attempt_<n>/   ← retry snapshots
    ├── final/                            ← best delivered artifacts
    └── manifest.json                     ← run summary
"""

import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger("Integrator")

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


class IntegratorAgent:
    """Integrates builder outputs and writes artifacts to canonical run directories."""

    def __init__(self, run_context=None):
        self.run_context = run_context
        # Fallback for legacy usage without RunContext
        self.output_dir = PROJECT_ROOT / "output"

    def integrate(self, plan: dict, builder_result: dict, tracer=None,
                  task_id: int = 0) -> dict:
        reports = builder_result.get("builder_reports", [])
        merged_files = {}
        conflicts = []
        summaries = []
        conflict_details = []

        if tracer:
            tracer.log("Integrator", "integrate_start", {
                "builders_used": len(reports),
                "task_id": task_id,
            })

        for report in reports:
            summaries.append(report.get("output", "").strip())
            builder_name = report.get("builder_name", "unknown")
            for filename, content in report.get("generated_files", {}).items():
                if filename in merged_files and merged_files[filename] != content:
                    conflicts.append(filename)
                    conflict_details.append({
                        "file": filename,
                        "builder": builder_name,
                        "resolution": "keep_longest",
                    })
                    # Conflict resolution: keep the longer (more complete) version
                    if len(content) >= len(merged_files[filename]):
                        logger.warning(
                            f"Integration conflict on '{filename}' — "
                            f"keeping longer version from builder '{builder_name}'."
                        )
                        merged_files[filename] = content
                    else:
                        logger.warning(
                            f"Integration conflict on '{filename}' — "
                            f"keeping existing (longer) version."
                        )
                else:
                    merged_files[filename] = content

        if not reports:
            merged_files.update(builder_result.get("generated_files", {}))

        integrator_summary = " ".join(part for part in summaries if part)
        if conflicts:
            integrator_summary = (
                f"Integrated builder outputs with HARD CONFLICTS on: {', '.join(sorted(set(conflicts)))}. "
                f"{integrator_summary}".strip()
            )
        elif not integrator_summary:
            integrator_summary = "Integrated builder outputs successfully."

        # Save to attempt directory (within canonical run structure)
        attempt_dir, saved_files = self._save_to_attempt_dir(
            merged_files, task_id,
            plan.get("plan_summary", "Unknown task"),
        )

        result = {
            "generated_files": merged_files,
            "integrator_summary": integrator_summary,
            "integration_conflicts": sorted(set(conflicts)),
            "conflict_details": conflict_details,
            "saved_to": str(attempt_dir) if attempt_dir else "",
            "saved_files": saved_files,
        }

        if tracer:
            tracer.log("Integrator", "integrate_done", {
                "files_saved": len(saved_files),
                "integration_conflicts": result["integration_conflicts"],
                "attempt_dir": str(attempt_dir) if attempt_dir else "",
            })

        return result

    def promote_to_final(self, generated_files: dict):
        """Copy approved artifacts into the final/ directory."""
        if not generated_files or not self.run_context:
            return

        final_dir = self.run_context.final_artifact_dir
        saved_files = self._write_generated_files(
            final_dir,
            generated_files,
            allowed_files=None,
        )
        for saved_path in saved_files:
            rel_path = Path(saved_path).relative_to(final_dir).as_posix()
            logger.info(f"Promoted '{rel_path}' to final/")

    def save_snapshot(self, snapshot_dir: Path, generated_files: dict) -> list[str]:
        """Persist a generated-file snapshot while preserving relative paths."""
        return self._write_generated_files(snapshot_dir, generated_files)

    def write_manifest(self, goal: str, tasks: list, summary: dict,
                       provider_stats: dict):
        """Write manifest.json summarizing the entire run."""
        if not self.run_context:
            return

        # Collect final artifact filenames
        final_dir = self.run_context.final_artifact_dir
        final_files = []
        if final_dir.exists():
            final_files = sorted(
                f.relative_to(final_dir).as_posix()
                for f in final_dir.rglob("*")
                if f.is_file()
            )

        provider_failures = list(provider_stats.get("failure_log", []))
        provider_failures.extend(self.run_context.provider_failures)

        manifest = {
            "run_id": self.run_context.run_id,
            "generated_at": datetime.now().isoformat(),
            "goal": goal,
            "tasks": [
                {
                    "task_id": t.get("task_id"),
                    "task": t.get("task", ""),
                    "status": t.get("status", "unknown"),
                    "score": t.get("score", 0),
                    "attempts": t.get("attempts", 0),
                    "execution_mode": t.get("execution_mode", "unknown"),
                    "delivery_status": t.get("delivery_status", "unknown"),
                }
                for t in tasks if isinstance(t, dict)
            ],
            "attempts": dict(self.run_context.attempt_index_by_task),
            "final_artifacts": final_files,
            "provider_failures": provider_failures,
            "summary": {
                "total_time_s": summary.get("total_time_s", 0),
                "total_events": summary.get("total_events", 0),
                "approvals": summary.get("approvals", 0),
                "rejections": summary.get("rejections", 0),
                "provider_usage": provider_stats.get("provider_usage", {}),
            },
        }

        manifest_path = self.run_context.run_output_dir / "manifest.json"
        manifest_path.write_text(
            json.dumps(manifest, indent=2, default=str),
            encoding="utf-8",
        )
        logger.info(f"Manifest written to {manifest_path}")

    def _save_to_attempt_dir(self, generated_files: dict, task_id: int,
                              task_desc: str):
        """Save generated files to the current attempt directory."""
        if not generated_files:
            return None, []

        if self.run_context:
            attempt_dir = self.run_context.get_attempt_dir(task_id)
        else:
            # Legacy fallback: use old session-per-call behavior
            attempt_dir = self._get_legacy_session_dir()

        saved_files = self._write_generated_files(attempt_dir, generated_files)

        # Write attempt README
        readme_path = attempt_dir / "README.md"
        if not readme_path.exists():
            readme_path.write_text(
                f"""# NexusSentry Generated Output — Attempt Snapshot

**Task:** {task_desc}
**Task ID:** {task_id}
**Generated at:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
**Files generated:** {len(saved_files)}

## Files
{chr(10).join(f'- `{Path(f).relative_to(attempt_dir).as_posix()}`' for f in saved_files)}

---
*Generated by NexusSentry Agent Swarm*
""",
                encoding="utf-8",
            )

        return attempt_dir, saved_files

    def _write_generated_files(
        self,
        base_dir: Path,
        generated_files: dict,
        allowed_files: Optional[set[str]] = None,
    ) -> list[str]:
        """Write generated files under base_dir while preserving relative layout."""
        if not generated_files:
            return []

        base_dir.mkdir(parents=True, exist_ok=True)
        saved_files: list[str] = []

        for filename, content in generated_files.items():
            rel_path = self._sanitize_relative_path(filename)
            if rel_path is None:
                logger.warning(f"Skipping unsafe generated path '{filename}'.")
                continue

            rel_posix = rel_path.as_posix()
            if allowed_files and rel_posix not in allowed_files and rel_path.name not in allowed_files:
                logger.info(f"Skipping '{rel_posix}' — not in allowed output files.")
                continue

            path = base_dir / rel_path
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
            saved_files.append(str(path))

        return saved_files

    def _sanitize_relative_path(self, filename: str) -> Optional[Path]:
        """Normalize a generated path into a safe relative filesystem path."""
        raw = str(filename).strip().replace("\\", "/")
        if not raw:
            return None

        if raw.startswith("/") or raw.startswith("\\") or re.match(r"^[A-Za-z]:", raw):
            return None

        parts = []
        for part in raw.split("/"):
            if not part or part == ".":
                continue
            if part == "..":
                return None

            safe_part = re.sub(r'[<>:"|?*]', '_', part)
            if not safe_part:
                return None
            parts.append(safe_part)

        if not parts:
            return None

        return Path(*parts)

    def _get_legacy_session_dir(self) -> Path:
        """Legacy: create a timestamped session dir (used only without RunContext)."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        session_dir = self.output_dir / f"session_{timestamp}"
        session_dir.mkdir(parents=True, exist_ok=True)
        return session_dir
