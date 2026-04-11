"""
Integration tests for the orchestrator's core flows:
  - reject → retry → approve loop
    - max-rejections → user-decision escalation path
    - dependency-aware execution context behavior
"""

import pytest
import asyncio
import time
from unittest.mock import patch, MagicMock, AsyncMock
from types import SimpleNamespace

from nexussentry.agents.critic import CriticAgent
from nexussentry.agents.builder import BuilderAgent
from nexussentry.agents.integrator import IntegratorAgent
from nexussentry.agents.qa_verifier import QAVerifierAgent


class TestCriticRetryLoop:
    """Tests for the self-correcting reject→retry→approve loop."""

    def test_critic_rejection_count_persists_across_reviews(self):
        """A single CriticAgent instance should track rejections across calls."""
        critic = CriticAgent(max_rejections=2)

        assert critic.rejection_count == 0

        # Simulate a rejection
        reject_verdict = {
            "decision": "reject",
            "score": 45,
            "reasoning": "Insufficient",
            "issues_found": ["Missing validation"],
            "suggestions": ["Add input checks"],
        }
        result = critic._process_verdict(reject_verdict)
        assert critic.rejection_count == 1
        assert result["decision"] == "reject"

    def test_critic_escalates_after_max_rejections(self):
        """After max_rejections, Critic should escalate to human."""
        critic = CriticAgent(max_rejections=2)

        reject_verdict = {
            "decision": "reject",
            "score": 30,
            "reasoning": "Bad",
            "issues_found": ["Critical bug"],
            "suggestions": [],
        }

        # First rejection — should stay as reject
        r1 = critic._process_verdict(reject_verdict.copy())
        assert r1["decision"] == "reject"
        assert critic.rejection_count == 1

        # Second rejection — should escalate to human
        r2 = critic._process_verdict(reject_verdict.copy())
        assert r2["decision"] == "escalate_to_human"
        assert critic.rejection_count == 2

    def test_new_critic_per_subtask_has_fresh_count(self):
        """Each sub-task should get a fresh CriticAgent with rejection_count=0."""
        critic1 = CriticAgent(max_rejections=2)
        critic1._process_verdict({
            "decision": "reject", "score": 30,
            "reasoning": "Bad", "issues_found": [], "suggestions": [],
        })
        assert critic1.rejection_count == 1

        # New critic for next sub-task should start fresh
        critic2 = CriticAgent(max_rejections=2)
        assert critic2.rejection_count == 0

    def test_approve_does_not_increment_rejection_count(self):
        """Approval should not affect the rejection counter."""
        critic = CriticAgent(max_rejections=2)

        approve_verdict = {
            "decision": "approve",
            "score": 92,
            "reasoning": "Well done",
            "issues_found": [],
            "suggestions": [],
        }
        result = critic._process_verdict(approve_verdict)
        assert result["decision"] == "approve"
        assert critic.rejection_count == 0


class TestCriticCacheKey:
    """Tests that the cache key properly differentiates attempts."""

    def test_different_plans_produce_different_cache_keys(self):
        """Two reviews with different plans should NOT collide in cache."""
        import hashlib

        task = "Fix SQL injection"

        plan_a = '{"plan_summary": "Use parameterized queries"}'
        plan_b = '{"plan_summary": "Use ORM instead of raw SQL"}'

        input_a = f"ORIGINAL TASK: {task}\nPLAN: {plan_a}\nFIXER: ok"
        input_b = f"ORIGINAL TASK: {task}\nPLAN: {plan_b}\nFIXER: ok"

        hash_a = hashlib.md5(input_a.encode()).hexdigest()[:12]
        hash_b = hashlib.md5(input_b.encode()).hexdigest()[:12]

        assert hash_a != hash_b, "Different plans should produce different cache keys"


