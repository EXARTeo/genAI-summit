"""Message DTOs: the message as the UI reads it, the create input, and the
finalizing update of an AI placeholder."""

from typing import Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

from core.settings import settings
from schema.attachments import AttachmentIn, AttachmentOut, check_attachment_batch
from schema.base import Senders, UTCDateTime


class TaskNoticeOut(BaseModel):
    """``MessageOut.taskNotice``: what the UI's compact notice row for a
    background task shows.

    The stored record also keeps the notification's ``agent_kwargs`` and
    ``agent_content`` for the agents service; only these four keys ever leave
    the backend.
    """

    model_config = ConfigDict(extra="ignore")

    task_id: str
    name: str
    status: str
    duration_ms: int | None = None


class MessageOut(BaseModel):
    """A message as the UI reads it, attachments included."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: str
    # Branching: edits and retries are siblings under the same parent.
    parentMessageId: str | None = Field(None, validation_alias="parent_message_id")
    content: str | None = None
    sender: Senders
    liked: bool | None = Field(None, validation_alias="liked")
    # The agent that produced an AI message (null on user messages).
    agentSlug: str | None = Field(None, validation_alias="agent_slug")
    agentName: str | None = Field(None, validation_alias="agent_name")
    created_at: UTCDateTime = Field(..., validation_alias="created_at")
    updated_at: UTCDateTime = Field(..., validation_alias="updated_at")
    attachments: list[AttachmentOut] = Field(default_factory=list)
    thinking: list[str] | None = Field(None, validation_alias="reasoning_steps")
    thinkingTime: int | None = Field(None, validation_alias="reasoning_time_seconds")
    error: bool | None = Field(None, validation_alias="is_error")
    errorMessage: str | None = Field(None, validation_alias="error_message")
    # Run lifecycle of an AI message: queued / running / cancelling while live,
    # then completed / cancelled / failed. Null on user messages.
    streamingStatus: str | None = Field(None, validation_alias="streaming_status")
    rawEvents: list[dict] = Field(default_factory=list, validation_alias="raw_events")
    # A background-task notification row: ``kind`` is "task_notification"
    # (sender stays "user": it is the orchestrator's input), rendered as a
    # compact notice, never as the user's words. Both null on every other message.
    kind: Literal["task_notification"] | None = None
    taskNotice: TaskNoticeOut | None = Field(None, validation_alias="task_notice")

    @field_validator("rawEvents", mode="before")
    @classmethod
    def _coerce_raw_events(cls, value: object) -> object:
        return value if value is not None else []

    @field_validator("taskNotice", mode="before")
    @classmethod
    def _notice_or_none(cls, value: object) -> object:
        # An unreadable stored notice must not fail the whole conversation.
        if isinstance(value, TaskNoticeOut):
            return value
        if not isinstance(value, dict) or not value:
            return None
        try:
            return TaskNoticeOut.model_validate(value)
        except ValidationError:
            return None


class MessageIn(BaseModel):
    """Create a message with optional attachments.

    A user message needs content or at least one attachment. An AI message may
    be empty: the UI allocates a placeholder before its run streams.
    """

    parentMessageId: str | None = None
    sender: Senders
    content: str | None = None
    attachments: list[AttachmentIn] = Field(default_factory=list)

    thinking: list[str] | None = None
    thinkingTime: int | None = None
    error: bool | None = None
    errorMessage: str | None = None
    rawEvents: list[dict] = Field(default_factory=list)

    @field_validator("attachments", mode="before")
    @classmethod
    def _limit_batch(cls, value: object) -> object:
        return check_attachment_batch(value)

    @model_validator(mode="after")
    def _require_content_or_attachment(self) -> "MessageIn":
        if self.sender == "user" and not self.content and not self.attachments:
            raise ValueError("Either 'content' or at least one attachment is required.")
        total_limit = settings.attachments.max_total_bytes
        if sum(item.size or 0 for item in self.attachments) > total_limit:
            raise ValueError(
                f"Total attachment payload exceeds the {total_limit // (1024 * 1024)} MB limit."
            )
        return self


class MessageUpdate(BaseModel):
    """Finalize an AI placeholder after streaming. ``content`` is required."""

    content: str | None = None
    thinking: list[str] | None = None
    thinkingTime: int | None = None
    error: bool | None = None
    errorMessage: str | None = None
    rawEvents: list[dict] = Field(default_factory=list)

    @model_validator(mode="after")
    def _require_content(self) -> "MessageUpdate":
        if self.content is None:
            raise ValueError("Message content is required to update the message.")
        return self
