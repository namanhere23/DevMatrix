import json
from pathlib import Path
from nexussentry.contracts import GoalContract, RunContext
from nexussentry.agents import IntegratorAgent

def _capture_written_files(monkeypatch):
    written = {}

    def fake_write_text(self, text, encoding="utf-8", *args, **kwargs):
        written[str(self)] = text
        return len(text)

    monkeypatch.setattr(Path, "write_text", fake_write_text)
    return written


def test_manifest_matches_final_summary(monkeypatch):
    written = _capture_written_files(monkeypatch)
    run_dir = Path.cwd() / "manifest_test_run"
    contract = GoalContract(single_file=True, allowed_output_files=["index.html"])
    run_context = RunContext(
        run_id="test_run",
        run_output_dir=run_dir,
        goal_contract=contract,
    )

    integrator = IntegratorAgent(run_context=run_context)
    integrator.write_manifest(
        goal="Test goal",
        tasks=[{"task_id": 1, "task": "A", "status": "done", "score": 100, "attempts": 1, "execution_mode": "mock"}],
        summary={"total_time_s": 1.5, "total_events": 10, "approvals": 1, "rejections": 0},
        provider_stats={"total_calls": 5, "provider_usage": {"mock": 5}},
    )

    manifest_path = str(run_dir / "manifest.json")
    assert manifest_path in written
    data = json.loads(written[manifest_path])

    assert data["run_id"] == "test_run"
    assert data["goal"] == "Test goal"
    assert len(data["tasks"]) == 1
    assert data["tasks"][0]["task_id"] == 1
    assert data["summary"]["total_time_s"] == 1.5
    assert data["summary"]["provider_usage"]["mock"] == 5


def test_manifest_contains_provider_failures(monkeypatch):
    written = _capture_written_files(monkeypatch)
    run_dir = Path.cwd() / "manifest_test_run"
    contract = GoalContract()
    run_context = RunContext(
        run_id="test_run",
        run_output_dir=run_dir,
        goal_contract=contract,
    )
    run_context.record_provider_failure("gemini", "Quota exceeded")

    integrator = IntegratorAgent(run_context=run_context)
    integrator.write_manifest(
        goal="Test goal",
        tasks=[],
        summary={},
        provider_stats={},
    )

    manifest_path = str(run_dir / "manifest.json")
    assert manifest_path in written
    data = json.loads(written[manifest_path])

    assert len(data["provider_failures"]) == 1
    assert data["provider_failures"][0]["provider"] == "gemini"
    assert data["provider_failures"][0]["error"] == "Quota exceeded"


def test_promote_to_final_preserves_relative_directories(monkeypatch):
    written = _capture_written_files(monkeypatch)
    monkeypatch.setattr(Path, "mkdir", lambda self, parents=False, exist_ok=False: None)

    run_dir = Path.cwd() / "manifest_test_run"
    run_context = RunContext(
        run_id="test_run",
        run_output_dir=run_dir,
        goal_contract=GoalContract(),
    )
    integrator = IntegratorAgent(run_context=run_context)

    integrator.promote_to_final({
        "src/app.py": "print('app')",
        "tests/app.py": "print('test')",
    })

    assert str(run_dir / "final" / "src" / "app.py") in written
    assert str(run_dir / "final" / "tests" / "app.py") in written
