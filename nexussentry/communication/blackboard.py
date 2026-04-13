# nexussentry/communication/blackboard.py
"""
Swarm Blackboard v3.0 — Shared Knowledge Space
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Shared knowledge space where all agents can read and write.
Eliminates tight coupling between agents — no agent needs to know
another agent's interface, only the shared data schema.

Inspired by Symphony paper (decentralized multi-agent collective intelligence).
"""

import asyncio
import time
import logging
import threading
from collections import defaultdict
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger("Blackboard")


class SwarmBlackboard:
    """
    Shared knowledge space. Agents post to it and subscribe to it.
    Thread-safe for use in both sync and async contexts.

    Usage:
        blackboard = SwarmBlackboard()
        blackboard.post("plan:task_1", architect_plan, agent="architect")
        plan = blackboard.get("plan:task_1")
    """

    def __init__(self, namespace: str = "default"):
        self.namespace = namespace
        self._board: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.RLock()
        self._history: List[Dict[str, Any]] = []

    def post(self, key: str, value: Any, agent: str = "unknown"):
        """Any agent can write to the blackboard. Thread-safe."""
        with self._lock:
            version = self._board.get(key, {}).get("version", 0) + 1

            entry = {
                "value": value,
                "posted_by": agent,
                "timestamp": time.time(),
                "version": version,
            }
            self._board[key] = entry

            # Record in history
            self._history.append({
                "key": key,
                "agent": agent,
                "version": version,
                "timestamp": entry["timestamp"],
            })

            logger.debug(f"Blackboard [{self.namespace}] {agent} posted '{key}' (v{version})")

    def get(self, key: str) -> Optional[Any]:
        """Get the latest value for a key. Returns None if not found."""
        with self._lock:
            entry = self._board.get(key)
            return entry["value"] if entry else None

    def get_with_metadata(self, key: str) -> Optional[Dict[str, Any]]:
        """Get the full entry including metadata."""
        with self._lock:
            return self._board.get(key)

    def has(self, key: str) -> bool:
        """Check if a key exists."""
        with self._lock:
            return key in self._board

    def get_all_by_prefix(self, prefix: str) -> Dict[str, Any]:
        """Get all entries matching a key prefix."""
        with self._lock:
            result = {}
            for key, entry in self._board.items():
                if key.startswith(prefix):
                    result[key] = entry["value"]
            return result

    def get_keys(self) -> List[str]:
        """Get all keys on the blackboard."""
        with self._lock:
            return list(self._board.keys())

    def get_history(self, last_n: int = 20) -> List[Dict[str, Any]]:
        """Get recent write history."""
        with self._lock:
            return self._history[-last_n:]

    def get_agent_contributions(self, agent: str) -> Dict[str, Any]:
        """Get all entries posted by a specific agent."""
        with self._lock:
            result = {}
            for key, entry in self._board.items():
                if entry.get("posted_by") == agent:
                    result[key] = entry["value"]
            return result

    def clear(self):
        """Clear the blackboard (usually between sessions)."""
        with self._lock:
            self._board.clear()
            self._history.clear()

    def summary(self) -> Dict[str, Any]:
        """Return a summary of the blackboard state."""
        with self._lock:
            agents = set()
            for entry in self._board.values():
                agents.add(entry.get("posted_by", "unknown"))

            return {
                "namespace": self.namespace,
                "total_keys": len(self._board),
                "total_writes": len(self._history),
                "agents": sorted(agents),
                "keys": list(self._board.keys()),
            }
