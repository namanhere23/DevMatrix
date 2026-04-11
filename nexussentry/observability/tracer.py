# nexussentry/observability/tracer.py
"""
AgentTracer — Real-Time Event Logging & Dashboard Data Provider
Logs every agent action to a JSONL file and provides a thread-safe
in-memory event store that the dashboard can poll via HTTP.

Now tracks execution mode and per-task status.
"""

import json
import sys
import time
import threading
from datetime import datetime
from pathlib import Path


def _safe_print(text: str):
    """Print with safe encoding fallback for Windows cp1252 consoles."""
    try:
        print(text)
    except UnicodeEncodeError:
        # Strip or replace characters that cp1252 can't handle
        safe = text.encode(sys.stdout.encoding or "utf-8", errors="replace").decode(
            sys.stdout.encoding or "utf-8", errors="replace"
        )
        print(safe)


class AgentTracer:
    """Logs every agent action. Thread-safe for dashboard polling."""

    AGENT_ICONS = {
        "Scout": "🔍", "Architect": "🏗️",
        "Builder": "🔨", "Integrator": "🧩", "QAVerifier": "✅", "Critic": "📋",
        "HITL": "🚨", "Guardian": "🛡️", "System": "⚙️"
    }

    def __init__(self):
        self.log_dir = Path.home() / ".nexussentry" / "traces"
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.session_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.log_file = self.log_dir / f"{self.session_id}.jsonl"
        self.events: list[dict] = []
        self.start_time = time.time()
        self._lock = threading.Lock()

        # Session metadata
        self.goal = ""
        self.status = "initializing"
        self.current_agent = ""
        self.current_task = ""
        self.tasks_total = 0
        self.tasks_done = 0

        # Execution mode tracking
        self.execution_mode = "unknown"

        # Provider tracking
        self.provider_calls: dict[str, int] = {}

        # Per-task status tracking
        self.task_statuses: list[dict] = []

    def log(self, agent: str, action: str, data: dict = {}):
        """Log an agent event — thread-safe."""
        event = {
            "t": round(time.time() - self.start_time, 2),
            "ts": time.time(),
            "agent": agent,
            "action": action,
            "data": data
        }

        # Track provider usage
        provider = data.get("provider", "")
        if provider and provider != "cache":
            self.provider_calls[provider] = self.provider_calls.get(provider, 0) + 1

        # Track execution mode
        exec_mode = data.get("execution_mode", "")
        if exec_mode:
            self.execution_mode = exec_mode

        with self._lock:
            self.events.append(event)
            self.current_agent = agent

            # Track status transitions
            if action == "swarm_start":
                self.status = "running"
                self.goal = data.get("goal", "")
                self.execution_mode = data.get("execution_mode", "unknown")
            elif action == "decompose_done":
                tasks = data.get("sub_tasks", [])
                self.tasks_total = len(tasks)
            elif action.endswith("_done") and agent != "System":
                if action in ("build_done", "integrate_done", "qa_done"):
                    pass  # Task completion is still tracked at Critic approval
            elif action == "review_done":
                if data.get("decision") == "approve":
                    self.tasks_done += 1

        # Write to disk
        try:
            with open(self.log_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(event, default=str) + "\n")
        except OSError:
            pass

        # Console output
        icon = self.AGENT_ICONS.get(agent, "🤖")
        provider_tag = f" [{provider}]" if provider and provider != "cache" else ""
        exec_tag = f" [{exec_mode.upper()}]" if exec_mode and exec_mode != "unknown" else ""
        _safe_print(f"  [+{event['t']:>6.1f}s] {icon} {agent:12} → {action}{provider_tag}{exec_tag}")

    def set_current_task(self, task_desc: str):
        """Update what task is currently being worked on."""
        with self._lock:
            self.current_task = task_desc

    def record_task_status(self, task_desc: str, status: str,
                           execution_mode: str = "unknown",
                           score: int = 0, attempts: int = 0):
        """Record the final status of a completed sub-task."""
        with self._lock:
            self.task_statuses.append({
                "task": task_desc,
                "status": status,
                "execution_mode": execution_mode,
                "score": score,
                "attempts": attempts,
            })

    def mark_complete(self):
        """Mark the swarm session as complete."""
        with self._lock:
            self.status = "complete"

    def get_events_since(self, last_id: int = 0) -> list[dict]:
        """Get events since a given index — used by dashboard polling."""
        with self._lock:
            return self.events[last_id:]

    def get_dashboard_state(self) -> dict:
        """Return full state snapshot for the dashboard."""
        with self._lock:
            return {
                "session_id": self.session_id,
                "status": self.status,
                "goal": self.goal,
                "current_agent": self.current_agent,
                "current_task": self.current_task,
                "tasks_total": self.tasks_total,
                "tasks_done": self.tasks_done,
                "elapsed": round(time.time() - self.start_time, 1),
                "total_events": len(self.events),
                "events": self.events[-50:],  # Last 50 events
                "agents_used": list({e["agent"] for e in self.events}),
                "provider_calls": self.provider_calls.copy(),
                "execution_mode": self.execution_mode,
                "task_statuses": list(self.task_statuses),
            }

    def summary(self) -> dict:
        """Return final summary statistics."""
        with self._lock:
            total = round(time.time() - self.start_time, 1)
            agents = list({e["agent"] for e in self.events})
            approvals = sum(
                1 for e in self.events
                if e["action"] == "review_done"
                and e.get("data", {}).get("decision") == "approve"
            )
            rejections = sum(
                1 for e in self.events
                if e["action"] == "review_done"
                and e.get("data", {}).get("decision") == "reject"
            )
            return {
                "total_time_s": total,
                "total_events": len(self.events),
                "agents_used": agents,
                "approvals": approvals,
                "rejections": rejections,
                "log_file": str(self.log_file),
                "provider_calls": self.provider_calls.copy(),
                "execution_mode": self.execution_mode,
                "task_statuses": list(self.task_statuses),
            }
