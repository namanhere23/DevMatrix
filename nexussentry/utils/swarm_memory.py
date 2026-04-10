"""
Swarm Memory
━━━━━━━━━━━━
A thread-safe shared context repository that allows agents
to share memory, learn from previous steps, and understand
the overall state of the swarm execution beyond just their
current task.

Now drives decisions: detects file conflicts, provides
actionable constraints to the Architect, and feeds critic
feedback into future planning.
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

    def has_file_conflict(self, proposed_files: List[str]) -> List[str]:
        """
        Check if any proposed files overlap with already-modified files.
        Returns list of conflicting file paths (empty = no conflicts).
        
        Used by the orchestrator to warn the Architect before planning
        changes to files that were already modified by a previous sub-task.
        """
        with self._lock:
            if not proposed_files or not self._modified_files:
                return []
            return [f for f in proposed_files if f in self._modified_files]

    def record_critic_feedback(self, feedback: str):
        """Record Critic rejections so future agents don't make the same mistake."""
        with self._lock:
            self._critic_feedback_history.append(feedback)

    def get_critic_feedback(self) -> List[str]:
        """Get historical criticism to learn from past mistakes."""
        with self._lock:
            return list(self._critic_feedback_history)

    def get_actionable_constraints(self, proposed_files: Optional[List[str]] = None) -> str:
        """
        Generate structured constraints for the Architect based on memory state.
        
        Unlike summarize_context() which is a prose summary, this returns
        specific warnings and rules that should influence planning decisions.
        
        Args:
            proposed_files: Files the current task plans to modify (for conflict check)
            
        Returns:
            Structured constraint text, or empty string if no constraints apply.
        """
        with self._lock:
            constraints = []

            # Warn about file conflicts
            if proposed_files:
                conflicts = [f for f in proposed_files if f in self._modified_files]
                if conflicts:
                    constraints.append(
                        "⚠️ FILE CONFLICT WARNING: The following files were already "
                        f"modified by previous tasks: {', '.join(conflicts)}. "
                        "Coordinate changes carefully to avoid overwriting previous fixes."
                    )

            # Surface all modified files so Architect avoids blind spots
            if self._modified_files:
                constraints.append(
                    f"ALREADY MODIFIED FILES (do not overwrite without reason): "
                    f"{', '.join(sorted(self._modified_files))}"
                )

            # Surface recurring critic issues as planning rules
            if self._critic_feedback_history:
                constraints.append("LESSONS FROM PREVIOUS REJECTIONS (do NOT repeat these):")
                # Include last 3 to save context window
                for fb in self._critic_feedback_history[-3:]:
                    constraints.append(f"  - {fb}")

            if not constraints:
                return ""

            return "PLANNING CONSTRAINTS:\n" + "\n".join(constraints)

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
                return ""
                
            return "\n".join(parts)
