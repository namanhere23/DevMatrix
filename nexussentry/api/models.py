"""API contracts for the NexusSentry backend."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class RunStatus(str, Enum):
    queued = "queued"
    guarding = "guarding"
    decomposing = "decomposing"
    executing = "executing"
    awaiting_decision = "awaiting_decision"
    completed = "completed"
    stopped = "stopped"
    failed = "failed"


class DecisionAction(str, Enum):
    retry = "retry"
    accept_current = "accept_current"
    stop = "stop"


class OrchestratorEngine(str, Enum):
    legacy = "legacy"
    langgraph = "langgraph"


class ErrorResponse(BaseModel):
    error: dict[str, Any]


class ApiEvent(BaseModel):
    cursor: int
    created_at: datetime
    event_type: str
    message: str
    agent: str | None = None
    action: str | None = None
    data: dict[str, Any] = Field(default_factory=dict)


class ArtifactRecord(BaseModel):
    id: str
    name: str
    path: str
    size_bytes: int
    media_type: str
    download_url: str


class DecisionRequestSnapshot(BaseModel):
    task_id: int | None = None
    task: str | None = None
    attempt: int | None = None
    requested_at: datetime
    deadline_at: datetime
    reason: str
    critic_score: int | None = None
    issues_found: list[str] = Field(default_factory=list)
    suggestions: list[str] = Field(default_factory=list)


class TaskResult(BaseModel):
    task_id: int
    task: str
    status: str
    attempts: int
    score: int | None = None
    execution_mode: str | None = None
    saved_to: str | None = None


class RunResponse(BaseModel):
    id: str
    goal: str
    engine: OrchestratorEngine
    status: RunStatus
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None = None
    current_agent: str | None = None
    current_task: str | None = None
    tasks_total: int = 0
    tasks_completed: int = 0
    trace_log: str | None = None
    task_results: list[TaskResult] = Field(default_factory=list)
    decision_request: DecisionRequestSnapshot | None = None
    artifacts: list[ArtifactRecord] = Field(default_factory=list)
    output: dict[str, Any] = Field(default_factory=dict)
    error: dict[str, Any] | None = None


class CreateRunRequest(BaseModel):
    goal: str = Field(min_length=1, max_length=4000)
    engine: OrchestratorEngine | None = None


class DecisionRequest(BaseModel):
    action: DecisionAction
    reason: str | None = Field(default=None, max_length=1000)
    actor: str | None = Field(default="ui", max_length=120)


class EventsResponse(BaseModel):
    run_id: str
    cursor: int
    next_cursor: int
    total: int
    events: list[ApiEvent]


class ArtifactsResponse(BaseModel):
    run_id: str
    artifacts: list[ArtifactRecord]


class HealthResponse(BaseModel):
    status: str
    checked_at: datetime
    details: dict[str, Any] = Field(default_factory=dict)
