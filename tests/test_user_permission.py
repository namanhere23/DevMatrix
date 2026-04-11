import asyncio

from nexussentry.hitl.user_permission import UserPermissionGate


def test_permission_gate_yes(monkeypatch):
    gate = UserPermissionGate()
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda _: "y")

    approved = asyncio.run(gate.request_retry_permission("Retry task", {"score": "62"}))
    assert approved is True


def test_permission_gate_no(monkeypatch):
    gate = UserPermissionGate()
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda _: "n")

    approved = asyncio.run(gate.request_retry_permission("Retry task", {"score": "62"}))
    assert approved is False


def test_permission_gate_non_interactive_defaults_no(monkeypatch):
    gate = UserPermissionGate()
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)

    approved = asyncio.run(gate.request_retry_permission("Retry task", {"score": "62"}))
    assert approved is False


def test_permission_gate_yes_then_no_sequence(monkeypatch):
    gate = UserPermissionGate()
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)

    answers = iter(["y", "n"])
    monkeypatch.setattr("builtins.input", lambda _: next(answers))

    first = asyncio.run(gate.request_retry_permission("Retry task", {"score": "62"}))
    second = asyncio.run(gate.request_retry_permission("Retry task", {"score": "62"}))

    assert first is True
    assert second is False
