# nexussentry/contracts.py
"""
╔═══════════════════════════════════════════════════════════╗
║          GoalContract & RunContext                        ║
║                                                           ║
║  Run-scoped types that constrain swarm output so agents   ║
║  understand hard delivery requirements up front.          ║
╚═══════════════════════════════════════════════════════════╝
"""

import hashlib
import json
import re
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional


@dataclass
class GoalContract:
    """
    Immutable contract derived from the user goal before any agent runs.

    Fields:
        single_file:            All output must be in one file.
        allowed_output_files:   Exhaustive list of permitted final artifact filenames.
        requires_inline_assets: CSS/JS must be inline (no external links).
        allow_sidecar_assets:   Whether separate CSS/JS/image files are acceptable.
        requires_tests:         Whether test files are expected as deliverables.
        preferred_entrypoint:   The main file the user expects to open/run.
        parallelism_mode:       "serialized" (linear chain) or "parallel" (wave).
    """

    single_file: bool = False
    allowed_output_files: list[str] = field(default_factory=list)
    requires_inline_assets: bool = False
    allow_sidecar_assets: bool = True
    requires_tests: bool = False
    preferred_entrypoint: str = ""
    parallelism_mode: str = "parallel"  # "serialized" | "parallel"

    def fingerprint(self) -> str:
        """Deterministic hash for cache-key differentiation."""
        raw = json.dumps(asdict(self), sort_keys=True)
        return hashlib.md5(raw.encode()).hexdigest()[:12]

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class RunContext:
    """
    Shared across the entire swarm for one user invocation.

    Provides a single canonical output directory structure:
        output/session_<run_id>/
        ├── attempts/task_<id>/attempt_<n>/   ← retry snapshots
        ├── final/                            ← approved artifacts
        └── manifest.json                     ← run summary
    """

    run_id: str
    run_output_dir: Path
    goal_contract: GoalContract
    attempt_index_by_task: dict = field(default_factory=dict)
    provider_failures: list[dict[str, str]] = field(default_factory=list)

    @property
    def final_artifact_dir(self) -> Path:
        return self.run_output_dir / "final"

    @property
    def attempts_dir(self) -> Path:
        return self.run_output_dir / "attempts"

    def get_attempt_dir(self, task_id: int) -> Path:
        """Get the directory for the current attempt of a task, auto-incrementing."""
        attempt_num = self.attempt_index_by_task.get(task_id, 0) + 1
        self.attempt_index_by_task[task_id] = attempt_num
        attempt_dir = self.attempts_dir / f"task_{task_id}" / f"attempt_{attempt_num}"
        attempt_dir.mkdir(parents=True, exist_ok=True)
        return attempt_dir

    def current_attempt_index(self, task_id: int) -> int:
        return self.attempt_index_by_task.get(task_id, 0)

    def record_provider_failure(self, provider: str, error: str, agent: str = "") -> None:
        """Attach provider failures that should be surfaced in the run manifest."""
        self.provider_failures.append({
            "provider": provider,
            "error": error,
            "agent": agent,
        })




# ═══════════════════════════════════════════
# Contract Inference
# ═══════════════════════════════════════════

# Keywords that signal a single-file web deliverable
_SINGLE_FILE_WEB_KEYWORDS = [
    r"single\s+file",
    r"one\s+file",
    r"single\s+html",
    r"in\s+a\s+single\s+html",
    r"complete\s+.*\s+in\s+(one|a single)\s+file",
    r"standalone\s+html",
    r"self[- ]contained\s+html",
    r"all\s+in\s+one\s+file",
    r"single[- ]page",
]

_WEB_PROJECT_KEYWORDS = [
    r"html", r"webpage", r"web\s*page", r"website",
    r"landing\s*page", r"shopping\s*cart", r"calculator",
    r"todo\s*app", r"to[- ]?do\s+list", r"form",
    r"dashboard", r"portfolio",
]

_MULTI_FILE_KEYWORDS = [
    r"\bapi\b", r"rest\s*api", r"microservice",
    r"backend", r"server", r"database",
    r"models?\s+and\s+routes", r"multiple\s+files",
    r"project\s+structure", r"modules?",
]

_TEST_KEYWORDS = [
    r"with\s+tests?", r"unit\s+tests?", r"test\s+suite",
    r"tdd", r"test[- ]driven",
]


def _matches_any(text: str, patterns: list[str]) -> bool:
    """Check if text matches any of the given regex patterns."""
    for pattern in patterns:
        if re.search(pattern, text, re.IGNORECASE):
            return True
    return False


def derive_goal_contract(user_goal: str) -> GoalContract:
    """
    Derive a GoalContract from the user's goal text using keyword heuristics.

    No LLM call needed — this is fast and deterministic.
    """
    goal_lower = user_goal.lower()

    is_single_file = _matches_any(goal_lower, _SINGLE_FILE_WEB_KEYWORDS)
    is_web = _matches_any(goal_lower, _WEB_PROJECT_KEYWORDS)
    is_multi = _matches_any(goal_lower, _MULTI_FILE_KEYWORDS)
    wants_tests = _matches_any(goal_lower, _TEST_KEYWORDS)

    # Single-file web page mode
    if is_single_file:
        return GoalContract(
            single_file=True,
            allowed_output_files=["index.html"],
            requires_inline_assets=True,
            allow_sidecar_assets=False,
            requires_tests=wants_tests,
            preferred_entrypoint="index.html",
            parallelism_mode="serialized",
        )

    # Multi-file project mode
    if is_multi or is_web:
        return GoalContract(
            single_file=False,
            allowed_output_files=[],  # empty = no restriction
            requires_inline_assets=False,
            allow_sidecar_assets=True,
            requires_tests=wants_tests,
            preferred_entrypoint="index.html" if is_web else "",
            parallelism_mode="parallel",
        )

    # Default: permissive contract
    return GoalContract(
        single_file=False,
        allowed_output_files=[],
        requires_inline_assets=False,
        allow_sidecar_assets=True,
        requires_tests=wants_tests,
        preferred_entrypoint="",
        parallelism_mode="parallel",
    )
