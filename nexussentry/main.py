# nexussentry/main.py
"""
╔═══════════════════════════════════════════════════════════╗
║           NexusSentry — Main Swarm Orchestrator           ║
║                                                           ║
║  Python for the Brain. Rust for the Blade.                ║
║                                                           ║
║  Coordinates 4 specialized AI agents + security layer     ║
║  + human-in-the-loop approval + real-time dashboard.      ║
║                                                           ║
║  Multi-Provider AI: Gemini │ Grok │ OpenRouter │ Anthropic║
╚═══════════════════════════════════════════════════════════╝
"""

import asyncio
import os
import sys
import logging
from dotenv import load_dotenv

# Fix Windows console encoding — must be before any emoji output
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(message)s",
    datefmt="%H:%M:%S"
)

from nexussentry.agents.scout import ScoutAgent
from nexussentry.agents.architect import ArchitectAgent
from nexussentry.agents.fixer import FixerAgent
from nexussentry.agents.critic import CriticAgent
from nexussentry.hitl.telegram import TelegramHITL
from nexussentry.observability.tracer import AgentTracer
from nexussentry.observability.dashboard import start_dashboard
from nexussentry.security.guardian import GuardianAI
from nexussentry.utils.response_cache import get_cache
from nexussentry.providers.llm_provider import get_provider
from nexussentry.utils.swarm_memory import SwarmMemory


def print_banner():
    """Print the NexusSentry startup banner."""
    banner = """
\033[95m╔═══════════════════════════════════════════════════════════╗
║                                                           ║
║   ███╗   ██╗███████╗██╗  ██╗██╗   ██╗███████╗            ║
║   ████╗  ██║██╔════╝╚██╗██╔╝██║   ██║██╔════╝            ║
║   ██╔██╗ ██║█████╗   ╚███╔╝ ██║   ██║███████╗            ║
║   ██║╚██╗██║██╔══╝   ██╔██╗ ██║   ██║╚════██║            ║
║   ██║ ╚████║███████╗██╔╝ ██╗╚██████╔╝███████║            ║
║   ╚═╝  ╚═══╝╚══════╝╚═╝  ╚═╝ ╚═════╝ ╚══════╝            ║
║              \033[96mSENTRY\033[95m                                        ║
║                                                           ║
║   \033[93mPython for the Brain. Rust for the Blade.\033[95m               ║
║                                                           ║
╚═══════════════════════════════════════════════════════════╝\033[0m
    """
    print(banner)


