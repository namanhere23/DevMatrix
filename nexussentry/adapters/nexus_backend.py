# nexussentry/adapters/nexus_backend.py
"""
NexusSentry Agent Backend — Claw Code Integration

Implements NexusSentry's AgentBackend protocol for routing
code execution tasks to the Claw Code Rust sandbox.

Installation: pip install nexussentry[all]
Or use directly by importing this class.
"""

import json
from nexussentry.adapters.claw_bridge import ClawBridge


class NexusClawBackend:
    """
    Implements NexusSentry's AgentBackend protocol.
    This is what NexusSentry calls when it needs code executed by Claw Code.
    """
    name = "claw_code"
    description = "Rust-sandboxed code execution via Claw Code"

    def __init__(self):
        self.bridge = ClawBridge()

    @property
    def execution_mode(self) -> str:
        """Report the current execution mode of the Claw bridge."""
        return self.bridge.execution_mode

    def complete(self, messages: list, system: str = "") -> str:
        """
        Execute a task via Claw Code.
        
        Args:
            messages: List of message dicts with 'role' and 'content' keys.
            system: Optional system prompt (unused for code execution).
            
        Returns:
            JSON string with execution result including execution_mode.
        """
        # Extract the last user message as the task
        task = messages[-1]["content"] if messages else ""
        result = self.bridge.run(task=task)
        return json.dumps(result, indent=2)

    def health(self) -> dict:
        """
        Report the health and readiness of the Claw Code bridge.
        
        Returns:
            Dict with availability status and execution mode.
        """
        return {
            "name": self.name,
            "available": self.bridge.claw_available,
            "execution_mode": self.bridge.execution_mode,
            "binary": self.bridge.binary,
        }
