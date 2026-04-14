"""Backend orchestration service for FastAPI endpoints."""

from __future__ import annotations

import mimetypes
import os
import threading
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

from fastapi import HTTPException, status
from nexussentry.agents import (
    ArchitectAgent,
    BuilderAgent,
    CriticAgent,
    IntegratorAgent,
    QAVerifierAgent,
    ScoutAgent,
)
from nexussentry.execution.profile_selector import ExecutionProfileSelector
from nexussentry.observability.tracer import AgentTracer
from nexussentry.providers.llm_provider import get_provider
from nexussentry.utils.swarm_memory import SwarmMemory

from .models import OrchestratorEngine, RunStatus
from .store import RunStore, utc_now


DEFAULT_MAX_ATTEMPTS = 3


def project_data_dir() -> Path:
    configured = os.getenv("NEXUSSENTRY_API_DATA_DIR", "").strip()
    if configured:
        return Path(configured)
    return Path.home() / ".nexussentry" / "api"


def _format_feedback(verdict: dict[str, Any]) -> str:
    issues = ", ".join(verdict.get("issues_found", [])) or "No issues listed"
    suggestions = ", ".join(verdict.get("suggestions", [])) or "No suggestions listed"
    score = verdict.get("score", "?")
    return f"Previous attempt scored {score}/100. Issues: {issues}. Suggestions: {suggestions}"


def _status_message(status: RunStatus) -> str:
    return f"Run status changed to {status.value}"


def _tracer_message(agent: str, action: str) -> str:
    return f"{agent} {action.replace('_', ' ')}"


class BackendTracer(AgentTracer):
    """Tracer that also publishes API events and live run metadata."""

    def __init__(self, service: "RunService", run_id: str):
        super().__init__()
        self._service = service
        self._run_id = run_id

    def log(self, agent: str, action: str, data: dict = {}):  # noqa: B006
        super().log(agent, action, data)
        latest = self.events[-1]
        timestamp = datetime.fromtimestamp(latest["ts"], tz=UTC)
        self._service.record_tracer_event(
            self._run_id,
            agent=agent,
            action=action,
            data=data,
            created_at=timestamp,
        )

    def set_current_task(self, task_desc: str):
        super().set_current_task(task_desc)
        self._service.update_run(self._run_id, current_task=task_desc)


