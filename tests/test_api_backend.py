import shutil
import time
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from nexussentry.api.app import create_app
from nexussentry.api.service import RunService
from nexussentry.api.store import RunStore


class StubGuardian:
    def __init__(self, safe=True):
        self.safe = safe

    def scan(self, text, tracer=None):
        if tracer:
            tracer.log("Guardian", "scan_start", {"goal": text})
        if self.safe:
            if tracer:
                tracer.log("Guardian", "scan_clear", {"safe": True})
            return {"safe": True, "layers_passed": 7}
        result = {"safe": False, "layer": 1, "reason": "blocked for test"}
        if tracer:
            tracer.log("Guardian", "threat_blocked", result)
        return result


class StubScout:
    def decompose(self, goal, tracer=None):
        result = {
            "goal_summary": f"Goal: {goal}",
            "sub_tasks": [{"id": 1, "task": "Implement backend flow", "priority": "high"}],
            "estimated_complexity": "medium",
        }
        if tracer:
            tracer.log("Scout", "decompose_start", {"goal": goal})
            tracer.log("Scout", "decompose_done", result)
        return result


class StubArchitect:
    def plan(self, sub_task, feedback="", context="", tracer=None):
        plan = {
            "plan_summary": f"Plan for {sub_task}",
            "approach": "Follow backend contract",
            "files_to_read": ["README.md"],
            "files_to_modify": ["api.py"],
            "commands_to_run": ["pytest"],
            "success_criteria": "API works",
            "risks": [],
        }
        if tracer:
            tracer.log("Architect", "plan_start", {"task": sub_task, "feedback": feedback})
            tracer.log("Architect", "plan_done", plan)
        return plan


class StubBuilder:
    def __init__(self, artifact_dir: Path = None):
        self.artifact_dir = artifact_dir or Path.cwd()

    def execute_plan(self, plan, tracer=None):
        result = {
            "success": True,
            "builder_reports": [{"file": "api.py", "status": "success"}],
            "execution_mode": "mock",
        }
        if tracer:
            tracer.log("Builder", "execute_start", {"files": plan.get("files_to_modify", [])})
            tracer.log("Builder", "execute_done", result)
        return result


class StubIntegrator:
    def integrate(self, plan, builder_result, tracer=None):
        self.artifact_dir = Path.cwd() / ".artifacts"
        self.artifact_dir.mkdir(parents=True, exist_ok=True)
        artifact = self.artifact_dir / "result.txt"
        artifact.write_text("integrated artifact", encoding="utf-8")
        result = {
            "success": True,
            "files_written": ["api.py"],
            "saved_to": str(self.artifact_dir),
            "execution_mode": "mock",
        }
        if tracer:
            tracer.log("Integrator", "integrate_done", result)
        return result


class StubQAVerifier:
    def verify(self, plan, integrated_result, tracer=None):
        result = {
            "decision": "pass",
            "score": 90,
            "issues_found": [],
            "suggestions": [],
            "summary": "All checks passed",
        }
        if tracer:
            tracer.log("QAVerifier", "verify_done", result)
        return result


class StubFixer:
    def __init__(self, artifact_dir: Path):
        self.artifact_dir = artifact_dir

    def execute(self, plan, tracer=None):
        self.artifact_dir.mkdir(parents=True, exist_ok=True)
        artifact = self.artifact_dir / "result.txt"
        artifact.write_text("backend artifact", encoding="utf-8")
        result = {
            "success": True,
            "output": "implemented",
            "files_modified": ["api.py"],
            "commands_run": ["pytest"],
            "errors": [],
            "elapsed": 0.01,
            "execution_mode": "simulated",
            "saved_to": str(self.artifact_dir),
        }
        if tracer:
            tracer.log("Fixer", "execute_start", {"plan": plan["plan_summary"], "execution_mode": "simulated"})
            tracer.log("Fixer", "execute_done", result)
        return result


class SequenceCritic:
    def __init__(self, decisions):
        self.decisions = list(decisions)

    def review(self, original_task, plan, fixer_result, tracer=None):
        verdict = self.decisions.pop(0)
        if tracer:
            tracer.log("Critic", "review_start", {"task": original_task})
            tracer.log("Critic", "review_done", verdict)
        return verdict


def make_client(tmp_path, critic_sequences, guardian_safe=True):
    critic_sequences = [list(seq) for seq in critic_sequences]

    def critic_factory():
        return SequenceCritic(critic_sequences.pop(0))

    artifact_dir = tmp_path / "artifacts"
    service = RunService(
        store=RunStore(tmp_path / "store"),
        guardian_factory=lambda: StubGuardian(safe=guardian_safe),
        scout_factory=StubScout,
        architect_factory=StubArchitect,
        builder_factory=StubBuilder,
        integrator_factory=StubIntegrator,
        qa_verifier_factory=StubQAVerifier,
        critic_factory=critic_factory,
        decision_timeout_seconds=1,
        max_attempts=3,
    )
    return TestClient(create_app(service)), artifact_dir


@pytest.fixture
def workspace_tmp():
    root = Path(__file__).resolve().parent / ".tmp_api_tests" / uuid.uuid4().hex
    root.mkdir(parents=True, exist_ok=True)
    try:
        yield root
    finally:
        shutil.rmtree(root, ignore_errors=True)


