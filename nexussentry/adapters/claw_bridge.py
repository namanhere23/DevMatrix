# nexussentry/adapters/claw_bridge.py
import subprocess, json, os, logging, time
from pathlib import Path

log = logging.getLogger("ClawBridge")

class ClawBridge:
    """
    THE critical piece — connects Python brain to Rust blade.
    PocketPaw sends tasks here; Claw Code executes them safely.
    """
    def __init__(self):
        self.binary = os.getenv("CLAW_BINARY", "claw")
        # We comment out health check for demo fallback in case Claw is not installed locally
        # self._health_check()

    def _health_check(self):
        try:
            r = subprocess.run([self.binary, "doctor"],
                               capture_output=True, text=True, timeout=15)
            if r.returncode != 0:
                log.warning(f"Claw Code unhealthy or not found: {r.stderr}")
            else:
                log.info("✅ Claw Code bridge ready")
        except FileNotFoundError:
            log.warning("Claw Code binary not found. Will run in mock mode if needed.")

    def run(self, task: str, context: dict = {}) -> dict:
        """Execute task in Rust sandbox. Returns structured result."""
        prompt = self._format_prompt(task, context)
        start  = time.time()

        try:
            result = subprocess.run(
                [self.binary, "prompt", prompt, "--output", "json"],
                capture_output=True, text=True, timeout=120
            )
            elapsed = round(time.time() - start, 2)

            if result.returncode != 0:
                # If claw isn't installed, let's mock the success for the hackathon demo.
                # In real life, it would return failure.
                if "No such file or directory" in result.stderr or result.returncode == 127:
                    return self._mock_run(task, elapsed)
                return {"success": False, "error": result.stderr,
                        "elapsed": elapsed}

            try:
                data = json.loads(result.stdout)
            except json.JSONDecodeError:
                data = {"success": True, "output": result.stdout}

            data["elapsed"] = elapsed
            log.info(f"🦀 Claw done in {elapsed}s")
            return data

        except subprocess.TimeoutExpired:
            return {"success": False, "error": "Timed out after 120s"}
        except FileNotFoundError:
            # Fallback for demo when Claw Rust binary isn't built.
            elapsed = round(time.time() - start, 2)
            return self._mock_run(task, elapsed)

    def _mock_run(self, task: str, elapsed: float) -> dict:
        """Demo fallback when Rust binary isn't present."""
        return {
            "success": False,
            "output": f"Mock failed: {task[:30]}... (Error: rust claw binary not found, execution blocked)",
            "files_modified": ["mock_file.txt"],
            "commands_run": ["echo mock"],
            "errors": [],
            "elapsed": elapsed + 1.2
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
