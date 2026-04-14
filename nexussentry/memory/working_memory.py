# nexussentry/memory/working_memory.py
"""
Enhanced Working Memory v3.0
━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Replaces the raw dict-based SwarmMemory with typed, validated state.
Every field is explicit. No more mystery keys buried in a dict.

Extends the existing typed_memory.py with richer models for:
- CriticVerdict tracking
- AgentOutput tracking (with cost/latency)
- Token budget management
- Feedback accumulation for Architect retry loops
"""
import time
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field


class CriticVerdict(BaseModel):
    attempt: int
    score: int
    decision: str               # "approve" | "reject" | "escalate_to_human"
    issues: List[str] = []
    reasoning: str = ""
    panel_breakdown: Dict[str, int] = {}   # optional per-reviewer score details
    timestamp: float = Field(default_factory=time.time)


class AgentOutput(BaseModel):
    agent_name: str
    output: Dict[str, Any]
    latency_ms: float
    provider_used: str
    token_estimate: int = 0
    cost_estimate_usd: float = 0.0
    from_cache: bool = False
    timestamp: float = Field(default_factory=time.time)


class TaskWorkingMemory(BaseModel):
    """
    Complete isolated context for one sub-task execution.
    Thread-safe: each sub-task gets its own instance.
    """
    task_id: str
    session_id: str
    tenant_id: str = "default"

    # Input
    original_goal: str = ""
    sub_task: Dict[str, Any] = {}
    complexity: str = "medium"          # trivial | low | medium | high

    # Execution history
    architect_plans: List[Dict] = []    # ALL attempts preserved
    agent_outputs: List[AgentOutput] = []
    critic_verdicts: List[CriticVerdict] = []

    # Accumulated context (grows with feedback, injected into prompts)
    accumulated_feedback: str = ""
    positive_examples: List[Dict] = []  # Similar successes from EpisodicMemory

    # Budget tracking
    token_budget_total: int = 12000
    tokens_consumed: int = 0
    cost_usd_consumed: float = 0.0

    # Status
    status: str = "pending"             # pending | running | approved | failed | escalated
    final_result: Optional[Dict] = None
    started_at: float = Field(default_factory=time.time)
    completed_at: Optional[float] = None

    def add_plan(self, plan: dict):
        self.architect_plans.append(plan)
        self.accumulated_feedback = ""  # Reset feedback accumulation per new plan

    def add_verdict(self, verdict: dict, attempt: int):
        self.critic_verdicts.append(CriticVerdict(attempt=attempt, **verdict))
        if verdict.get("decision") == "reject":
            self.accumulated_feedback += f"\nAttempt {attempt} failed (score {verdict.get('score', 0)}/100):\n"
            self.accumulated_feedback += "\n".join(f"  - {i}" for i in verdict.get("issues", []))

    def get_feedback_for_architect(self) -> str:
        """Returns the feedback string to inject into the next Architect call."""
        return self.accumulated_feedback.strip()

    def mark_complete(self, result: dict, status: str):
        self.final_result = result
        self.status = status
        self.completed_at = time.time()

    @property
    def attempt_count(self) -> int:
        return len(self.critic_verdicts)

    @property
    def last_score(self) -> int:
        return self.critic_verdicts[-1].score if self.critic_verdicts else 0
