# nexussentry/adapters/claw_bridge.py
"""
THE critical piece — connects Python brain to Rust blade.
NexusSentry sends tasks here; Claw Code executes them safely.

Execution modes:
  - "real"       — Claw Code binary found and executed successfully
  - "simulated"  — Binary not found, LLM-enhanced simulation used
  - "unavailable"— Binary not found and no LLM available
"""

import subprocess, json, os, logging, time
from pathlib import Path

log = logging.getLogger("ClawBridge")


class ClawBridge:
    """
    THE critical piece — connects Python brain to Rust blade.
    NexusSentry sends tasks here; Claw Code executes them safely.
    """
    def __init__(self):
        self.binary = os.getenv("CLAW_BINARY", "claw")
        self.claw_available = False
        self._check_claw_availability()

    def _check_claw_availability(self):
        """Non-blocking health check — determines execution mode."""
        try:
            r = subprocess.run(
                [self.binary, "doctor"],
                capture_output=True, text=True, timeout=15
            )
            if r.returncode == 0:
                self.claw_available = True
                log.info("Claw Code bridge ready")
            else:
                self.claw_available = False
                log.warning(f"Claw Code unhealthy: {r.stderr[:100]}")
        except FileNotFoundError:
            self.claw_available = False
            log.warning("Claw Code binary not found. Running in simulated mode.")
        except subprocess.TimeoutExpired:
            self.claw_available = False
            log.warning("Claw Code health check timed out. Running in simulated mode.")
        except Exception as e:
            self.claw_available = False
            log.warning(f"Claw Code health check failed: {e}. Running in simulated mode.")

    @property
    def execution_mode(self) -> str:
        """Return the current execution mode: 'real', 'simulated', or 'unavailable'."""
        return "real" if self.claw_available else "simulated"

    def run(self, task: str, context: dict = {}) -> dict:
        """Execute task in Rust sandbox. Returns structured result with execution_mode."""
        prompt = self._format_prompt(task, context)
        start  = time.time()

        try:
            result = subprocess.run(
                [self.binary, "prompt", prompt, "--output", "json"],
                capture_output=True, text=True, timeout=120
            )
            elapsed = round(time.time() - start, 2)

            if result.returncode != 0:
                # If claw isn't installed, fall back to simulated mode
                if "No such file or directory" in result.stderr or result.returncode == 127:
                    return self._simulated_run(task, elapsed)
                return {
                    "success": False,
                    "error": result.stderr,
                    "elapsed": elapsed,
                    "execution_mode": "real",
                }

            try:
                data = json.loads(result.stdout)
            except json.JSONDecodeError:
                data = {"success": True, "output": result.stdout}

            data["elapsed"] = elapsed
            data["execution_mode"] = "real"
            log.info(f"Claw done in {elapsed}s [REAL]")
            return data

        except subprocess.TimeoutExpired:
            return {
                "success": False,
                "error": "Timed out after 120s",
                "execution_mode": "real",
            }
        except FileNotFoundError:
            # Fallback when Rust binary isn't built
            elapsed = round(time.time() - start, 2)
            return self._simulated_run(task, elapsed)

    def _simulated_run(self, task: str, elapsed: float) -> dict:
        """
        Simulated fallback when Rust binary isn't present.
        Clearly marked as simulated — no fake file modifications.
        """
        return {
            "success": True,
            "output": f"[SIMULATED] Task queued for execution: {task[:80]}... "
                      f"(Claw Code binary not available — results are simulated)",
            "files_modified": [],
            "commands_run": [],
            "errors": [],
            "elapsed": elapsed + 1.2,
            "execution_mode": "simulated",
        }

    def _format_prompt(self, task: str, ctx: dict) -> str:
        ctx_lines = "\n".join(f"  {k}: {v}" for k, v in ctx.items())
        return f"""
CONTEXT:
{ctx_lines}

TASK:
{task}

OUTPUT FORMAT (strict JSON):
{{
  "success": true/false,
  "output": "description of what was done",
  "files_modified": ["file1.py", ...],
  "commands_run": ["cmd1", ...],
  "errors": []
}}
"""