def wait_for_status(client, run_id, target_statuses, timeout=5):
    deadline = time.time() + timeout
    while time.time() < deadline:
        response = client.get(f"/api/v1/runs/{run_id}")
        response.raise_for_status()
        data = response.json()
        if data["status"] in target_statuses:
            return data
        time.sleep(0.05)
    raise AssertionError(f"Timed out waiting for statuses {target_statuses}")


def wait_for_artifacts(client, run_id, timeout=5):
    deadline = time.time() + timeout
    while time.time() < deadline:
        artifacts = client.get(f"/api/v1/runs/{run_id}/artifacts").json()["artifacts"]
        if artifacts:
            return artifacts
        time.sleep(0.05)
    raise AssertionError("Timed out waiting for artifacts")


def test_approve_complete_path_and_artifacts(workspace_tmp):
    client, _ = make_client(
        workspace_tmp,
        critic_sequences=[[
            {"decision": "approve", "score": 92, "issues_found": [], "suggestions": []}
        ]],
    )

    created = client.post("/api/v1/runs", json={"goal": "Build backend"}).json()
    run = wait_for_status(client, created["id"], {"completed"})

    assert run["tasks_completed"] == 1
    assert run["task_results"][0]["status"] == "done"

    artifacts = wait_for_artifacts(client, created["id"])
    download = client.get(artifacts[0]["download_url"])
    assert download.status_code == 200


def test_reject_retry_approve_path(workspace_tmp):
    client, _ = make_client(
        workspace_tmp,
        critic_sequences=[[
            {"decision": "reject", "score": 60, "issues_found": ["missing validation"], "suggestions": ["retry"]},
            {"decision": "escalate_to_human", "score": 55, "issues_found": ["still wrong"], "suggestions": ["retry again"]},
            {"decision": "approve", "score": 89, "issues_found": [], "suggestions": []},
        ]],
    )

    created = client.post("/api/v1/runs", json={"goal": "Build backend"}).json()
    waiting = wait_for_status(client, created["id"], {"awaiting_decision"})
    assert waiting["decision_request"]["task"] == "Implement backend flow"

    decision = client.post(
        f"/api/v1/runs/{created['id']}/decision",
        json={"action": "retry", "reason": "one more pass", "actor": "tester"},
    )
    assert decision.status_code == 200

    run = wait_for_status(client, created["id"], {"completed"})
    assert run["task_results"][0]["attempts"] == 3
    assert run["task_results"][0]["status"] == "done"


def test_reject_accept_current_path(workspace_tmp):
    client, _ = make_client(
        workspace_tmp,
        critic_sequences=[[
            {"decision": "reject", "score": 61, "issues_found": ["missing validation"], "suggestions": ["retry"]},
            {"decision": "escalate_to_human", "score": 58, "issues_found": ["still wrong"], "suggestions": ["accept or stop"]},
        ]],
    )

    created = client.post("/api/v1/runs", json={"goal": "Build backend"}).json()
    wait_for_status(client, created["id"], {"awaiting_decision"})

    client.post(
        f"/api/v1/runs/{created['id']}/decision",
        json={"action": "accept_current", "reason": "good enough", "actor": "tester"},
    )
    run = wait_for_status(client, created["id"], {"completed"})

    assert run["task_results"][0]["status"] == "accepted_current"
    assert "accepted_current" in run["output"]


def test_reject_stop_path(workspace_tmp):
    client, _ = make_client(
        workspace_tmp,
        critic_sequences=[[
            {"decision": "reject", "score": 61, "issues_found": ["missing validation"], "suggestions": ["retry"]},
            {"decision": "escalate_to_human", "score": 58, "issues_found": ["still wrong"], "suggestions": ["accept or stop"]},
        ]],
    )

    created = client.post("/api/v1/runs", json={"goal": "Build backend"}).json()
    wait_for_status(client, created["id"], {"awaiting_decision"})

    client.post(
        f"/api/v1/runs/{created['id']}/decision",
        json={"action": "stop", "reason": "halt", "actor": "tester"},
    )
    run = wait_for_status(client, created["id"], {"stopped"})
    assert "stopped_after_task" in run["output"]


def test_guardian_gate_runs_before_decomposition(workspace_tmp):
    client, _ = make_client(
        workspace_tmp,
        critic_sequences=[[
            {"decision": "approve", "score": 92, "issues_found": [], "suggestions": []}
        ]],
    )

    created = client.post("/api/v1/runs", json={"goal": "Build backend"}).json()
    wait_for_status(client, created["id"], {"completed"})
    events = client.get(f"/api/v1/runs/{created['id']}/events").json()["events"]

    guardian_idx = next(i for i, event in enumerate(events) if event["agent"] == "Guardian" and event["action"] == "scan_start")
    scout_idx = next(i for i, event in enumerate(events) if event["agent"] == "Scout" and event["action"] == "decompose_start")
    assert guardian_idx < scout_idx


def test_decision_endpoint_rejects_invalid_action_value(workspace_tmp):
    client, _ = make_client(
        workspace_tmp,
        critic_sequences=[[
            {"decision": "approve", "score": 92, "issues_found": [], "suggestions": []}
        ]],
    )

    created = client.post("/api/v1/runs", json={"goal": "Build backend"}).json()
    response = client.post(
        f"/api/v1/runs/{created['id']}/decision",
        json={"action": "pause", "reason": "invalid"},
    )

    assert response.status_code == 422
