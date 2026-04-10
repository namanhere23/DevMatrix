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
║  Multi-Provider AI: Gemini │ Groq │ OpenRouter │ Anthropic║
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
        for each sub-task (SEQUENTIAL — conflict-aware):
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
    hitl = TelegramHITL()
    cache = get_cache()
    provider = get_provider()
    memory = SwarmMemory()

    # ── Determine execution mode from Claw bridge ──
    exec_mode = fixer.claw.execution_mode
    exec_badge = f"[{exec_mode.upper()}]"
    print(f"  ⚡ Execution Mode: {exec_badge}")

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
        "execution_mode": exec_mode,
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

    # Record Scout discoveries as facts
    memory.record_fact("goal_summary", decomposition.get("goal_summary", user_goal))
    memory.record_fact("complexity", decomposition.get("estimated_complexity", "unknown"))

    results = []

    # ══════════════════════════════════════════════
    # STEPS 2-4: Architect → Fixer → Critic loop
    # SEQUENTIAL execution — each task feeds context
    # to the next via SwarmMemory
    # ══════════════════════════════════════════════
    for task_obj in sub_tasks:
        task_id = task_obj.get("id", "?")
        task_desc = task_obj.get("task", "Unknown task")
        priority = task_obj.get("priority", "medium").upper()

        print(f"\n  {'─' * 56}")
        print(f"  📌 Sub-task {task_id}/{len(sub_tasks)} [{priority}]: {task_desc}")

        tracer.set_current_task(task_desc)
        feedback = ""

        # Single CriticAgent per sub-task — tracks rejection_count across retry attempts
        critic = CriticAgent(max_rejections=2)

        for attempt in range(3):
            print(f"\n    ▸ Attempt {attempt + 1}/3 for Sub-task {task_id}")

            # ── Step 2: Architect plans ──
            if slow: await asyncio.sleep(1.5)

            # Feed memory constraints into the Architect
            plan_context = memory.summarize_context()
            constraints = memory.get_actionable_constraints(
                proposed_files=task_obj.get("files_to_modify", [])
            )
            if constraints:
                plan_context += f"\n\n{constraints}"

            plan = await asyncio.to_thread(
                architect.plan,
                sub_task=task_desc,
                feedback=feedback,
                context=plan_context,
                tracer=tracer
            )

            # ── Check for file conflicts before execution ──
            proposed_files = plan.get("files_to_modify", [])
            conflicts = memory.has_file_conflict(proposed_files)
            if conflicts:
                print(f"    ⚠️  File conflict detected: {', '.join(conflicts)}")
                print(f"    ⚠️  These files were modified by a previous task. Proceeding with caution.")

            # ── Step 3: Fixer executes ──
            if slow: await asyncio.sleep(2)
            result = await asyncio.to_thread(
                fixer.execute,
                plan,
                tracer
            )

            # ── Step 4: Critic reviews ──
            if slow: await asyncio.sleep(1.5)
            verdict = await asyncio.to_thread(
                critic.review,
                original_task=task_desc,
                plan=plan,
                fixer_result=result,
                tracer=tracer
            )

            if verdict["decision"] == "approve":
                score = verdict.get("score", "?")
                exec_mode_tag = result.get("execution_mode", "unknown").upper()
                print(f"\n    ✅ Sub-task {task_id} complete! (score: {score}/100) [{exec_mode_tag}]")
                
                # Record to SwarmMemory
                memory.record_task_result(task_id, task_desc, f"Completed with score {score}")
                for f in plan.get("files_to_modify", []):
                    memory.mark_file_modified(f)
                    
                results.append({
                    "task": task_desc,
                    "status": "done",
                    "score": score,
                    "attempts": attempt + 1,
                    "execution_mode": result.get("execution_mode", "unknown"),
                    "saved_to": result.get("saved_to", ""),
                })
                break

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
                    results.append({
                        "task": task_desc,
                        "status": "human_approved",
                        "attempts": attempt + 1,
                        "execution_mode": result.get("execution_mode", "unknown"),
                    })
                else:
                    tracer.log("HITL", "human_rejected", {})
                    print(f"    ❌ Human rejected sub-task {task_id}. Skipping.")
                    results.append({
                        "task": task_desc,
                        "status": "skipped",
                        "attempts": attempt + 1,
                        "execution_mode": result.get("execution_mode", "unknown"),
                    })
                break

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
        else:
            # Max attempts reached (for-else: only when loop completes without break)
            results.append({
                "task": task_desc,
                "status": "failed",
                "score": 0,
                "attempts": 3,
                "execution_mode": result.get("execution_mode", "unknown"),
            })

    # ══════════════════════════════════════════════
    # FINAL SUMMARY
    # ══════════════════════════════════════════════
    tracer.mark_complete()
    summary = tracer.summary()
    cache_stats = cache.stats()
    security_stats = guardian.stats()
    provider_stats = provider.stats()

    # Determine overall execution mode badge
    exec_modes_used = list({r.get("execution_mode", "unknown") for r in results if isinstance(r, dict)})
    overall_mode = exec_modes_used[0].upper() if len(exec_modes_used) == 1 else "MIXED"

    print(f"\n  {'═' * 56}")
    print(f"  🏁 NexusSentry Swarm Complete! [{overall_mode}]")
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
    print(f"   ⚡ Execution mode: {overall_mode}")
    print(f"   📁 Trace log:      {summary['log_file']}")

    # Show output directory if files were saved
    output_dirs = set()
    for r in results:
        if isinstance(r, dict) and r.get("saved_to"):
            output_dirs.add(r["saved_to"])
    if output_dirs:
        print(f"   📂 Output saved:   {', '.join(output_dirs)}")
    else:
        output_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "output")
        if os.path.exists(output_path):
            print(f"   📂 Output dir:     {output_path}")

    # Per-task status breakdown
    print(f"  {'─' * 56}")
    print(f"  📋 Per-Task Results:")
    for r in results:
        if isinstance(r, dict):
            status_icon = {"done": "✅", "human_approved": "👤", "skipped": "⏭️", "failed": "❌"}.get(r.get("status"), "❓")
            mode_tag = f"[{r.get('execution_mode', '?').upper()}]"
            score_tag = f" (score: {r['score']}/100)" if "score" in r else ""
            print(f"    {status_icon} {r['task'][:50]}... {mode_tag}{score_tag} ({r.get('attempts', '?')} attempts)")
            if r.get("saved_to"):
                print(f"       💾 Files → {r['saved_to']}")

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
