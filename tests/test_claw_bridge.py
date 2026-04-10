"""
Tests for ClawBridge execution mode behavior.
Verifies that the bridge correctly reports real/simulated mode
and produces honest output in each mode.
"""

import pytest
from nexussentry.adapters.claw_bridge import ClawBridge


class TestClawBridgeExecutionMode:
    """Tests for explicit execution mode reporting."""

    def test_execution_mode_property_exists(self):
        """ClawBridge should have an execution_mode property."""
        bridge = ClawBridge()
        assert hasattr(bridge, "execution_mode")
        assert bridge.execution_mode in ("real", "simulated")

    def test_claw_available_flag(self):
        """claw_available should be False when binary doesn't exist."""
        bridge = ClawBridge()
        # In test env, claw binary won't be installed
        assert bridge.claw_available is False
        assert bridge.execution_mode == "simulated"

    def test_simulated_run_output_format(self):
        """Simulated runs should have clear markers and no fake data."""
        bridge = ClawBridge()
        result = bridge._simulated_run("Test task description", 0.5)

        # Must include execution_mode
        assert result["execution_mode"] == "simulated"

        # Must NOT have fake file modifications
        assert result["files_modified"] == []
        assert result["commands_run"] == []

        # Output should clearly indicate simulation
        assert "[SIMULATED]" in result["output"]

        # Should still report success (task was queued, not failed)
        assert result["success"] is True

    def test_simulated_run_includes_elapsed(self):
        """Elapsed time should be present and reasonable."""
        bridge = ClawBridge()
        result = bridge._simulated_run("Test", 0.3)
        assert "elapsed" in result
        assert result["elapsed"] > 0

    def test_run_returns_execution_mode(self):
        """The run() method should always include execution_mode in results."""
        bridge = ClawBridge()
        result = bridge.run(task="echo hello", context={})
        assert "execution_mode" in result

    def test_format_prompt_includes_context(self):
        """_format_prompt should include context keys."""
        bridge = ClawBridge()
        prompt = bridge._format_prompt("do something", {"key1": "val1", "key2": "val2"})
        assert "key1: val1" in prompt
        assert "key2: val2" in prompt
        assert "do something" in prompt
