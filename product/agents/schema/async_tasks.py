"""The internal task API for the backend — ``TaskOut``, ``OutboxItem`` and the request bodies.

These are the cross-service contract (``docs/agents-contract.md``, "Async
sub-agents"): the backend validates the same shapes. ``client_id`` — the
backend's anonymous ``X-Client-Id`` — is in every request so each call is
checked against the task row's owner (a mismatch is a 404, never a hint that
the task exists). It is a capability: never logged or traced raw.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

TaskStatus = Literal[
    "pending", "running", "waiting_children", "waiting", "success", "error", "cancelled"
]
TaskStatusEvent = Literal["TASK_STARTED", "TASK_STATUS", "TASK_SETTLED"]

_ID = Field(min_length=1, max_length=256)


class TaskUsage(BaseModel):
    """Summed usage of a task's runs. Every key is optional on the wire."""

    input_tokens: int = 0
    output_tokens: int = 0
    cached_input_tokens: int = 0
    reasoning_tokens: int = 0
    calls: int = 0
    model_latency_ms: int = 0


class TaskOut(BaseModel):
    """One task."""

    task_id: str
    conversation_id: str
    client_id: str
    parent_task_id: str | None = None
    root_run_id: str
    branch_thread_id: str
    spawned_by_message_id: str
    depth: int
    name: str
    subagent_path: str
    description: str | None = None
    model: str | None = None
    status: TaskStatus
    result_preview: str | None = Field(default=None, max_length=2000)
    error: str | None = None
    usage: TaskUsage = Field(default_factory=TaskUsage)
    started_at: datetime
    settled_at: datetime | None = None


class TaskNotification(BaseModel):
    """The notification message's content blocks and metadata (see
    ``harness.async_tasks.notification``)."""

    content: list[dict[str, Any]] = Field(default_factory=list)
    additional_kwargs: dict[str, Any] = Field(default_factory=dict)


class OutboxItem(BaseModel):
    """A settled depth-1 task the orchestrator has not been told about."""

    task_id: str
    client_id: str
    conversation_id: str
    branch_thread_id: str
    root_run_id: str
    agent_slug: str
    interactive: bool = True
    status: Literal["success", "error", "cancelled"]
    cancelled_by_user: bool = False
    notification: TaskNotification


class TaskClientIn(BaseModel):
    """A body carrying only the acting client (``/notified``)."""

    client_id: str = _ID


class TaskCancelIn(BaseModel):
    """``POST /tasks/{task_id}/cancel``: the user stopped the task."""

    client_id: str = _ID
    reason: Literal["user"] = "user"


class TaskResumeDecision(BaseModel):
    """One interrupt's answer — the item shape of ``/agents/{slug}/resume``."""

    decision: Literal["approve", "reject"]
    reason: str | None = Field(default=None, max_length=4000)
    value: Any | None = None
    decisions: list[dict[str, Any]] | None = Field(default=None, max_length=64)


class TaskResumeIn(BaseModel):
    """``POST /tasks/{task_id}/resume``: answers keyed by interrupt id."""

    client_id: str = _ID
    decisions: dict[str, TaskResumeDecision] = Field(min_length=1, max_length=64)


class TaskCancelScopeIn(BaseModel):
    """``POST /tasks/cancel-scope``: every task of a client, a conversation or a root run."""

    client_id: str = _ID
    conversation_id: str | None = Field(default=None, max_length=256)
    root_run_id: str | None = Field(default=None, max_length=256)


class TaskCancelScopeOut(BaseModel):
    """How many tasks a scope cancel stopped (descendants included)."""

    cancelled: int


__all__ = [
    "OutboxItem",
    "TaskCancelIn",
    "TaskCancelScopeIn",
    "TaskCancelScopeOut",
    "TaskNotification",
    "TaskOut",
    "TaskResumeDecision",
    "TaskResumeIn",
    "TaskStatus",
    "TaskStatusEvent",
    "TaskClientIn",
    "TaskUsage",
]
