"""Background sub-agent task DTOs: the shapes the agents service, the backend
and the UI agree on.

``TaskOut`` and ``OutboxItem`` are written by the agents service (Redis
streams, internal HTTP) and validated here before anything is stored or
forwarded; ``TaskOut`` is also what the backend serves to the browser from its
``conversation_tasks`` mirror. Field names are snake_case on purpose: they are
the cross-service contract (``docs/agents-contract.md`` § Async sub-agents).

``client_id`` (the owning browser) is read from the agents service but never
serialised back out: it is a capability, and the browser already knows its own.

Every free-text field coming from the agents service is clipped rather than
rejected: a too-long description must not turn a status update into a poison
entry that blocks the stream.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from schema.base import UTCDateTime
from schema.inference import InferenceRunResumeIn

#: The task lifecycle. The last three are the settled statuses.
AsyncTaskStatus = Literal[
    "pending", "running", "waiting_children", "waiting", "success", "error", "cancelled"
]
#: The events of the ``tasks:status`` stream and of the conversation channel.
TaskStatusEvent = Literal["TASK_STARTED", "TASK_STATUS", "TASK_SETTLED"]

#: Clip limits for the agents service's free text (characters).
_NAME_MAX = 200
_PATH_MAX = 1000
_DESCRIPTION_MAX = 10_000
_PREVIEW_MAX = 2000
_ERROR_MAX = 2000
_ID_MAX = 200


def _clip(value: Any, limit: int) -> Any:
    """Clip a string to ``limit`` characters; anything else passes unchanged."""
    return value[:limit] if isinstance(value, str) and len(value) > limit else value


class TaskUsage(BaseModel):
    """What a task's runs spent, summed by the agents service (0 when not reported)."""

    model_config = ConfigDict(extra="ignore")

    input_tokens: int = Field(0, ge=0)
    output_tokens: int = Field(0, ge=0)
    cached_input_tokens: int = Field(0, ge=0)
    reasoning_tokens: int = Field(0, ge=0)
    calls: int = Field(0, ge=0)
    model_latency_ms: int = Field(0, ge=0)


class TaskOut(BaseModel):
    """One background sub-agent task."""

    model_config = ConfigDict(from_attributes=True, extra="ignore")

    task_id: str = Field(..., min_length=1, max_length=_ID_MAX)
    conversation_id: str = Field(..., min_length=1, max_length=_ID_MAX)
    client_id: str = Field(..., min_length=1, max_length=_ID_MAX, exclude=True)
    parent_task_id: str | None = Field(None, max_length=_ID_MAX)
    root_run_id: str | None = Field(None, max_length=_ID_MAX)
    branch_thread_id: str | None = Field(None, max_length=_ID_MAX)
    spawned_by_message_id: str | None = Field(None, max_length=_ID_MAX)
    depth: int = Field(1, ge=1, le=10)
    name: str = Field(..., min_length=1)
    subagent_path: str | None = None
    description: str | None = None
    model: str | None = None
    status: AsyncTaskStatus
    result_preview: str | None = None
    error: str | None = None
    usage: TaskUsage = Field(default_factory=TaskUsage)
    started_at: UTCDateTime | None = None
    settled_at: UTCDateTime | None = None

    @field_validator("name", "model", mode="before")
    @classmethod
    def _clip_name(cls, value: Any) -> Any:
        return _clip(value, _NAME_MAX)

    @field_validator("subagent_path", mode="before")
    @classmethod
    def _clip_path(cls, value: Any) -> Any:
        return _clip(value, _PATH_MAX)

    @field_validator("description", mode="before")
    @classmethod
    def _clip_description(cls, value: Any) -> Any:
        return _clip(value, _DESCRIPTION_MAX)

    @field_validator("result_preview", mode="before")
    @classmethod
    def _clip_preview(cls, value: Any) -> Any:
        return _clip(value, _PREVIEW_MAX)

    @field_validator("error", mode="before")
    @classmethod
    def _clip_error(cls, value: Any) -> Any:
        return _clip(value, _ERROR_MAX)

    @field_validator("usage", mode="before")
    @classmethod
    def _usage_or_empty(cls, value: Any) -> Any:
        return value if isinstance(value, dict | TaskUsage) else {}

    @property
    def settled(self) -> bool:
        return self.status in ("success", "error", "cancelled")


class TaskStatusEntry(BaseModel):
    """One ``tasks:status`` stream entry: an event and the task as it now is."""

    event: TaskStatusEvent
    task: TaskOut


class TaskNotification(BaseModel):
    """The notification HumanMessage the agents service built for a settled task."""

    model_config = ConfigDict(extra="ignore")

    content: list[dict[str, Any]] | str = Field(default_factory=list)
    additional_kwargs: dict[str, Any] = Field(default_factory=dict)


class OutboxItem(BaseModel):
    """One ``tasks:outbox`` entry / ``GET /tasks/unnotified`` item.

    Written when a depth-1 task's whole subtree has settled: the doorbell that
    wakes the orchestrator. The durable truth is the agents service's
    ``parent_notified_at``. ``interactive`` is accepted but unused: this
    product has no scheduled (headless) runs.
    """

    model_config = ConfigDict(extra="ignore")

    task_id: str = Field(..., min_length=1, max_length=_ID_MAX)
    client_id: str = Field(..., min_length=1, max_length=_ID_MAX, exclude=True)
    conversation_id: str = Field(..., min_length=1, max_length=_ID_MAX)
    branch_thread_id: str = Field(..., min_length=1, max_length=_ID_MAX)
    root_run_id: str | None = Field(None, max_length=_ID_MAX)
    agent_slug: str | None = Field(None, max_length=_NAME_MAX)
    interactive: bool = True
    status: Literal["success", "error", "cancelled"]
    cancelled_by_user: bool = False
    notification: TaskNotification = Field(default_factory=TaskNotification)

    def notification_text(self) -> str:
        """The notification's text, as the notice row's content."""
        content = self.notification.content
        if isinstance(content, str):
            return content
        parts = [
            block["text"]
            for block in content
            if isinstance(block, dict)
            and block.get("type") == "text"
            and isinstance(block.get("text"), str)
        ]
        return "\n\n".join(parts)


class TaskResumeIn(InferenceRunResumeIn):
    """``POST /v1/tasks/{task_id}/resume``: an approval decision for a
    ``waiting`` task, the same body as a run's resume. ``interruptId`` is
    required: a task's pause is answered interrupt by interrupt."""

    @model_validator(mode="after")
    def _require_interrupt_id(self) -> TaskResumeIn:
        if not self.interruptId:
            raise ValueError("interruptId is required to answer a task's approval.")
        return self


class ActiveConversationsOut(BaseModel):
    """``GET /v1/tasks/active-conversations``: the caller's conversations whose
    background tasks are still working (the sidebar's spinner poll)."""

    conversationIds: list[str] = Field(default_factory=list)


class TaskFrame(BaseModel):
    """Conversation channel: a task's status change, as the tree should show it."""

    type: Literal["task"] = "task"
    event: TaskStatusEvent
    task: TaskOut
