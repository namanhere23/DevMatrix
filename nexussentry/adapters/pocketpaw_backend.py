# nexussentry/adapters/pocketpaw_backend.py
import json
from nexussentry.adapters.claw_bridge import ClawBridge

class PocketPawClawBackend:
    """
    Implements PocketPaw's AgentBackend protocol.
    This is what PocketPaw calls when it needs code executed by Claw Code.
    """
    name = "claw_code"
    description = "Rust-sandboxed code execution via Claw Code"

    def __init__(self):
        self.bridge = ClawBridge()

    def complete(self, messages: list, system: str = "") -> str:
        # Extract the last user message as the task
        task = messages[-1]["content"] if messages else ""
        result = self.bridge.run(task=task)
        return json.dumps(result, indent=2)
