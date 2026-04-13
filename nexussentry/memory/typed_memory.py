# nexussentry/memory/typed_memory.py
"""
Typed Working Memory — v3.0
━━━━━━━━━━━━━━━━━━━━━━━━━━
Replaces arbitrary dict-based memory with Pydantic models.
Each sub-task gets its own isolated working memory namespace,
preventing cross-task contamination.
"""

from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any


class TaskWorkingMemory(BaseModel):
    """Structured working memory for a single sub-task execution."""

    task_id: int = 0
    goal_summary: str = ""
    sub_task: Dict[str, Any] = Field(default_factory=dict)

    # All attempts, not just latest — enables convergence analysis
    architect_plans: List[Dict[str, Any]] = Field(default_factory=list)

    # Full history for convergence analysis
    critic_verdicts: List[Dict[str, Any]] = Field(default_factory=list)

    # Real execution results
    tool_outputs: List[Dict[str, Any]] = Field(default_factory=list)

    # Growing context string for LLM prompts
    accumulated_context: str = ""

    # Track remaining context window budget
    token_budget_remaining: int = 8000

    # Attempt counter
    current_attempt: int = 0

    # Files this task has touched
    files_modified: List[str] = Field(default_factory=list)

    def record_plan(self, plan: Dict[str, Any]):
        """Record an Architect plan attempt."""
        self.architect_plans.append(plan)
        self.current_attempt += 1

    def record_verdict(self, verdict: Dict[str, Any]):
        """Record a Critic verdict."""
        self.critic_verdicts.append(verdict)

    def record_output(self, output: Dict[str, Any]):
        """Record a tool/builder output."""
        self.tool_outputs.append(output)

    def get_latest_plan(self) -> Optional[Dict[str, Any]]:
        """Get the most recent Architect plan."""
        return self.architect_plans[-1] if self.architect_plans else None

    def get_latest_verdict(self) -> Optional[Dict[str, Any]]:
        """Get the most recent Critic verdict."""
        return self.critic_verdicts[-1] if self.critic_verdicts else None

    def is_converging(self) -> bool:
        """
        Check if scores are improving across attempts.
        Returns True if the last 2 scores show improvement.
        """
        if len(self.critic_verdicts) < 2:
            return True  # Not enough data to judge

        scores = [v.get("score", 0) for v in self.critic_verdicts[-3:]]
        if len(scores) >= 2:
            return scores[-1] >= scores[-2]
        return True

    def convergence_summary(self) -> str:
        """Return a human-readable convergence summary."""
        if not self.critic_verdicts:
            return "No verdicts yet"

        scores = [v.get("score", 0) for v in self.critic_verdicts]
        trend = "↑ improving" if self.is_converging() else "↓ degrading"
        return f"Attempts: {len(scores)}, Scores: {scores}, Trend: {trend}"


class SwarmSessionMemory(BaseModel):
    """Top-level memory container for an entire swarm session."""

    session_id: str = ""
    goal: str = ""

    # Per-task working memories
    task_memories: Dict[int, TaskWorkingMemory] = Field(default_factory=dict)

    # Global facts discovered during execution
    global_facts: Dict[str, str] = Field(default_factory=dict)

    # Files modified across all tasks
    all_modified_files: List[str] = Field(default_factory=list)

    def get_or_create_task_memory(self, task_id: int, sub_task: Dict[str, Any] = None) -> TaskWorkingMemory:
        """Get or create a working memory for a specific task."""
        if task_id not in self.task_memories:
            self.task_memories[task_id] = TaskWorkingMemory(
                task_id=task_id,
                goal_summary=self.goal,
                sub_task=sub_task or {},
            )
        return self.task_memories[task_id]

    def record_global_fact(self, key: str, value: str):
        """Record a fact that applies across all tasks."""
        self.global_facts[key] = value

    def get_completed_task_summaries(self) -> List[str]:
        """Get summaries of all completed tasks for context injection."""
        summaries = []
        for tid, mem in self.task_memories.items():
            latest = mem.get_latest_verdict()
            if latest and latest.get("decision") == "approve":
                summaries.append(
                    f"Task {tid}: {mem.sub_task.get('task', 'Unknown')} — "
                    f"Score: {latest.get('score', '?')}/100"
                )
        return summaries
