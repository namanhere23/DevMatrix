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
║  Multi-Provider AI: Gemini │ Groq │ OpenRouter │ HuggingFace║
╚═══════════════════════════════════════════════════════════╝
"""

import asyncio
import os
import sys
import logging
from typing import Any
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
from nexussentry.agents.builder import BuilderAgent
from nexussentry.agents.integrator import IntegratorAgent
from nexussentry.agents.qa_verifier import QAVerifierAgent
from nexussentry.agents.critic import CriticAgent
from nexussentry.hitl.user_permission import UserPermissionGate
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
        User Goal → Guardian (security) → Scout (decompose with dependencies) →
        execute ready sub-tasks in parallel waves (dependency-aware):
            Architect (plan) → Builder(s) → Integrator → QA Verifier (strict gate)
            if QA fails: retry directly with QA feedback
            if QA passes: Critic reviews; rejection loops back to Architect
            if Critic escalates: ask user whether to retry or return current output
    """
    print_banner()
    print(f"  📋 Goal: {user_goal}")
    print(f"  {'═' * 56}\n")

    # ── Initialize all components ──
    tracer = AgentTracer()
    guardian = GuardianAI()
    scout = ScoutAgent()
    architect = ArchitectAgent()
    builder = BuilderAgent()
    integrator = IntegratorAgent()
    qa_verifier = QAVerifierAgent()
    permission_gate = UserPermissionGate()
    cache = get_cache()
    provider = get_provider()
    memory = SwarmMemory()

    # ── Determine execution mode from Claw bridge ──
    exec_mode = builder.claw.execution_mode
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
    raw_sub_tasks = decomposition.get("sub_tasks", [])

    def _normalize_sub_tasks(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Normalize IDs/dependencies so orchestration can safely schedule tasks."""
        normalized: list[dict[str, Any]] = []
        used_ids: set[int] = set()

        for index, item in enumerate(items, start=1):
            try:
                task_id = int(item.get("id", index))
            except (TypeError, ValueError):
                task_id = index

            while task_id in used_ids:
                task_id += 1
            used_ids.add(task_id)

            depends_on = item.get("depends_on", [])
            if isinstance(depends_on, (int, str)):
                depends_on = [depends_on]

            dep_ids: list[int] = []
            for dep in depends_on:
                try:
                    dep_id = int(dep)
                except (TypeError, ValueError):
                    continue
                if dep_id != task_id:
                    dep_ids.append(dep_id)

            normalized.append({
                **item,
                "id": task_id,
                "depends_on": sorted(set(dep_ids)),
            })

        valid_ids = {t["id"] for t in normalized}
        for task in normalized:
            task["depends_on"] = [dep for dep in task.get("depends_on", []) if dep in valid_ids]

        return normalized

    sub_tasks = _normalize_sub_tasks(raw_sub_tasks)

    if not sub_tasks:
        print("  ⚠️  Scout returned no sub-tasks. Aborting.")
        tracer.mark_complete()
        return []

    # Record Scout discoveries as facts
    memory.record_fact("goal_summary", decomposition.get("goal_summary", user_goal))
    memory.record_fact("complexity", decomposition.get("estimated_complexity", "unknown"))

    results = []

    # ══════════════════════════════════════════════
    # STEPS 2-6: Dependency-based parallel execution waves
    # Architect → Builder(s) → Integrator → QA (strict fail) → Critic
    # ══════════════════════════════════════════════
    stop_requested = False

    async def _execute_sub_task(task_obj: dict[str, Any]) -> dict[str, Any]:
        task_id = task_obj.get("id", "?")
        task_desc = task_obj.get("task", "Unknown task")
        priority = task_obj.get("priority", "medium").upper()
        dependencies = task_obj.get("depends_on", [])

        print(f"\n  {'─' * 56}")
        dep_label = f" deps={dependencies}" if dependencies else " deps=[]"
        print(f"  📌 Sub-task {task_id}/{len(sub_tasks)} [{priority}]{dep_label}: {task_desc}")

        feedback = ""
        critic = CriticAgent(max_rejections=2)
        execution_result: dict[str, Any] = {}

        for attempt in range(3):
            print(f"\n    ▸ Attempt {attempt + 1}/3 for Sub-task {task_id}")

            if slow:
                await asyncio.sleep(1.5)

            plan_context = memory.summarize_context()
            constraints = memory.get_actionable_constraints(
                proposed_files=task_obj.get("files_to_modify", [])
            )
            if constraints:
                plan_context = f"{plan_context}\n\n{constraints}".strip()

            plan = await asyncio.to_thread(
                architect.plan,
                sub_task=task_desc,
                feedback=feedback,
                context=plan_context,
                task_priority=priority,
                estimated_complexity=decomposition.get("estimated_complexity", "medium"),
                tracer=tracer
            )

            memory.record_builder_dispatch(
                task_desc,
                plan.get("builder_dispatch", {})
            )

            proposed_files = plan.get("files_to_modify", [])
            conflicts = memory.has_file_conflict(proposed_files)
            if conflicts:
                print(f"    ⚠️  File conflict detected: {', '.join(conflicts)}")
                print("    ⚠️  These files were modified by previous completed tasks.")

            if slow:
                await asyncio.sleep(2)
            builder_result = await asyncio.to_thread(
                builder.build,
                plan,
                tracer
            )

            integration_result = await asyncio.to_thread(
                integrator.integrate,
                plan,
                builder_result,
                tracer
            )

            qa_result = await asyncio.to_thread(
                qa_verifier.verify,
                plan,
                integration_result.get("generated_files", {}),
                builder_result.get("builder_reports", []),
                tracer,
            )

            execution_result = {
                **builder_result,
                **integration_result,
                "qa_result": qa_result,
                "output": integration_result.get("integrator_summary", ""),
                "success": builder_result.get("success", True) and qa_result.get("passed", True),
            }

            # Strict QA gate: Critic runs only if QA passes.
            if not qa_result.get("passed", False):
                qa_issues = qa_result.get("issues_found", [])
                qa_suggestions = qa_result.get("suggestions", [])
                feedback = (
                    f"QA failed. Issues: {', '.join(qa_issues)}. "
                    f"Suggestions: {', '.join(qa_suggestions)}"
                )
                memory.record_critic_feedback(f"Task '{task_desc}' QA: " + feedback)
                print(f"    ❌ QA failed for sub-task {task_id}; retrying before Critic.")
                if attempt < 2:
                    continue

                return {
                    "task_id": task_id,
                    "task": task_desc,
                    "status": "failed",
                    "score": qa_result.get("score", 0),
                    "attempts": attempt + 1,
                    "execution_mode": execution_result.get("execution_mode", "unknown"),
                    "saved_to": execution_result.get("saved_to", ""),
                }

            if slow:
                await asyncio.sleep(1.5)
            verdict = await asyncio.to_thread(
                critic.review,
                original_task=task_desc,
                plan=plan,
                execution_result=execution_result,
                tracer=tracer
            )

            if verdict["decision"] == "approve":
                score = verdict.get("score", "?")
                exec_mode_tag = execution_result.get("execution_mode", "unknown").upper()
                print(f"\n    ✅ Sub-task {task_id} complete! (score: {score}/100) [{exec_mode_tag}]")

                memory.record_task_result(task_id, task_desc, f"Completed with score {score}")
                for file_path in plan.get("files_to_modify", []):
                    memory.mark_file_modified(file_path)

                return {
                    "task_id": task_id,
                    "task": task_desc,
                    "status": "done",
                    "score": score,
                    "attempts": attempt + 1,
                    "execution_mode": execution_result.get("execution_mode", "unknown"),
                    "saved_to": execution_result.get("saved_to", ""),
                }

            if verdict["decision"] == "escalate_to_human":
                tracer.log("UserPermission", "retry_requested", {"task": task_desc})
                retry_approved = await permission_gate.request_retry_permission(
                    message=f"Task: {task_desc}",
                    details={
                        "issues": ", ".join(verdict.get("issues_found", [])),
                        "score": str(verdict.get("score", "?")),
                    }
                )

                if retry_approved and attempt < 2:
                    tracer.log("UserPermission", "retry_approved", {})
                    print(f"    🔁 User approved one more retry for sub-task {task_id}.")
                    feedback = (
                        f"User approved a retry after escalation. "
                        f"Issues: {', '.join(verdict.get('issues_found', []))}. "
                        f"Suggestions: {', '.join(verdict.get('suggestions', []))}"
                    )
                    memory.record_critic_feedback(f"Task '{task_desc}': " + feedback)
                    continue

                tracer.log("UserPermission", "retry_denied", {})
                print(f"    ⏹️  User declined retry. Returning current results.")
                return {
                    "task_id": task_id,
                    "task": task_desc,
                    "status": "partial_output",
                    "attempts": attempt + 1,
                    "execution_mode": execution_result.get("execution_mode", "unknown"),
                    "saved_to": execution_result.get("saved_to", ""),
                    "stop_requested": True,
                }

            issues = verdict.get("issues_found", [])
            score = verdict.get("score", "?")
            feedback = (
                f"Previous attempt scored {score}/100. "
                f"Issues: {', '.join(issues)}. "
                f"Suggestions: {', '.join(verdict.get('suggestions', []))}"
            )
            memory.record_critic_feedback(f"Task '{task_desc}': " + feedback)
            print(f"    🔄 Retrying sub-task {task_id} with Critic feedback...")

        return {
            "task_id": task_id,
            "task": task_desc,
            "status": "failed",
            "score": 0,
            "attempts": 3,
            "execution_mode": execution_result.get("execution_mode", "unknown"),
            "saved_to": execution_result.get("saved_to", ""),
        }

    pending = {task["id"]: task for task in sub_tasks}
    completed_ids: set[int] = set()
    failed_ids: set[int] = set()

    while pending and not stop_requested:
        blocked_ids = []
        for task_id, task_obj in list(pending.items()):
            deps = task_obj.get("depends_on", [])
            if any(dep in failed_ids for dep in deps):
                blocked_ids.append(task_id)
                results.append({
                    "task_id": task_id,
                    "task": task_obj.get("task", "Unknown task"),
                    "status": "skipped",
                    "attempts": 0,
                    "execution_mode": "n/a",
                })
                tracer.record_task_status(
                    task_obj.get("task", "Unknown task"),
                    "skipped",
                    execution_mode="n/a",
                    score=0,
                    attempts=0,
                )
                failed_ids.add(task_id)

        for task_id in blocked_ids:
            pending.pop(task_id, None)

        if not pending:
            break

        ready_tasks = [
            task_obj
            for task_obj in pending.values()
            if all(dep in completed_ids for dep in task_obj.get("depends_on", []))
        ]

        if not ready_tasks:
            print("\n  ⚠️  No dependency-ready tasks remain; possible dependency cycle.")
            for task_id, task_obj in list(pending.items()):
                results.append({
                    "task_id": task_id,
                    "task": task_obj.get("task", "Unknown task"),
                    "status": "skipped",
                    "attempts": 0,
                    "execution_mode": "n/a",
                })
                tracer.record_task_status(
                    task_obj.get("task", "Unknown task"),
                    "skipped",
                    execution_mode="n/a",
                    score=0,
                    attempts=0,
                )
                pending.pop(task_id, None)
            break

        ready_ids = [task.get("id") for task in ready_tasks]
        print(f"\n  🚀 Executing dependency-ready wave in parallel: {ready_ids}")
        wave_results = await asyncio.gather(*[_execute_sub_task(task_obj) for task_obj in ready_tasks])

        for task_result in wave_results:
            task_id = task_result.get("task_id")
            status = task_result.get("status", "failed")
            pending.pop(task_id, None)
            results.append(task_result)

            tracer.record_task_status(
                task_result.get("task", "Unknown task"),
                status,
                execution_mode=task_result.get("execution_mode", "unknown"),
                score=int(task_result.get("score", 0) or 0),
                attempts=int(task_result.get("attempts", 0) or 0),
            )

            if status == "done":
                completed_ids.add(task_id)
            else:
                failed_ids.add(task_id)

            if task_result.get("stop_requested"):
                stop_requested = True

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
            status_icon = {
                "done": "✅",
                "partial_output": "⏹️",
                "failed": "❌",
                "human_approved": "👤",
                "skipped": "⏭️",
            }.get(r.get("status"), "❓")
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