class TestDependencyExecutionContext:
    """Tests for shared context behavior across task progress."""

    @patch("nexussentry.providers.llm_provider._global_provider", None)
    def test_tasks_execute_in_order(self):
        """Verify sequential execution by checking task result ordering."""
        from nexussentry.utils.swarm_memory import SwarmMemory

        memory = SwarmMemory()

        # Simulate sequential task recording
        memory.record_task_result(1, "Task A", "Done")
        memory.record_task_result(2, "Task B", "Done")
        memory.record_task_result(3, "Task C", "Done")

        history = memory.get_task_history()
        assert len(history) == 3
        assert history[0]["task_id"] == 1
        assert history[1]["task_id"] == 2
        assert history[2]["task_id"] == 3

    def test_memory_context_grows_after_each_task(self):
        """Each subsequent task should see results from all previous tasks."""
        from nexussentry.utils.swarm_memory import SwarmMemory

        memory = SwarmMemory()

        # Before any tasks, context should be empty
        assert memory.summarize_context() == ""

        # After Task 1
        memory.record_task_result(1, "Fix auth", "Done with score 88")
        memory.mark_file_modified("auth.py")
        ctx1 = memory.summarize_context()
        assert "Fix auth" in ctx1
        assert "auth.py" in ctx1

        # After Task 2 — should see both tasks
        memory.record_task_result(2, "Fix XSS", "Done with score 91")
        memory.mark_file_modified("templates.py")
        ctx2 = memory.summarize_context()
        assert "Fix auth" in ctx2
        assert "Fix XSS" in ctx2
        assert "auth.py" in ctx2
        assert "templates.py" in ctx2


class TestExecutionMode:
    """Tests that execution mode propagates correctly."""

    def test_builder_reports_execution_mode(self):
        """BuilderAgent should include execution_mode information."""
        builder = BuilderAgent()
        # Without real Claw binary, mode should be simulated
        assert builder.claw.execution_mode in ("real", "simulated")

    def test_claw_bridge_simulated_mode_no_fake_files(self):
        """Simulated results should NOT contain fake file paths."""
        from nexussentry.adapters.claw_bridge import ClawBridge

        bridge = ClawBridge()
        if not bridge.claw_available:
            result = bridge._simulated_run("test task", 0.5)
            assert result["execution_mode"] == "simulated"
            assert result["files_modified"] == []
            assert result["commands_run"] == []
            assert "[SIMULATED]" in result["output"]


class TestBuilderPipeline:
    """Tests for separated builder/integrator/qa agent flow."""

    def test_partition_files_uses_all_requested_builder_slots(self):
        """Partitioning should create one chunk per active builder."""
        builder = BuilderAgent()

        groups = builder._partition_files(
            ["a.py", "b.py", "c.py", "d.py", "e.py", "f.py"],
            5,
        )

        assert len(groups) == 5
        assert sum(len(group) for group in groups) == 6

    def test_builder_integrator_qa_pipeline(self, monkeypatch):
        """Builder -> Integrator -> QA pipeline returns coherent outputs."""
        builder = BuilderAgent()
        integrator = IntegratorAgent()
        qa = QAVerifierAgent()

        monkeypatch.setattr(
            builder,
            "_generate_code_files",
            lambda plan, provider: {"app.py": "print('ok')"},
        )

        builder_result = builder.build({
            "plan_summary": "Build a small app",
            "approach": "Use a builder pipeline",
            "files_to_read": [],
            "files_to_modify": ["app.py"],
            "commands_to_run": [],
            "success_criteria": "app.py exists",
            "builder_dispatch": {"builder_count": 1},
        })

        integration_result = integrator.integrate(
            {"plan_summary": "Build a small app"},
            builder_result,
        )

        qa_result = qa.verify(
            {"plan_summary": "Build a small app", "files_to_modify": ["app.py"]},
            integration_result["generated_files"],
            builder_result["builder_reports"],
        )

        assert builder_result["generated_files"]["app.py"] == "print('ok')"
        assert integration_result["generated_files"]["app.py"] == "print('ok')"
        assert qa_result["passed"] is True


