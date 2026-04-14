# tests/integration/test_v3_pipeline.py
"""
Full pipeline integration test — Phase 7.
Run this after completing all 6 phases.
This IS your Phase 7 — running it proves the system works.
"""
import asyncio
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))


def test_memory_chain():
    """Phase 1: Memory flows through the system."""
    from nexussentry.memory.working_memory import TaskWorkingMemory

    mem = TaskWorkingMemory(task_id="t1", session_id="s1")
    mem.add_plan({"plan_summary": "Test plan"})
    mem.add_verdict({"score": 55, "decision": "reject", "issues": ["Missing tests"]}, attempt=1)
    assert mem.attempt_count == 1
    assert mem.last_score == 55
    print("✓ Phase 1 Memory: OK")


def test_episodic_memory():
    """Phase 1.2: EpisodicMemory initializes (may degrade gracefully)."""
    from nexussentry.memory.episodic_memory import EpisodicMemory
    mem = EpisodicMemory()
    stats = mem.stats()
    # Should work regardless of whether chromadb is installed
    assert "available" in stats
    if stats["available"]:
        print(f"✓ Phase 1.2 EpisodicMemory: ACTIVE ({stats['episode_count']} episodes)")
    else:
        print("✓ Phase 1.2 EpisodicMemory: DEGRADED (no chromadb — OK for testing)")


def test_critic_reviewer():
    """Phase 2: Critic reviewer produces structured verdicts."""
    from nexussentry.agents import CriticAgent

    critic = CriticAgent(max_rejections=2)
    result = critic.review(
        original_task="Write a function that validates email addresses",
        plan={"plan_summary": "Use regex pattern matching", "approach": "import re; match pattern"},
        execution_result={"summary": "Function validates emails using RFC 5322 pattern"},
    )
    assert "decision" in result
    assert "score" in result
    assert result["decision"] in ("approve", "reject", "escalate_to_human", "conditional approve")
    print(f"✓ Phase 2 Critic: {result['decision']} ({result.get('score', '?')}/100)")


def test_dynamic_router():
    """Phase 3: Router makes intelligent selections."""
    from nexussentry.providers.dynamic_router import DynamicRouter

    router = DynamicRouter()
    router.record_outcome("gemini", 300, quality_score=85)
    router.record_outcome("groq", 150, quality_score=72)

    providers = ["gemini", "groq"]
    selected = router.select_provider("architect", providers)
    assert selected in providers
    print(f"✓ Phase 3 DynamicRouter: selected '{selected}'")


def test_agent_factory():
    """Phase 4: Factory spawns correct pipeline."""
    from nexussentry.factory.agent_factory import AgentFactory

    factory = AgentFactory()

    simple = factory.assemble_pipeline([{"task": "Add a comment to the main function"}])
    assert "architect" in simple
    assert "critic" in simple

    complex_ = factory.assemble_pipeline([
        {"task": "Implement OAuth2 JWT authentication with security tests"}
    ])
    assert "security_auditor" in complex_ or "qa_verifier" in complex_
    print(f"✓ Phase 4 AgentFactory: simple={simple}, complex={complex_}")


def test_constitutional_guard():
    """Phase 5: Constitutional guard blocks dangerous outputs."""
    from nexussentry.security.constitutional_guard import ConstitutionalGuard

    guard = ConstitutionalGuard()

    bad = guard.check_output("architect", {"commands_to_run": ["rm -rf /usr/lib"]})
    assert not bad.safe
    assert bad.violation_type == "HARD_STOP"

    good = guard.check_output("architect", {"approach": "Add type hints to user_service.py functions"})
    assert good.safe

    print(f"✓ Phase 5 ConstitutionalGuard: blocks dangerous={not bad.safe}, allows safe={good.safe}")


def test_cost_tracker():
    """Phase 6: Cost tracking works."""
    from nexussentry.observability.cost_tracker import CostTracker
    tracker = CostTracker()
    tracker.record("gemini", "scout", 400, 200)
    tracker.record("groq", "critic_correctness", 1200, 300)
    s = tracker.summary()
    assert s["total_cost_usd"] > 0
    assert s["total_tokens"] == 2100
    assert s["total_calls"] == 2
    print(f"✓ Phase 6 CostTracker: ${s['total_cost_usd']:.6f} for {s['total_tokens']} tokens")


def test_ws_dashboard_importable():
    """Phase 6: WebSocket dashboard module is importable."""
    from nexussentry.observability.ws_dashboard import RealtimeDashboard, WEBSOCKETS_AVAILABLE
    print(f"✓ Phase 6 WSDashboard: importable (websockets available={WEBSOCKETS_AVAILABLE})")


def test_routing_module():
    """Phase 3: Routing module re-export works."""
    from nexussentry.routing import DynamicRouter
    router = DynamicRouter()
    assert hasattr(router, "select_provider")
    print("✓ Phase 3 Routing re-export: OK")


def test_constitutional_module():
    """Phase 5: Constitutional sub-package re-export works."""
    from nexussentry.security.constitutional import ConstitutionalGuard
    guard = ConstitutionalGuard()
    assert hasattr(guard, "check_output")
    print("✓ Phase 5 Constitutional re-export: OK")


if __name__ == "__main__":
    print("=" * 60)
    print("NexusSentry v3.0 — Integration Test Suite")
    print("=" * 60)
    tests = [
        test_memory_chain,
        test_episodic_memory,
        test_critic_reviewer,
        test_dynamic_router,
        test_agent_factory,
        test_constitutional_guard,
        test_cost_tracker,
        test_ws_dashboard_importable,
        test_routing_module,
        test_constitutional_module,
    ]
    passed = failed = 0
    for test in tests:
        try:
            test()
            passed += 1
        except Exception as e:
            import traceback
            print(f"✗ {test.__name__} FAILED: {e}")
            traceback.print_exc()
            failed += 1

    print("=" * 60)
    print(f"Results: {passed} passed, {failed} failed out of {len(tests)}")
    if failed == 0:
        print("🔥 ALL PHASES INTEGRATED — NexusSentry v3.0 IS READY")
    else:
        print("Fix the failing phases before proceeding to deployment.")
    print("=" * 60)
