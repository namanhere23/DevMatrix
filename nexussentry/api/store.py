"""Thread-safe run storage for the FastAPI backend."""

from __future__ import annotations

import json
import threading
import uuid
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .models import OrchestratorEngine, RunStatus


def utc_now() -> datetime:
    return datetime.now(UTC)


def _json_default(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _clone(data: Any) -> Any:
    return json.loads(json.dumps(data, default=_json_default))


class RunStore:
    """In-memory store with on-disk snapshots for run state and events."""

    def __init__(self, data_dir: Path):
        self.data_dir = data_dir
        self.runs_dir = self.data_dir / "runs"
        self.runs_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._runs: dict[str, dict[str, Any]] = {}
        self._events: dict[str, list[dict[str, Any]]] = {}
        self._idempotency: dict[str, Any] = {}
        self._load_existing_runs()

    def _load_existing_runs(self) -> None:
        for snapshot in self.runs_dir.glob("*/snapshot.json"):
            try:
                data = json.loads(snapshot.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            run_id = data.get("id")
            if not run_id:
                continue
            events_file = snapshot.parent / "events.jsonl"
            events: list[dict[str, Any]] = []
            if events_file.exists():
                try:
                    for line in events_file.read_text(encoding="utf-8").splitlines():
                        if line.strip():
                            events.append(json.loads(line))
                except (OSError, json.JSONDecodeError):
                    events = []
            self._runs[run_id] = data
            self._events[run_id] = events

    def _run_dir(self, run_id: str) -> Path:
        run_dir = self.runs_dir / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        return run_dir

    def _persist_snapshot(self, run_id: str) -> None:
        snapshot = self._run_dir(run_id) / "snapshot.json"
        snapshot.write_text(
            json.dumps(self._runs[run_id], indent=2, default=_json_default),
            encoding="utf-8",
        )

    def _append_event(self, run_id: str, event: dict[str, Any]) -> None:
        events_file = self._run_dir(run_id) / "events.jsonl"
        with events_file.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, default=_json_default) + "\n")

    def create_run(self, goal: str, engine: OrchestratorEngine) -> dict[str, Any]:
        now = utc_now()
        run_id = uuid.uuid4().hex
        run = {
            "id": run_id,
            "goal": goal,
            "engine": engine.value,
            "status": RunStatus.queued.value,
            "created_at": now,
            "updated_at": now,
            "completed_at": None,
            "current_agent": None,
            "current_task": None,
            "tasks_total": 0,
            "tasks_completed": 0,
            "trace_log": None,
            "task_results": [],
            "decision_request": None,
            "artifacts": [],
            "output": {},
            "error": None,
        }
        with self._lock:
            self._runs[run_id] = run
            self._events[run_id] = []
            self._persist_snapshot(run_id)
            return _clone(run)

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        with self._lock:
            run = self._runs.get(run_id)
            if run is None:
                return None
            return _clone(run)

    def update_run(self, run_id: str, **changes: Any) -> dict[str, Any]:
        with self._lock:
            run = self._runs[run_id]
            run.update(changes)
            run["updated_at"] = utc_now()
            if run.get("status") in {
                RunStatus.completed.value,
                RunStatus.failed.value,
                RunStatus.stopped.value,
            } and not run.get("completed_at"):
                run["completed_at"] = utc_now()
            self._persist_snapshot(run_id)
            return _clone(run)

    def append_task_result(self, run_id: str, result: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            run = self._runs[run_id]
            run["task_results"].append(result)
            run["tasks_completed"] = sum(
                1
                for item in run["task_results"]
                if item.get("status") in {"done", "accepted_current", "human_approved"}
            )
            run["updated_at"] = utc_now()
            self._persist_snapshot(run_id)
            return _clone(run)

    def set_artifacts(self, run_id: str, artifacts: list[dict[str, Any]]) -> dict[str, Any]:
        with self._lock:
            self._runs[run_id]["artifacts"] = artifacts
            self._runs[run_id]["updated_at"] = utc_now()
            self._persist_snapshot(run_id)
            return _clone(self._runs[run_id])

    def add_event(
        self,
        run_id: str,
        *,
        event_type: str,
        message: str,
        agent: str | None = None,
        action: str | None = None,
        data: dict[str, Any] | None = None,
        created_at: datetime | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            event = {
                "cursor": len(self._events[run_id]),
                "created_at": created_at or utc_now(),
                "event_type": event_type,
                "message": message,
                "agent": agent,
                "action": action,
                "data": data or {},
            }
            self._events[run_id].append(event)
            self._append_event(run_id, event)
            return _clone(event)

    def list_events(self, run_id: str, cursor: int = 0, limit: int = 200) -> tuple[list[dict[str, Any]], int]:
        with self._lock:
            events = self._events.get(run_id, [])
            window = events[cursor : cursor + limit]
            next_cursor = cursor + len(window)
            return _clone(window), next_cursor

    def total_events(self, run_id: str) -> int:
        with self._lock:
            return len(self._events.get(run_id, []))

    def get_idempotent(self, key: str) -> Any:
        with self._lock:
            return deepcopy(self._idempotency.get(key))

    def set_idempotent(self, key: str, value: Any) -> None:
        with self._lock:
            self._idempotency[key] = deepcopy(value)