async def run_swarm(user_goal: str, enable_dashboard: bool = True, slow: bool = False):
    """
    Main orchestration loop.

    Flow:
        User Goal → Guardian (security) → Scout (decompose) →
        for each sub-task:
            Architect (plan) → Fixer (execute) → Critic (review)
            if rejected: loop back to Architect with feedback
            if max rejections: escalate to Human (HITL)
    """
    print_banner()
    print(f"  📋 Goal: {user_goal}")
    print(f"  {'═' * 56}\n")

    # ── Initialize all components ──
    tracer = AgentTracer()
    guardian = GuardianAI()
    scout = ScoutAgent()
    architect = ArchitectAgent()
    fixer = FixerAgent()
    critic = CriticAgent(max_rejections=2)
    hitl = TelegramHITL()
    cache = get_cache()
    provider = get_provider()
    memory = SwarmMemory()

    # ── Show provider info ──
    print(f"  🤖 AI Providers: {provider.provider_summary_str()}")
    print(f"\n  Agent → Provider Routing:")
    print(provider.agent_routing_str())
    print()

    # ── Start dashboard server ──
    if enable_dashboard:
        try:
            start_dashboard(tracer, port=7777)
        except OSError:
            print("  ⚠️  Dashboard port 7777 in use, trying 7778...")
            try:
                start_dashboard(tracer, port=7778)
            except OSError:
                print("  ⚠️  Dashboard unavailable (ports busy)")

    tracer.log("System", "swarm_start", {
        "goal": user_goal,
        "providers": provider.available_providers,
        "mock_mode": provider.mock_mode,
    })

    # ══════════════════════════════════════════════
    # STEP 0: Security Scan (Guardian — 7 layers)
    # ══════════════════════════════════════════════
    print(f"\n  🛡️  Running 7-layer security scan...")
    scan_result = guardian.scan(user_goal, tracer)
    if not scan_result.get("safe", True):
        print(f"\n  🚨 BLOCKED by Guardian (Layer {scan_result.get('layer', '?')})")
        print(f"     Reason: {scan_result.get('reason', 'Unknown')}")
        print(f"\n  {'═' * 56}")
        print(f"  🛡️  0 data leaked. Threat neutralized.\n")
        tracer.mark_complete()
        return []

    print(f"  ✅ Security scan passed (all 7 layers clear)\n")

    # ══════════════════════════════════════════════
    # STEP 1: Scout decomposes the goal
    # ══════════════════════════════════════════════
    if slow: await asyncio.sleep(2)
    context = memory.summarize_context()
    scout_input = user_goal if not context else f"{user_goal}\n\nContext:\n{context}"
    decomposition = scout.decompose(scout_input, tracer)
    sub_tasks = decomposition.get("sub_tasks", [])

    if not sub_tasks:
        print("  ⚠️  Scout returned no sub-tasks. Aborting.")
        tracer.mark_complete()
        return []

    results = []

    # ══════════════════════════════════════════════
    # STEPS 2-4: Architect → Fixer → Critic loop (PARALLEL)
    # ══════════════════════════════════════════════
    async def process_sub_task(task_obj):
        task_id = task_obj.get("id", "?")
        task_desc = task_obj.get("task", "Unknown task")
        priority = task_obj.get("priority", "medium").upper()

        print(f"\n  {'─' * 56}")
        print(f"  📌 Sub-task {task_id}/{len(sub_tasks)} [{priority}]: {task_desc}")

        tracer.set_current_task(task_desc)
        feedback = ""

        for attempt in range(3):
            print(f"\n    ▸ Attempt {attempt + 1}/3 for Sub-task {task_id}")

            # ── Step 2: Architect plans ──
            if slow: await asyncio.sleep(1.5)
            plan_context = memory.summarize_context()
            plan = await asyncio.to_thread(
                architect.plan,
                sub_task=task_desc,
                feedback=feedback,
                context=plan_context,
                tracer=tracer
            )

            # ── Step 3: Fixer executes ──
            if slow: await asyncio.sleep(2)
            result = await asyncio.to_thread(
                fixer.execute,
                plan,
                tracer
            )

            # ── Step 4: Critic reviews ──
            if slow: await asyncio.sleep(1.5)
            critic_agent = CriticAgent(max_rejections=2)  # Fresh per sub-task
            verdict = await asyncio.to_thread(
                critic_agent.review,
                original_task=task_desc,
                plan=plan,
                fixer_result=result,
                tracer=tracer
            )

            if verdict["decision"] == "approve":
                score = verdict.get("score", "?")
                print(f"\n    ✅ Sub-task {task_id} complete! (score: {score}/100)")
                
                # Record to SwarmMemory
                memory.record_task_result(task_id, task_desc, f"Completed with score {score}")
                for f in plan.get("files_to_modify", []):
                    memory.mark_file_modified(f)
                    
                return {
                    "task": task_desc,
                    "status": "done",
                    "score": score,
                    "attempts": attempt + 1
                }

            elif verdict["decision"] == "escalate_to_human":
                tracer.log("HITL", "approval_requested", {"task": task_desc})

                approved = await hitl.request_approval(
                    message=f"Task: {task_desc}",
                    details={
                        "issues": ", ".join(verdict.get("issues_found", [])),
                        "score": str(verdict.get("score", "?")),
                    }
                )

                if approved:
                    tracer.log("HITL", "human_approved", {})
                    print(f"    ✅ Human approved sub-task {task_id}. Moving on.")
                    return {
                        "task": task_desc,
                        "status": "human_approved",
                        "attempts": attempt + 1
                    }
                else:
                    tracer.log("HITL", "human_rejected", {})
                    print(f"    ❌ Human rejected sub-task {task_id}. Skipping.")
                    return {
                        "task": task_desc,
                        "status": "skipped",
                        "attempts": attempt + 1
                    }

            else:
                # Critic rejected → loop back with feedback
                issues = verdict.get("issues_found", [])
                score = verdict.get("score", "?")
                feedback = (
                    f"Previous attempt scored {score}/100. "
                    f"Issues: {', '.join(issues)}. "
                    f"Suggestions: {', '.join(verdict.get('suggestions', []))}"
                )
                memory.record_critic_feedback(f"Task '{task_desc}': " + feedback)
                print(f"    🔄 Retrying sub-task {task_id} with Critic feedback...")
        
        # Max attempts reached
        return {
            "task": task_desc,
            "status": "failed",
            "score": 0,
            "attempts": 3
        }

    # Execute all sub-tasks concurrently
    parallel_tasks = [process_sub_task(task) for task in sub_tasks]
    results = await asyncio.gather(*parallel_tasks, return_exceptions=True)


    # ══════════════════════════════════════════════
    # FINAL SUMMARY
    # ══════════════════════════════════════════════
    tracer.mark_complete()
    summary = tracer.summary()
    cache_stats = cache.stats()
    security_stats = guardian.stats()
    provider_stats = provider.stats()

    print(f"\n  {'═' * 56}")
    print(f"  🏁 NexusSentry Swarm Complete!")
    print(f"  {'─' * 56}")
    print(f"   ⏱️  Total time:     {summary['total_time_s']}s")
    print(f"   📊 Total events:   {summary['total_events']}")
    print(f"   🤖 Agents used:    {', '.join(summary['agents_used'])}")
    print(f"   ✅ Approvals:      {summary['approvals']}")
    print(f"   ❌ Rejections:     {summary['rejections']}")
    print(f"   🛡️  Security scans: {security_stats['scans_performed']}")
    print(f"   💾 Cache hit rate: {cache_stats['hit_rate']}")
    print(f"   🤖 LLM calls:     {provider_stats['total_calls']}")
    print(f"   🔀 Providers used: {provider_stats['provider_usage']}")
    print(f"   📁 Trace log:      {summary['log_file']}")
    print(f"  {'═' * 56}")
    print(f"\n  \033[95m✨ Python for the Brain. Rust for the Blade. ✨\033[0m\n")

    return results


if __name__ == "__main__":
    goal = (
        "Analyze this Python project for security vulnerabilities "
        "and fix the top 3 critical issues"
    )

    # Allow goal to be passed as CLI argument
    if len(sys.argv) > 1:
        goal = " ".join(sys.argv[1:])

    asyncio.run(run_swarm(goal))
