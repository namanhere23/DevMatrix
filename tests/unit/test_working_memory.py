# tests/unit/test_working_memory.py
"""Unit tests for the enhanced TaskWorkingMemory (Phase 1.1)."""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from nexussentry.memory.working_memory import TaskWorkingMemory, CriticVerdict, AgentOutput


def test_working_memory_basic():
    mem = TaskWorkingMemory(task_id="t1", session_id="s1")
    mem.add_plan({"plan_summary": "test plan"})
    mem.add_verdict({"score": 55, "decision": "reject", "issues": ["Missing error handling"]}, attempt=1)

    assert mem.attempt_count == 1
    assert mem.last_score == 55
    assert "55" in mem.get_feedback_for_architect()
    assert "Missing error handling" in mem.get_feedback_for_architect()
    print("✓ Working memory basic test passed")


def test_working_memory_multiple_attempts():
    mem = TaskWorkingMemory(task_id="t2", session_id="s2")

    # Attempt 1: rejected
    mem.add_plan({"plan_summary": "first attempt"})
    mem.add_verdict({
        "score": 45, "decision": "reject",
        "issues": ["No input validation", "Missing tests"]
    }, attempt=1)

    assert mem.attempt_count == 1
    assert mem.last_score == 45
    feedback = mem.get_feedback_for_architect()
    assert "No input validation" in feedback
    assert "Missing tests" in feedback

    # Attempt 2: approved
    mem.add_plan({"plan_summary": "second attempt with fixes"})
    mem.add_verdict({
        "score": 88, "decision": "approve", "issues": []
    }, attempt=2)

    assert mem.attempt_count == 2
    assert mem.last_score == 88
    print("✓ Working memory multiple attempts test passed")


def test_working_memory_complete():
    mem = TaskWorkingMemory(task_id="t3", session_id="s3", original_goal="Build API")
    mem.add_plan({"plan_summary": "REST API plan"})
    mem.mark_complete({"api_ready": True}, "approved")

    assert mem.status == "approved"
    assert mem.final_result == {"api_ready": True}
    assert mem.completed_at is not None
    print("✓ Working memory complete test passed")


def test_critic_verdict_model():
    verdict = CriticVerdict(
        attempt=1, score=72, decision="approve",
        issues=[], reasoning="Looks good",
        panel_breakdown={"correctness": 80, "security": 70, "architecture": 65}
    )
    assert verdict.score == 72
    assert verdict.panel_breakdown["correctness"] == 80
    print("✓ CriticVerdict model test passed")


def test_agent_output_model():
    output = AgentOutput(
        agent_name="builder",
        output={"files": ["index.html"]},
        latency_ms=350.5,
        provider_used="gemini",
        token_estimate=500,
        cost_estimate_usd=0.0002
    )
    assert output.agent_name == "builder"
    assert output.latency_ms == 350.5
    print("✓ AgentOutput model test passed")


if __name__ == "__main__":
    test_working_memory_basic()
    test_working_memory_multiple_attempts()
    test_working_memory_complete()
    test_critic_verdict_model()
    test_agent_output_model()
    print("\n✅ All working memory unit tests passed!")
