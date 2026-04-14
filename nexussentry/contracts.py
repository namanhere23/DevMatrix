# nexussentry/contracts.py
"""
╔═══════════════════════════════════════════════════════════╗
║                     RunContext                            ║
║                                                           ║
║  Run-scoped state shared across the orchestration flow.   ║
╚═══════════════════════════════════════════════════════════╝
"""

from dataclasses import dataclass, field
from pathlib import Path


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