class RunService:
    """Coordinates run lifecycle, events, decisions, and artifacts."""

    def __init__(
        self,
        store: RunStore | None = None,
        *,
        guardian_factory: Callable[[], Any] | None = None,
        scout_factory: Callable[[], Any] = ScoutAgent,
        architect_factory: Callable[[], Any] = ArchitectAgent,
        builder_factory: Callable[[], Any] = BuilderAgent,
        integrator_factory: Callable[[], Any] = IntegratorAgent,
        qa_verifier_factory: Callable[[], Any] = QAVerifierAgent,
        critic_factory: Callable[[], Any] = lambda: CriticAgent(max_rejections=2),
        max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    ):
        self.store = store or RunStore(project_data_dir())
        self.guardian_factory = guardian_factory  # kept for backward compatibility
        self.scout_factory = scout_factory
        self.architect_factory = architect_factory
        self.builder_factory = builder_factory
        self.integrator_factory = integrator_factory
        self.qa_verifier_factory = qa_verifier_factory
        self.critic_factory = critic_factory
        self.max_attempts = max_attempts

    def default_engine(self) -> OrchestratorEngine:
        raw = os.getenv("ORCHESTRATOR_ENGINE", OrchestratorEngine.legacy.value)
        try:
            return OrchestratorEngine(raw)
        except ValueError:
            return OrchestratorEngine.legacy

    def create_run(
        self,
        goal: str,
        engine: OrchestratorEngine | None = None,
        *,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        effective_engine = engine or self.default_engine()
        if idempotency_key:
            cached = self.store.get_idempotent(f"run:{idempotency_key}")
            if cached:
                return self.get_run(cached["run_id"])
        run = self.store.create_run(goal, effective_engine)
        self.add_event(run["id"], "run.created", "Run queued", data={"engine": effective_engine.value})
        worker = threading.Thread(
            target=self._execute_run,
            args=(run["id"],),
            name=f"nexussentry-run-{run['id'][:8]}",
            daemon=True,
        )
        worker.start()
        if idempotency_key:
            self.store.set_idempotent(f"run:{idempotency_key}", {"run_id": run["id"]})
        return self.get_run(run["id"])

    def get_run(self, run_id: str) -> dict[str, Any]:
        run = self.store.get_run(run_id)
        if run is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"code": "run_not_found", "message": f"Run '{run_id}' was not found."},
            )
        return run

    def update_run(self, run_id: str, **changes: Any) -> dict[str, Any]:
        return self.store.update_run(run_id, **changes)

    def add_event(
        self,
        run_id: str,
        event_type: str,
        message: str,
        *,
        agent: str | None = None,
        action: str | None = None,
        data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self.store.add_event(
            run_id,
            event_type=event_type,
            message=message,
            agent=agent,
            action=action,
            data=data,
        )

    def record_tracer_event(
        self,
        run_id: str,
        *,
        agent: str,
        action: str,
        data: dict[str, Any],
        created_at: datetime,
    ) -> None:
        self.store.add_event(
            run_id,
            event_type="agent.event",
            message=_tracer_message(agent, action),
            agent=agent,
            action=action,
            data=data,
            created_at=created_at,
        )
        updates: dict[str, Any] = {"current_agent": agent}
        if action == "decompose_done":
            updates["tasks_total"] = len(data.get("sub_tasks", []))
        self.store.update_run(run_id, **updates)

    def list_events(self, run_id: str, cursor: int = 0, limit: int = 200) -> dict[str, Any]:
        self.get_run(run_id)
        events, next_cursor = self.store.list_events(run_id, cursor=cursor, limit=limit)
        return {
            "run_id": run_id,
            "cursor": cursor,
            "next_cursor": next_cursor,
            "total": self.store.total_events(run_id),
            "events": events,
        }

    def list_artifacts(self, run_id: str) -> dict[str, Any]:
        run = self.get_run(run_id)
        return {"run_id": run_id, "artifacts": run.get("artifacts", [])}

    def get_artifact_path(self, run_id: str, artifact_id: str) -> Path:
        run = self.get_run(run_id)
        for artifact in run.get("artifacts", []):
            if artifact["id"] == artifact_id:
                return Path(artifact["path"])
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "artifact_not_found", "message": f"Artifact '{artifact_id}' was not found."},
        )

    def _set_status(self, run_id: str, status_value: RunStatus, **extra: Any) -> None:
        self.store.update_run(run_id, status=status_value.value, **extra)
        self.add_event(run_id, "run.status", _status_message(status_value), data={"status": status_value.value})

    def _execute_run(self, run_id: str) -> None:
        run = self.get_run(run_id)
        tracer = BackendTracer(self, run_id)
        scout = self.scout_factory()
        architect = self.architect_factory()
        builder = self.builder_factory()
        integrator = self.integrator_factory()
        qa_verifier = self.qa_verifier_factory()
        profile_selector = ExecutionProfileSelector()
        memory = SwarmMemory()
        provider = get_provider()

        self.store.update_run(run_id, trace_log=str(tracer.log_file))
        self.add_event(
            run_id,
            "run.started",
            "Run execution started",
            data={"engine": run["engine"], "mock_mode": provider.mock_mode},
        )

        try:
            self._set_status(run_id, RunStatus.decomposing)
            decomposition = scout.decompose(run["goal"], tracer)
            sub_tasks = decomposition.get("sub_tasks", [])
            if not sub_tasks:
                self._mark_failed(run_id, "decomposition_empty", "Scout returned no sub-tasks.")
                self._finalize_artifacts(run_id, tracer)
                return

            self.store.update_run(
                run_id,
                tasks_total=len(sub_tasks),
                output={"goal_summary": decomposition.get("goal_summary", run["goal"])},
            )
            memory.record_fact("goal_summary", decomposition.get("goal_summary", run["goal"]))
            memory.record_fact("complexity", decomposition.get("estimated_complexity", "unknown"))

            for task_obj in sub_tasks:
                task_id = int(task_obj.get("id", 0) or 0)
                task_desc = task_obj.get("task", "Unknown task")
                self._set_status(run_id, RunStatus.executing, current_task=task_desc)
                terminal_status = self._execute_task(
                    run_id=run_id,
                    task_id=task_id,
                    task_desc=task_desc,
                    task_obj=task_obj,
                    architect=architect,
                    builder=builder,
                    integrator=integrator,
                    qa_verifier=qa_verifier,
                    profile_selector=profile_selector,
                    memory=memory,
                    tracer=tracer,
                )
                if terminal_status in {
                    RunStatus.completed.value,
                    RunStatus.stopped.value,
                    RunStatus.failed.value,
                }:
                    self._finalize_artifacts(run_id, tracer)
                    return

            summary = tracer.summary()
            output = self.get_run(run_id).get("output", {})
            output["summary"] = {
                "total_time_s": summary["total_time_s"],
                "total_events": summary["total_events"],
                "approvals": summary["approvals"],
                "rejections": summary["rejections"],
                "agents_used": summary["agents_used"],
            }
            self.store.update_run(run_id, status=RunStatus.completed.value, output=output)
            self.add_event(run_id, "run.completed", "Run completed successfully.")
            self._finalize_artifacts(run_id, tracer)
        except Exception as exc:  # pragma: no cover
            self._mark_failed(run_id, "backend_error", str(exc))
            self.add_event(run_id, "run.failed", "Run failed with an unhandled exception.", data={"error": str(exc)})
            self._finalize_artifacts(run_id, tracer)

    def _execute_task(
        self,
        *,
        run_id: str,
        task_id: int,
        task_desc: str,
        task_obj: dict[str, Any],
        architect: Any,
        builder: Any,
        integrator: Any,
        qa_verifier: Any,
        profile_selector: ExecutionProfileSelector,
        memory: SwarmMemory,
        tracer: BackendTracer,
    ) -> str:
        critic = self.critic_factory()
        feedback = ""
        qa_threshold = int(os.getenv("NEXUS_QA_SCORE_THRESHOLD", "70"))
        critic_threshold = int(os.getenv("NEXUS_CRITIC_SCORE_THRESHOLD", "72"))
        best_attempt_score = -1
        best_attempt: dict[str, Any] | None = None

        for attempt in range(1, self.max_attempts + 1):
            self.add_event(
                run_id,
                "task.attempt",
                f"Attempt {attempt} for task {task_id}",
                data={"task_id": task_id, "task": task_desc, "attempt": attempt},
            )
            plan_context = memory.summarize_context()
            constraints = memory.get_actionable_constraints(task_obj.get("files_to_modify", []))
            if constraints:
                plan_context = f"{plan_context}\n\n{constraints}".strip()
            try:
                plan = architect.plan(
                    sub_task=task_desc,
                    feedback=feedback,
                    context=plan_context,
                    tracer=tracer,
                    sub_task_meta=task_obj,
                )
            except TypeError:
                plan = architect.plan(
                    sub_task=task_desc,
                    feedback=feedback,
                    context=plan_context,
                    tracer=tracer,
                )

            profile = profile_selector.resolve(plan)
            dispatch = plan.get("builder_dispatch", {}) or {}
            dispatch["execution_profile"] = profile.mode
            dispatch["builder_count"] = profile.builder_count
            plan["builder_dispatch"] = dispatch

            # Execute with new pipeline: builder → verifier(score) → critic(score) → integrator(end)
            if hasattr(builder, "build"):
                builder_result = builder.build(plan, tracer)
            else:
                builder_result = builder.execute_plan(plan, tracer)

            try:
                qa_result = qa_verifier.verify(
                    plan,
                    builder_result.get("generated_files", {}),
                    builder_result.get("builder_reports", []),
                    tracer,
                )
            except TypeError:
                qa_result = qa_verifier.verify(plan, builder_result, tracer)

            qa_score = int(qa_result.get("score", 100 if qa_result.get("passed", False) else 0) or 0)
            qa_passes_threshold = qa_score >= qa_threshold
            qa_improvements = []
            if not qa_passes_threshold:
                qa_improvements = list(qa_result.get("improvements", []) or qa_result.get("suggestions", []) or [])
                if not qa_improvements:
                    qa_improvements = [f"Fix: {issue}" for issue in qa_result.get("issues_found", [])[:5]]
            qa_result["improvements"] = qa_improvements

            critic_input = {
                **builder_result,
                "qa_result": qa_result,
                "execution_mode": builder_result.get("execution_mode", "unknown"),
            }
            verdict = critic.review(task_desc, plan, critic_input, tracer)

            critic_score = int(verdict.get("score", 0) or 0)
            critic_passes_threshold = critic_score >= critic_threshold
            critic_improvements = []
            if not critic_passes_threshold:
                critic_improvements = list(verdict.get("improvements", []) or verdict.get("suggestions", []) or [])
                if not critic_improvements:
                    critic_improvements = [f"Fix: {issue}" for issue in verdict.get("issues_found", [])[:5]]
            verdict["improvements"] = critic_improvements

            combined_score = min(qa_score, critic_score)
            if combined_score > best_attempt_score:
                best_attempt_score = combined_score
                best_attempt = {
                    "plan": plan,
                    "builder_result": builder_result,
                    "qa_result": qa_result,
                    "critic_verdict": verdict,
                    "score": combined_score,
                }

            if qa_passes_threshold and critic_passes_threshold:
                integrated_result = integrator.integrate(plan, builder_result, tracer)
                if hasattr(integrator, "promote_to_final"):
                    integrator.promote_to_final(integrated_result.get("generated_files", {}))
                task_result = {
                    "task_id": task_id,
                    "task": task_desc,
                    "status": "done",
                    "attempts": attempt,
                    "score": combined_score,
                    "execution_mode": builder_result.get("execution_mode"),
                    "saved_to": integrated_result.get("saved_to", ""),
                }
                self.store.append_task_result(run_id, task_result)
                memory.record_task_result(task_id, task_desc, f"Completed with score {combined_score}")
                for path in plan.get("files_to_modify", []):
                    memory.mark_file_modified(path)
                self.add_event(
                    run_id,
                    "task.completed",
                    f"Task {task_id} completed.",
                    data={"task_id": task_id, "score": combined_score},
                )
                return RunStatus.executing.value

            feedback_payload = {
                "improvements": qa_result.get("improvements", []) + verdict.get("improvements", []),
                "qa_issues": qa_result.get("issues_found", []),
                "critic_issues": verdict.get("issues_found", []),
                "score": combined_score,
                "thresholds": {
                    "qa": qa_threshold,
                    "critic": critic_threshold,
                },
            }
            feedback = json.dumps(feedback_payload, ensure_ascii=False)
            memory.record_critic_feedback(f"Task '{task_desc}': {feedback}")

        if best_attempt is not None:
            integrated_result = integrator.integrate(best_attempt["plan"], best_attempt["builder_result"], tracer)
            if hasattr(integrator, "promote_to_final"):
                integrator.promote_to_final(integrated_result.get("generated_files", {}))
            final_score = int(best_attempt["score"])
            task_result = {
                "task_id": task_id,
                "task": task_desc,
                "status": "done",
                "attempts": self.max_attempts,
                "score": final_score,
                "execution_mode": best_attempt["builder_result"].get("execution_mode"),
                "saved_to": integrated_result.get("saved_to", ""),
                "delivery_status": "threshold_bypassed",
            }
            self.store.append_task_result(run_id, task_result)
            memory.record_task_result(task_id, task_desc, f"Passed through after retries (score {final_score})")
            for path in best_attempt["plan"].get("files_to_modify", []):
                memory.mark_file_modified(path)
            self.add_event(
                run_id,
                "task.completed",
                f"Task {task_id} passed through after retry exhaustion.",
                data={"task_id": task_id, "score": final_score, "delivery_status": "threshold_bypassed"},
            )
            return RunStatus.executing.value

        task_result = {
            "task_id": task_id,
            "task": task_desc,
            "status": "done",
            "attempts": self.max_attempts,
            "score": 0,
            "execution_mode": "unknown",
            "saved_to": "",
            "delivery_status": "threshold_bypassed",
        }
        self.store.append_task_result(run_id, task_result)
        self.add_event(
            run_id,
            "task.completed",
            f"Task {task_id} passed through with empty output after retry exhaustion.",
            data={"task_id": task_id, "score": 0, "delivery_status": "threshold_bypassed"},
        )
        return RunStatus.executing.value

    def _mark_failed(self, run_id: str, code: str, message: str) -> None:
        self.store.update_run(
            run_id,
            status=RunStatus.failed.value,
            error={"code": code, "message": message},
        )

    def _finalize_artifacts(self, run_id: str, tracer: BackendTracer) -> None:
        artifacts: list[dict[str, Any]] = []
        trace_log = Path(str(tracer.log_file))
        if trace_log.exists():
            artifacts.append(self._artifact_record(run_id, trace_log))

        run = self.get_run(run_id)
        for task_result in run.get("task_results", []):
            saved_to = task_result.get("saved_to")
            if not saved_to:
                continue
            base = Path(saved_to)
            if not base.exists():
                continue
            if base.is_file():
                artifacts.append(self._artifact_record(run_id, base))
                continue
            for path in sorted(base.rglob("*")):
                if path.is_file():
                    artifacts.append(self._artifact_record(run_id, path))

        deduped: dict[str, dict[str, Any]] = {}
        for artifact in artifacts:
            deduped[artifact["id"]] = artifact
        self.store.set_artifacts(run_id, list(deduped.values()))

    def _artifact_record(self, run_id: str, path: Path) -> dict[str, Any]:
        media_type, _ = mimetypes.guess_type(path.name)
        artifact_id = path.resolve().as_posix().replace("/", "_").replace(":", "")
        return {
            "id": artifact_id,
            "name": path.name,
            "path": str(path.resolve()),
            "size_bytes": path.stat().st_size,
            "media_type": media_type or "application/octet-stream",
            "download_url": f"/api/v1/runs/{run_id}/artifacts/{artifact_id}",
        }

    def health_live(self) -> dict[str, Any]:
        return {"status": "live", "checked_at": utc_now(), "details": {"service": "nexussentry-api"}}

    def health_ready(self) -> dict[str, Any]:
        storage_ok = self.store.data_dir.exists() and os.access(self.store.data_dir, os.W_OK)
        provider = get_provider()
        status_value = "ready" if storage_ok else "not_ready"
        return {
            "status": status_value,
            "checked_at": utc_now(),
            "details": {
                "storage_ok": storage_ok,
                "default_engine": self.default_engine().value,
                "providers_available": provider.available_providers,
                "mock_mode": provider.mock_mode,
                "execution_mode": BuilderAgent.execution_mode,
            },
        }