class TestDependencyWaveScheduler:
    """Tests for dependency-wave execution and strict QA gate behavior."""

    def _install_swarm_stubs(self, monkeypatch, sub_tasks, qa_verdicts):
        """Patch run_swarm dependencies with deterministic in-memory stubs."""
        from nexussentry import main as orchestrator

        state = {
            "architect_calls": 0,
            "critic_calls": 0,
            "qa_calls": 0,
            "build_starts": {},
            "build_ends": {},
            "build_order": [],
        }

        class FakeTracer:
            def __init__(self):
                self.events = []

            def log(self, agent, event, payload):
                self.events.append((agent, event, payload))

            def record_task_status(self, *args, **kwargs):
                return None

            def mark_complete(self):
                return None

            def summary(self):
                return {
                    "total_time_s": 0,
                    "total_events": 0,
                    "agents_used": [],
                    "approvals": 0,
                    "rejections": 0,
                    "log_file": "test.log",
                }

        class FakeGuardian:
            def scan(self, *_args, **_kwargs):
                return {"safe": True}

            def stats(self):
                return {"scans_performed": 1}

        class FakeScout:
            def decompose(self, *_args, **_kwargs):
                return {
                    "goal_summary": "test goal",
                    "estimated_complexity": "medium",
                    "sub_tasks": sub_tasks,
                }

        class FakeArchitect:
            def plan(self, sub_task, **_kwargs):
                state["architect_calls"] += 1
                return {
                    "plan_summary": sub_task,
                    "files_to_modify": [f"{sub_task}.py"],
                    "builder_dispatch": {"builder_count": 1},
                }

        class FakeBuilder:
            def __init__(self):
                self.claw = SimpleNamespace(execution_mode="simulated")

            def build(self, plan, *_args, **_kwargs):
                task_name = plan["plan_summary"]
                state["build_order"].append(task_name)
                state["build_starts"][task_name] = time.perf_counter()
                if task_name in ("A", "B"):
                    time.sleep(0.05)
                state["build_ends"][task_name] = time.perf_counter()
                return {
                    "success": True,
                    "execution_mode": "simulated",
                    "builder_reports": [{"builder_id": "builder-1", "status": "ok"}],
                    "generated_files": {f"{task_name}.py": f"print('{task_name}')"},
                    "saved_to": "",
                }

        class FakeIntegrator:
            def integrate(self, _plan, builder_result, *_args, **_kwargs):
                return {
                    "integrator_summary": "integrated",
                    "generated_files": builder_result.get("generated_files", {}),
                    "execution_mode": builder_result.get("execution_mode", "simulated"),
                    "saved_to": "",
                }

        class FakeQA:
            def verify(self, *_args, **_kwargs):
                state["qa_calls"] += 1
                verdict_index = min(state["qa_calls"] - 1, len(qa_verdicts) - 1)
                verdict = qa_verdicts[verdict_index]
                return {
                    "passed": verdict["passed"],
                    "score": verdict.get("score", 100 if verdict["passed"] else 0),
                    "issues_found": verdict.get("issues_found", []),
                    "suggestions": verdict.get("suggestions", []),
                }

        class FakeCritic:
            def __init__(self, max_rejections=2):
                self.max_rejections = max_rejections

            def review(self, *_args, **_kwargs):
                state["critic_calls"] += 1
                return {
                    "decision": "approve",
                    "score": 96,
                    "issues_found": [],
                    "suggestions": [],
                }

        class FakePermissionGate:
            async def request_retry_permission(self, *_args, **_kwargs):
                return False

        class FakeMemory:
            def summarize_context(self):
                return ""

            def record_fact(self, *_args, **_kwargs):
                return None

            def get_actionable_constraints(self, **_kwargs):
                return ""

            def record_builder_dispatch(self, *_args, **_kwargs):
                return None

            def has_file_conflict(self, *_args, **_kwargs):
                return []

            def record_critic_feedback(self, *_args, **_kwargs):
                return None

            def record_task_result(self, *_args, **_kwargs):
                return None

            def mark_file_modified(self, *_args, **_kwargs):
                return None

        class FakeCache:
            def stats(self):
                return {"hit_rate": "0%"}

        class FakeProvider:
            available_providers = ["mock"]
            mock_mode = True

            def provider_summary_str(self):
                return "mock"

            def agent_routing_str(self):
                return "all -> mock"

            def stats(self):
                return {"total_calls": 0, "provider_usage": {"mock": 0}}

        monkeypatch.setattr(orchestrator, "AgentTracer", FakeTracer)
        monkeypatch.setattr(orchestrator, "GuardianAI", FakeGuardian)
        monkeypatch.setattr(orchestrator, "ScoutAgent", FakeScout)
        monkeypatch.setattr(orchestrator, "ArchitectAgent", FakeArchitect)
        monkeypatch.setattr(orchestrator, "BuilderAgent", FakeBuilder)
        monkeypatch.setattr(orchestrator, "IntegratorAgent", FakeIntegrator)
        monkeypatch.setattr(orchestrator, "QAVerifierAgent", FakeQA)
        monkeypatch.setattr(orchestrator, "CriticAgent", FakeCritic)
        monkeypatch.setattr(orchestrator, "UserPermissionGate", FakePermissionGate)
        monkeypatch.setattr(orchestrator, "SwarmMemory", FakeMemory)
        monkeypatch.setattr(orchestrator, "get_cache", lambda: FakeCache())
        monkeypatch.setattr(orchestrator, "get_provider", lambda: FakeProvider())
        monkeypatch.setattr(orchestrator, "print_banner", lambda: None)

        return orchestrator, state

    def test_dependency_waves_run_parallel_then_unlock_dependents(self, monkeypatch):
        """Independent tasks should run together; dependent tasks should run after."""
        sub_tasks = [
            {"id": 1, "task": "A", "priority": "high", "depends_on": []},
            {"id": 2, "task": "B", "priority": "high", "depends_on": []},
            {"id": 3, "task": "C", "priority": "high", "depends_on": [1, 2]},
        ]
        orchestrator, state = self._install_swarm_stubs(
            monkeypatch,
            sub_tasks=sub_tasks,
            qa_verdicts=[{"passed": True}],
        )

        results = asyncio.run(orchestrator.run_swarm("test", enable_dashboard=False, slow=False))
        status_by_id = {item["task_id"]: item["status"] for item in results}

        assert status_by_id[1] == "done"
        assert status_by_id[2] == "done"
        assert status_by_id[3] == "done"
        assert set(state["build_order"][:2]) == {"A", "B"}
        assert state["build_order"][2] == "C"
        assert state["build_starts"]["C"] >= state["build_ends"]["A"]
        assert state["build_starts"]["C"] >= state["build_ends"]["B"]

    def test_qa_failure_retries_before_critic(self, monkeypatch):
        """Critic should run only after QA passes, with retries driven by QA failures."""
        sub_tasks = [{"id": 1, "task": "A", "priority": "high", "depends_on": []}]
        orchestrator, state = self._install_swarm_stubs(
            monkeypatch,
            sub_tasks=sub_tasks,
            qa_verdicts=[
                {
                    "passed": False,
                    "score": 42,
                    "issues_found": ["missing tests"],
                    "suggestions": ["add tests"],
                },
                {"passed": True, "score": 95},
            ],
        )

        results = asyncio.run(orchestrator.run_swarm("test", enable_dashboard=False, slow=False))

        assert results[0]["status"] == "done"
        assert results[0]["attempts"] == 2
        assert state["architect_calls"] == 2
        assert state["critic_calls"] == 1

    def test_failed_dependency_causes_downstream_skip(self, monkeypatch):
        """When a dependency fails, dependent tasks should be skipped as blocked."""
        sub_tasks = [
            {"id": 1, "task": "A", "priority": "high", "depends_on": []},
            {"id": 2, "task": "B", "priority": "high", "depends_on": [1]},
        ]
        orchestrator, _state = self._install_swarm_stubs(
            monkeypatch,
            sub_tasks=sub_tasks,
            qa_verdicts=[
                {
                    "passed": False,
                    "score": 30,
                    "issues_found": ["critical QA failure"],
                    "suggestions": ["fix issue"],
                }
            ],
        )

        results = asyncio.run(orchestrator.run_swarm("test", enable_dashboard=False, slow=False))
        status_by_id = {item["task_id"]: item["status"] for item in results}

        assert status_by_id[1] == "failed"
        assert status_by_id[2] == "skipped"
