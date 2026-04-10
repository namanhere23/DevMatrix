# nexussentry/agents/fixer.py
"""
Agent C — The Fixer
━━━━━━━━━━━━━━━━━━━
Executes the Architect's plan using Claw Code's Rust sandbox.
The "hands" of the swarm — this is where code actually gets modified.

When Claw Code is unavailable, uses LLM to simulate execution.

Role in the swarm: Executor. The one who does the work.
Provider preference: auto (uses whatever's available)
"""

import json
import re
import logging

from nexussentry.adapters.claw_bridge import ClawBridge
from nexussentry.providers.llm_provider import get_provider

logger = logging.getLogger("Fixer")

FIXER_SYSTEM = """You are a precise code execution engine. Given a technical plan, 
simulate its execution and report what changes would be made.

Respond ONLY with valid JSON:
{
  "success": true/false,
  "output": "description of what was done",
  "files_modified": ["file1.py", ...],
  "commands_run": ["cmd1", ...],
  "errors": []
}"""


class FixerAgent:
    """Executes the Architect's plan using Claw Code's Rust sandbox."""

    def __init__(self):
        self.claw = ClawBridge()
        self.tasks_executed = 0

    def execute(self, plan: dict, tracer=None) -> dict:
        plan_summary = plan.get("plan_summary", "Unknown plan")
        provider = get_provider()
        provider_name = provider.get_provider_for_agent("fixer")

        if tracer:
            tracer.log("Fixer", "execute_start", {
                "plan": plan_summary,
                "provider": provider_name,
                "execution_mode": self.claw.execution_mode,
            })

        mode_badge = f" [{self.claw.execution_mode.upper()}]"
        print(f"\n🔧 Fixer executing{mode_badge}...")

        try:
            # Build a detailed prompt from the Architect's plan
            task = f"""
Execute this technical plan:

PLAN: {plan_summary}
APPROACH: {plan.get('approach', 'Direct implementation')}

Files to read first: {', '.join(plan.get('files_to_read', []))}
Files to modify: {', '.join(plan.get('files_to_modify', []))}
Commands to run: {'; '.join(plan.get('commands_to_run', []))}
Success criteria: {plan.get('success_criteria', 'Task completes without errors')}

Be careful. Report every change. If something fails, report it honestly.
"""
            result = self.claw.run(
                task=task,
                context={"safety_mode": "sandboxed", "dry_run": "false"}
            )

            # If Claw returned a simulated result, enhance it with LLM reasoning
            if result.get("execution_mode") == "simulated":
                result = self._llm_enhanced_execution(plan, result, provider)

            self.tasks_executed += 1
            status = "✅ Success" if result.get("success") else "❌ Failed"
            elapsed = result.get("elapsed", "?")
            exec_mode = result.get("execution_mode", "unknown").upper()
            print(f"🔧 Fixer result: {status} [{exec_mode}] ({elapsed}s) via {provider_name}")

            if tracer:
                tracer.log("Fixer", "execute_done", {
                    **result,
                    "provider": provider_name,
                    "execution_mode": result.get("execution_mode", "unknown"),
                })

            return result

        except Exception as e:
            logger.error(f"Fixer execution failed: {e}")
            error_result = {
                "success": False,
                "error": str(e),
                "output": "Fixer execution encountered an error",
                "files_modified": [],
                "commands_run": [],
                "elapsed": 0,
                "execution_mode": "unavailable",
            }
            print(f"🔧 Fixer result: ❌ Error [UNAVAILABLE] — {e}")
            if tracer:
                tracer.log("Fixer", "execute_error", {"error": str(e), "execution_mode": "unavailable"})
            return error_result

    def _llm_enhanced_execution(self, plan: dict, mock_result: dict,
                                 provider) -> dict:
        """When Claw Code is in simulated mode, use LLM to generate realistic execution output."""
        try:
            raw = provider.chat(
                system=FIXER_SYSTEM,
                user_msg=f"""Simulate executing this plan:
Plan: {plan.get('plan_summary', '')}
Approach: {plan.get('approach', '')}
Files: {', '.join(plan.get('files_to_modify', []))}
Commands: {'; '.join(plan.get('commands_to_run', []))}""",
                max_tokens=800,
                agent_name="fixer"
            )

            # Try to parse JSON from response
            try:
                result = json.loads(raw)
            except json.JSONDecodeError:
                json_match = re.search(r'\{.*\}', raw, re.DOTALL)
                if json_match:
                    result = json.loads(json_match.group(0))
                else:
                    result = mock_result

            result["elapsed"] = mock_result.get("elapsed", 1.5)
            result["execution_mode"] = "simulated"
            result.setdefault("success", True)
            result.setdefault("files_modified", [])
            result.setdefault("commands_run", [])
            result.setdefault("errors", [])
            return result

        except Exception:
            return mock_result
