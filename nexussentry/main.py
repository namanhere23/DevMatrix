# nexussentry/main.py
"""
╔═══════════════════════════════════════════════════════════╗
║           NexusSentry v3.0 — Swarm Orchestrator           ║
║                                                           ║
║  Python orchestration · multi-provider LLM agents         ║
║                                                           ║
║  Coordinates specialized AI agents + MoA critic panel     ║
║  + constitutional safety + real-time WebSocket dashboard. ║
║                                                           ║
║  Multi-Provider AI: Gemini │ Groq │ OpenRouter │ HuggingFace║
╚═══════════════════════════════════════════════════════════╝
"""

import asyncio
import os
import re
import sys
import logging
import uuid
from pathlib import Path
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

# Silence noisy third-party logs
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("sentence_transformers").setLevel(logging.WARNING)

from nexussentry.agents.scout import ScoutAgent
from nexussentry.agents.architect import ArchitectAgent
from nexussentry.agents.builder import BuilderAgent
from nexussentry.agents.integrator import IntegratorAgent
from nexussentry.agents.qa_verifier import QAVerifierAgent
from nexussentry.agents.critic import CriticAgent
from nexussentry.agents.critic_panel import CriticPanel
from nexussentry.hitl.user_permission import UserPermissionGate
from nexussentry.observability.tracer import AgentTracer
from nexussentry.observability.dashboard import start_dashboard
from nexussentry.security.guardian import GuardianAI
from nexussentry.security.constitutional_guard import ConstitutionalGuard
from nexussentry.security.behavioral_guard import BehavioralGuardrail
from nexussentry.utils.response_cache import get_cache
from nexussentry.providers.llm_provider import get_provider
from nexussentry.utils.swarm_memory import SwarmMemory
from nexussentry.utils.watchdog import SwarmWatchdog, SwarmTimeoutError
from nexussentry.memory.feedback_store import SwarmFeedbackStore
from nexussentry.memory.typed_memory import SwarmSessionMemory
from nexussentry.communication.blackboard import SwarmBlackboard
from nexussentry.contracts import GoalContract, RunContext, derive_goal_contract
from nexussentry.memory.episodic_memory import EpisodicMemory
from nexussentry.observability.cost_tracker import CostTracker
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
║   \033[93mPython orchestration · multi-provider LLM agents\033[95m          ║
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
    qa_verifier = QAVerifierAgent()
    permission_gate = UserPermissionGate()
    cache = get_cache()
    provider = get_provider()
    memory = SwarmMemory()

    # v3.0: New components
    constitutional_guard = ConstitutionalGuard()
    behavioral_guard = BehavioralGuardrail()
    feedback_store = SwarmFeedbackStore()
    session_memory = SwarmSessionMemory(session_id=getattr(tracer, 'session_id', ''), goal=user_goal)
    blackboard = SwarmBlackboard(namespace=getattr(tracer, 'session_id', 'default'))
    watchdog = SwarmWatchdog(max_wall_time_seconds=int(os.getenv('NEXUS_MAX_WALL_TIME', '300')))
    all_agent_outputs: list[dict] = []  # For behavioral audit
    episodic_memory = EpisodicMemory()
    cost_tracker = CostTracker()

    # ── Derive GoalContract from user intent ──
    goal_contract = derive_goal_contract(user_goal)
    project_root = Path(__file__).resolve().parent.parent
    run_id = getattr(tracer, "session_id", None) or uuid.uuid4().hex[:16]
    run_output_dir = project_root / "output" / f"session_{run_id}"
    run_context = RunContext(
        run_id=run_id,
        run_output_dir=run_output_dir,
        goal_contract=goal_contract,
    )

    # Create canonical output structure up front
    run_context.final_artifact_dir.mkdir(parents=True, exist_ok=True)
    run_context.attempts_dir.mkdir(parents=True, exist_ok=True)

    integrator = IntegratorAgent(run_context=run_context)

    # ── Print contract summary ──
    print(f"  📜 GoalContract:")
    print(f"     single_file={goal_contract.single_file}")
    print(f"     allowed_outputs={goal_contract.allowed_output_files}")
    print(f"     inline_assets={goal_contract.requires_inline_assets}")
    print(f"     parallelism={goal_contract.parallelism_mode}")
    print(f"     entrypoint={goal_contract.preferred_entrypoint}")
    print(f"  📂 Run output: {run_output_dir}")

    # ── Execution path (in-process builder / LLM generation) ──
    exec_mode = builder.execution_mode
    exec_badge = f"[{exec_mode.upper()}]"
    print(f"  ⚡ Execution Mode: {exec_badge}")

    # ── Show provider info ──
    print(f"  🤖 AI Providers: {provider.provider_summary_str()}")
    print(f"\n  Agent → Provider Routing:")
    print(provider.agent_routing_str())
    print()

    # ── Start dashboard server ──
    ws_dashboard = None
    if enable_dashboard:
        try:
            start_dashboard(tracer, port=7777)
        except OSError:
            print("  ⚠️  Dashboard port 7777 in use, trying 7778...")
            try:
                start_dashboard(tracer, port=7778)
            except OSError:
                print("  ⚠️  Dashboard unavailable (ports busy)")

        # v3.0: Start WebSocket dashboard alongside HTTP
        try:
            from nexussentry.observability.ws_dashboard import RealtimeDashboard, WEBSOCKETS_AVAILABLE
            if WEBSOCKETS_AVAILABLE:
                ws_dashboard = RealtimeDashboard(tracer)
                ws_dashboard.start(port=7779)
        except Exception:
            pass  # WebSocket dashboard is optional

    tracer.log("System", "swarm_start", {
        "goal": user_goal,
        "providers": provider.available_providers,
        "mock_mode": provider.mock_mode,
        "execution_mode": exec_mode,
        "goal_contract": goal_contract.to_dict(),
    })
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

        valid_ids = {task["id"] for task in normalized}
        for task in normalized:
            task["depends_on"] = [dep for dep in task.get("depends_on", []) if dep in valid_ids]

        return normalized

    async def _execute_sub_task(task_obj: dict[str, Any], decomposition: dict[str, Any]) -> dict[str, Any]:
        task_id = task_obj.get("id", "?")
        task_desc = task_obj.get("task", "Unknown task")
        priority = task_obj.get("priority", "medium").upper()
        dependencies = task_obj.get("depends_on", [])

        print(f"\n  {'─' * 56}")
        dep_label = f" deps={dependencies}" if dependencies else " deps=[]"
        print(f"  📌 Sub-task {task_id}/{len(decomposition.get('sub_tasks', []))} [{priority}]{dep_label}: {task_desc}")

        feedback = ""
        critic_panel = CriticPanel(max_rejections=2)
        execution_result: dict[str, Any] = {}
        
        # Track best attempt across retries in case all 3 fail
        best_attempt_score = -1
        best_attempt_data = None

        # v3.0: Get task working memory
        task_memory = session_memory.get_or_create_task_memory(task_id, task_obj)

        for attempt in range(3):
            # v3.0: Watchdog check at start of each attempt
            try:
                watchdog.check()
            except SwarmTimeoutError as e:
                print(f"\n  ⏰ WATCHDOG TIMEOUT: {e}")
                return {
                    "task_id": task_id,
                    "task": task_desc,
                    "status": "failed",
                    "score": 0,
                    "attempts": attempt,
                    "execution_mode": "timeout",
                    "saved_to": "",
                }

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
                tracer=tracer,
                goal_contract=goal_contract,
            )

            # v3.0: Constitutional check on Architect output
            const_verdict = constitutional_guard.check_output("architect", plan)
            if not const_verdict.safe:
                print(f"    ⛔ Constitutional violation in plan: {const_verdict.description}")
                feedback = f"Constitutional violation: {const_verdict.description}. Redo the plan."
                continue

            # v3.0: Record plan in typed memory and blackboard
            task_memory.record_plan(plan)
            blackboard.post(f"plan:task_{task_id}:attempt_{attempt}", plan, agent="architect")
            all_agent_outputs.append(plan)

            memory.record_builder_dispatch(
                task_desc,
                plan.get("builder_dispatch", {}),
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
                tracer,
            )

            integration_result = await asyncio.to_thread(
                integrator.integrate,
                plan,
                builder_result,
                tracer,
                task_id=task_id,
            )

            qa_result = await asyncio.to_thread(
                qa_verifier.verify,
                plan,
                integration_result.get("generated_files", {}),
                builder_result.get("builder_reports", []),
                tracer,
                goal_contract=goal_contract,
            )

            execution_result = {
                **builder_result,
                **integration_result,
                "qa_result": qa_result,
                "output": integration_result.get("integrator_summary", ""),
                "success": builder_result.get("success", True) and qa_result.get("passed", True),
            }

            # v3.0: Constitutional check on Builder output
            const_verdict = constitutional_guard.check_output(
                "builder", execution_result.get("generated_files", {})
            )
            if not const_verdict.safe:
                print(f"    ⛔ Constitutional violation in build: {const_verdict.description}")
                feedback = f"Constitutional violation in generated code: {const_verdict.description}"
                all_agent_outputs.append(execution_result)
                continue

            # v3.0: Record execution in typed memory
            task_memory.record_output(execution_result)
            all_agent_outputs.append(execution_result)

            if not qa_result.get("passed", False):
                qa_score = int(qa_result.get("score", 0))
                if qa_score > best_attempt_score:
                    best_attempt_score = qa_score
                    best_attempt_data = {
                        "generated_files": integration_result.get("generated_files", {}),
                        "execution_result": execution_result,
                        "score": qa_score
                    }

                qa_issues = qa_result.get("issues_found", [])
                qa_suggestions = qa_result.get("suggestions", [])
                feedback = (
                    f"QA failed. Issues: {', '.join(qa_issues)}. "
                    f"Suggestions: {', '.join(qa_suggestions)}"
                )
                memory.record_critic_feedback(f"Task '{task_desc}' QA: " + feedback)
                print(f"    ❌ QA failed for sub-task {task_id}; retrying before Critic.")
                continue

            if slow:
                await asyncio.sleep(1.5)

            # v3.0: Use CriticPanel (MoA debate) instead of single Critic
            verdict = await asyncio.to_thread(
                critic_panel.review,
                original_task=task_desc,
                plan=plan,
                execution_result=execution_result,
                tracer=tracer,
                goal_contract=goal_contract,
            )

            # v3.0: Record verdict in typed memory
            task_memory.record_verdict(verdict)

            score_str = verdict.get("score", "?")
            try:
                numeric_score = int(score_str)
            except (ValueError, TypeError):
                numeric_score = 0
                
            if numeric_score > best_attempt_score:
                best_attempt_score = numeric_score
                best_attempt_data = {
                    "generated_files": integration_result.get("generated_files", {}),
                    "execution_result": execution_result,
                    "score": numeric_score
                }

            if verdict["decision"] == "approve":
                score = verdict.get("score", "?")
                exec_mode_tag = execution_result.get("execution_mode", "unknown").upper()
                print(f"\n    ✅ Sub-task {task_id} complete! (score: {score}/100) [{exec_mode_tag}]")

                # Promote approved artifacts to final/
                integrator.promote_to_final(
                    integration_result.get("generated_files", {})
                )

                if best_attempt_data:
                    max_output_dir = run_context.run_output_dir / "max_output"
                    max_output_dir.mkdir(parents=True, exist_ok=True)
                    integrator.save_snapshot(
                        max_output_dir,
                        best_attempt_data["generated_files"],
                    )

                memory.record_task_result(task_id, task_desc, f"Completed with score {score}")
                for file_path in plan.get("files_to_modify", []):
                    memory.mark_file_modified(file_path)

                # v3.0: Update blackboard and watchdog
                blackboard.post(f"result:task_{task_id}", {"status": "done", "score": score}, agent="critic_panel")
                watchdog.record_task_complete()

                # v3.0: Store successful episode in episodic memory
                try:
                    episodic_memory.store_episode(
                        task=task_desc,
                        plan=plan,
                        result_summary=execution_result.get("output", "")[:300],
                        score=int(score) if isinstance(score, (int, float)) else 0
                    )
                except Exception:
                    pass  # Episodic memory is optional

                return {
                    "task_id": task_id,
                    "task": task_desc,
                    "status": "done",
                    "score": score,
                    "attempts": attempt + 1,
                    "execution_mode": execution_result.get("execution_mode", "unknown"),
                    "delivery_status": "approved",
                    "saved_to": str(run_context.final_artifact_dir),
                }

            if verdict["decision"] == "escalate_to_human":
                tracer.log("UserPermission", "retry_requested", {"task": task_desc})
                retry_approved = await permission_gate.request_retry_permission(
                    message=f"Task: {task_desc}",
                    details={
                        "issues": ", ".join(verdict.get("issues_found", [])),
                        "score": str(verdict.get("score", "?")),
                    },
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
                
                if best_attempt_data:
                    max_output_dir = run_context.run_output_dir / "max_output"
                    max_output_dir.mkdir(parents=True, exist_ok=True)
                    integrator.save_snapshot(
                        max_output_dir,
                        best_attempt_data["generated_files"],
                    )

                return {
                    "task_id": task_id,
                    "task": task_desc,
                    "status": "partial_output",
                    "attempts": attempt + 1,
                    "execution_mode": execution_result.get("execution_mode", "unknown"),
                    "delivery_status": "best_effort",
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

            # v3.0: Record rejection in feedback store for future learning
            feedback_store.record_rejection(
                task=task_desc,
                plan=plan,
                verdict=verdict,
                attempt=attempt + 1,
            )

            print(f"    🔄 Retrying sub-task {task_id} with Panel feedback...")

        # If we exhausted all attempts, save best effort (NOT to final/)
        if best_attempt_data:
            best_effort_dir = run_context.run_output_dir / "best_effort" / f"task_{task_id}"
            best_effort_dir.mkdir(parents=True, exist_ok=True)
            
            max_output_dir = run_context.run_output_dir / "max_output"
            max_output_dir.mkdir(parents=True, exist_ok=True)
            
            integrator.save_snapshot(
                best_effort_dir,
                best_attempt_data["generated_files"],
            )
            integrator.save_snapshot(
                max_output_dir,
                best_attempt_data["generated_files"],
            )
            print(f"    ⚠️ All attempts failed. Best attempt (score: {best_attempt_data['score']}/100) saved to best_effort/ and max_output/")

            return {
                "task_id": task_id,
                "task": task_desc,
                "status": "partial_output",
                "score": best_attempt_data["score"],
                "attempts": 3,
                "execution_mode": best_attempt_data["execution_result"].get("execution_mode", "unknown"),
                "delivery_status": "best_effort",
                "saved_to": str(best_effort_dir),
            }

        return {
            "task_id": task_id,
            "task": task_desc,
            "status": "failed",
            "score": 0,
            "attempts": 3,
            "execution_mode": execution_result.get("execution_mode", "unknown"),
            "delivery_status": "failed",
            "saved_to": execution_result.get("saved_to", ""),
        }

    def _print_final_summary(results: list[dict[str, Any]]) -> None:
        tracer.mark_complete()
        summary = tracer.summary()
        cache_stats = cache.stats()
        security_stats = guardian.stats()
        provider_stats = provider.stats()
        constitutional_stats = constitutional_guard.stats()
        watchdog_summary = watchdog.summary()

        # v3.0: Run behavioral audit on all agent outputs
        behavioral_anomalies = behavioral_guard.audit_swarm_run(all_agent_outputs)

        exec_modes_used = list({r.get("execution_mode", "unknown") for r in results if isinstance(r, dict)})
        if len(exec_modes_used) == 1:
            overall_mode = exec_modes_used[0].upper()
        elif exec_modes_used:
            overall_mode = "MIXED"
        else:
            overall_mode = "NONE"

        # ── Write manifest.json ──
        integrator.write_manifest(
            goal=user_goal,
            tasks=results,
            summary=summary,
            provider_stats=provider_stats,
        )

        print(f"\n  {'═' * 56}")
        print(f"  🏁 NexusSentry v3.0 Swarm Complete! [{overall_mode}]")
        print(f"  {'─' * 56}")
        print(f"    Total time:     {summary['total_time_s']}s")
        print(f"    Total events:   {summary['total_events']}")
        print(f"    Agents used:    {', '.join(summary['agents_used'])}")
        print(f"    Approvals:      {summary['approvals']}")
        print(f"    Rejections:     {summary['rejections']}")
        print(f"    Security scans: {security_stats['scans_performed']}")
        print(f"    Cache hit rate: {cache_stats['hit_rate']}")
        print(f"    LLM calls:     {provider_stats['total_calls']}")
        print(f"    Providers used: {provider_stats['provider_usage']}")
        print(f"    Execution mode: {overall_mode}")
        print(f"    Trace log:      {summary['log_file']}")

        # v3.0: Enhanced stats
        print(f"  {'─' * 56}")
        print(f"  🆕 v3.0 Intelligence:")
        print(f"    💰 Est. cost:   {provider_stats.get('estimated_session_cost', '$0.0000')}")
        print(f"    🛡️ Const. guard: {constitutional_stats['checks_performed']} checks, {constitutional_stats['violations_caught']} violations")
        print(f"    ⏱️ Watchdog:     {watchdog_summary['elapsed_s']}s / {watchdog_summary['max_wall_time_s']}s")
        if behavioral_anomalies:
            print(f"    ⚠️ Anomalies:   {len(behavioral_anomalies)} detected")
            for a in behavioral_anomalies[:3]:
                print(f"       [{a['severity'].upper()}] {a['type']}: {a['description'][:60]}")
        else:
            print(f"    ✅ Anomalies:   None detected")

        # Blackboard summary
        bb_summary = blackboard.summary()
        print(f"    📋 Blackboard:  {bb_summary['total_keys']} keys, {bb_summary['total_writes']} writes")

        # Feedback store stats
        rejection_stats = feedback_store.get_rejection_stats()
        if rejection_stats.get('total_rejections', 0) > 0:
            print(f"    📚 Feedback:    {rejection_stats['total_rejections']} rejections recorded")

        # Episodic memory stats
        ep_stats = episodic_memory.stats()
        if ep_stats.get('available'):
            print(f"    🧠 Episodes:    {ep_stats['episode_count']} stored")

        # Cost tracker summary
        cost_tracker.print_summary()

        print(f"  {'─' * 56}")
        print(f"   📂 Run output:   {run_context.run_output_dir}")
        print(f"   📂 Final files:  {run_context.final_artifact_dir}")

        # List final artifacts
        if run_context.final_artifact_dir.exists():
            final_files = [
                f.relative_to(run_context.final_artifact_dir).as_posix()
                for f in run_context.final_artifact_dir.rglob("*")
                if f.is_file()
            ]
            if final_files:
                print(f"   📄 Artifacts:    {', '.join(sorted(final_files))}")

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
        print(f"\n  \033[95m✨ NexusSentry v3.0 — Python orchestration · multi-provider LLM agents ✨\033[0m\n")
    original_provider_concurrency = None
    if hasattr(provider, "get_max_concurrency"):
        original_provider_concurrency = provider.get_max_concurrency()

    try:
        if goal_contract.parallelism_mode == "serialized":
            provider.set_max_concurrency(1)

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

        if slow:
            await asyncio.sleep(2)

        context = memory.summarize_context()
        scout_input = user_goal if not context else f"{user_goal}\n\nContext:\n{context}"
        decomposition = scout.decompose(scout_input, tracer, goal_contract=goal_contract)
        sub_tasks = _normalize_sub_tasks(decomposition.get("sub_tasks", []))

        if not sub_tasks:
            print("  ⚠️  Scout returned no sub-tasks. Aborting.")
            tracer.mark_complete()
            return []

        memory.record_fact("goal_summary", decomposition.get("goal_summary", user_goal))
        memory.record_fact("complexity", decomposition.get("estimated_complexity", "unknown"))

        watchdog.set_total_tasks(len(sub_tasks))
        complexity = decomposition.get("estimated_complexity", "unknown")
        print(f"  📊 Complexity: {complexity}")
        blackboard.post("complexity", complexity, agent="scout")

        pending = list(sub_tasks)
        completed_ids: set[int] = set()
        failed_ids: set[int] = set()
        results: list[dict[str, Any]] = []
        stop_requested = False

        while pending and not stop_requested:
            blocked_ids = []
            for task_obj in list(pending):
                deps = task_obj.get("depends_on", [])
                if any(dep in failed_ids for dep in deps):
                    task_id = task_obj.get("id")
                    blocked_ids.append(task_id)
                    task_result = {
                        "task_id": task_id,
                        "task": task_obj.get("task", "Unknown task"),
                        "status": "skipped",
                        "attempts": 0,
                        "execution_mode": "n/a",
                    }
                    results.append(task_result)
                    tracer.record_task_status(
                        task_obj.get("task", "Unknown task"),
                        "skipped",
                        execution_mode="n/a",
                        score=0,
                        attempts=0,
                    )
                    failed_ids.add(task_id)

            pending = [task for task in pending if task.get("id") not in blocked_ids]
            if not pending:
                break

            ready_tasks = [
                task_obj
                for task_obj in pending
                if all(dep in completed_ids for dep in task_obj.get("depends_on", []))
            ]

            if not ready_tasks:
                print("\n  ⚠️  No dependency-ready tasks remain; possible dependency cycle.")
                for index, task_obj in enumerate(list(pending)):
                    task_id_value = task_obj.get("id", index)
                    task_result = {
                        "task_id": task_id_value,
                        "task": task_obj.get("task", "Unknown task"),
                        "status": "skipped",
                        "attempts": 0,
                        "execution_mode": "n/a",
                    }
                    results.append(task_result)
                    tracer.record_task_status(
                        task_obj.get("task", "Unknown task"),
                        "skipped",
                        execution_mode="n/a",
                        score=0,
                        attempts=0,
                    )
                break

            ready_ids = [task.get("id") for task in ready_tasks]
            if goal_contract.parallelism_mode == "serialized":
                print(f"\n  🔗 Executing tasks in serialized mode: {ready_ids}")
                wave_results = []
                for task_obj in ready_tasks:
                    wave_results.append(await _execute_sub_task(task_obj, decomposition))
            else:
                print(f"\n  🚀 Executing dependency-ready wave in parallel: {ready_ids}")
                wave_results = await asyncio.gather(
                    *[_execute_sub_task(task_obj, decomposition) for task_obj in ready_tasks]
                )

            for task_result in wave_results:
                task_id = task_result.get("task_id")
                status = task_result.get("status", "failed")
                pending = [task for task in pending if task.get("id") != task_id]
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

        _print_final_summary(results)
        return results
    finally:
        if original_provider_concurrency is not None:
            provider.set_max_concurrency(original_provider_concurrency)


if __name__ == "__main__":
    goal = (
        "Analyze this Python project for security vulnerabilities "
        "and fix the top 3 critical issues"
    )

    # Allow goal to be passed as CLI argument
    if len(sys.argv) > 1:
        goal = " ".join(sys.argv[1:])

    asyncio.run(run_swarm(goal))
