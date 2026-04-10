"""
Swarm Memory
━━━━━━━━━━━━
A thread-safe shared context repository that allows agents
to share memory, learn from previous steps, and understand
the overall state of the swarm execution beyond just their
current task.
"""

import threading
import json
from typing import Any, Dict, List, Optional


class SwarmMemory:
    """Shared context spanning the entire swarm execution session."""

    def __init__(self):
        self._lock = threading.RLock()
        
        # Sub-task history: what was done, by whom, what was the result
        self._history: List[Dict[str, Any]] = []
        
        # Key repository: useful findings (e.g. "auth configuration found at src/auth.py")
        self._facts: Dict[str, str] = {}
        
        # Track which files have been modified across all sub-tasks
        self._modified_files: set = set()
        
        # Keep track of critic feedback to identify recurring issues
        self._critic_feedback_history: List[str] = []

    def record_task_result(self, task_id: int, task_name: str, result: str):
        """Record a successfully completed sub-task."""
        with self._lock:
            self._history.append({
                "task_id": task_id,
                "task_name": task_name,
                "result": result
            })

    def get_task_history(self) -> List[Dict[str, Any]]:
        """Get the timeline of completed tasks."""
        with self._lock:
            return list(self._history)

    def record_fact(self, key: str, value: str):
        """Record an important fact discovered during execution."""
        with self._lock:
            self._facts[key] = value

    def get_facts(self) -> Dict[str, str]:
        """Retrieve all learned facts."""
        with self._lock:
            return dict(self._facts)

    def mark_file_modified(self, filepath: str):
        """Record that a file was changed to prevent conflicting edits later."""
        with self._lock:
            self._modified_files.add(filepath)

    def get_modified_files(self) -> List[str]:
        """Get list of files modified during this session."""
        with self._lock:
            return list(self._modified_files)

    def record_critic_feedback(self, feedback: str):
        """Record Critic rejections so future agents don't make the same mistake."""
        with self._lock:
            self._critic_feedback_history.append(feedback)

    def get_critic_feedback(self) -> List[str]:
        """Get historical criticism to learn from past mistakes."""
        with self._lock:
            return list(self._critic_feedback_history)

    def summarize_context(self) -> str:
        """
        Generate a textual summary of the swarm's memory to inject 
        into an agent's context window.
        """
        with self._lock:
            parts = []
            
            if self._history:
                parts.append("Completed Tasks:")
                for task in self._history:
                    parts.append(f"- Task {task['task_id']} ({task['task_name']}) -> Done")
                    
            if self._modified_files:
                parts.append("\nModified Files in this Session:")
                for f in self._modified_files:
                    parts.append(f"- {f}")
                    
            if self._facts:
                parts.append("\nDiscovered Facts:")
                for k, v in self._facts.items():
                    parts.append(f"- {k}: {v}")
                    
            if self._critic_feedback_history:
                parts.append("\nHistorical Critic Feedback (Do NOT repeat these mistakes):")
                # Only include last 3 to save context window
                for fb in self._critic_feedback_history[-3:]:
                    parts.append(f"- {fb}")
                    
            if not parts:
                return "Swarm Memory is currently empty."
                
            return "\n".join(parts)
