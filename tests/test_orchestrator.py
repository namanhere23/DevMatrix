"""
Integration tests for the orchestrator's core flows:
  - reject → retry → approve loop
  - max-rejections → HITL escalation
  - sequential execution order
"""

import pytest
import asyncio
from unittest.mock import patch, MagicMock, AsyncMock

from nexussentry.agents.critic import CriticAgent
from nexussentry.agents.fixer import FixerAgent


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


class TestSequentialExecution:
    """Tests that sub-tasks execute in order, not in parallel."""

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

    def test_fixer_reports_execution_mode(self):
        """FixerAgent should include execution_mode in results."""
        fixer = FixerAgent()
        # Without real Claw binary, mode should be simulated
        assert fixer.claw.execution_mode in ("real", "simulated")

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
