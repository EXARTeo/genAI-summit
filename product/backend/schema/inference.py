"""Run DTOs: the start request and its answers, the run view, HITL resume,
the composer queue and the conversation-channel frames.

A *run* is the assistant message being produced: its id is the message id and
its lifecycle lives in the message's ``streaming_*`` columns. There is no login,
so nothing here names a user; ownership is the conversation's ``client_id``.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from schema.base import UTCDateTime
from schema.conversations import ConversationSummary
from schema.messages import MessageIn, MessageOut

#: An agent slug as the agents service names agents; it becomes one URL path
#: segment, so it starts with a letter or digit and never contains a slash.
AGENT_SLUG_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9_-]{0,99}$"


class InferenceStartPayload(BaseModel):
    """``POST /v1/inference/runs/start``.

    * ``new`` — a new conversation with ``agentSlug`` (+ optional ``agentName``,
      ``title``) and its first ``message``;
    * ``send`` — ``message`` continues ``conversationId`` under
      ``parentMessageId``; ``agentSlug`` switches the agent for this turn
      (default: the conversation's);
    * ``edit`` — ``message`` replaces the user message ``targetMessageId`` as
      a sibling branch;
    * ``retry`` — a new answer to the user message above the AI message
      ``targetMessageId`` (optionally pinned to the UI's ``messagePath``).

    The agents service validates the slug; the backend has no agent catalog.
    """

    mode: Literal["new", "send", "edit", "retry"]
    agentSlug: str | None = Field(default=None, pattern=AGENT_SLUG_PATTERN)
    agentName: str | None = Field(default=None, max_length=200)
    title: str | None = Field(default=None, max_length=300)
    conversationId: str | None = None
    parentMessageId: str | None = None
    targetMessageId: str | None = None
    messagePath: list[str] | None = None
    message: MessageIn | None = None
    # On a `send` to a conversation that already has an active run, hold this
    # message as the conversation's one queued message (202) instead of
    # refusing it (409). It is sent when the run ends.
    queue_if_busy: bool = False


class InferenceRunOut(BaseModel):
    """A run as the UI's run manager sees it. ``id`` and ``assistantMessageId``
    are both the assistant message id."""

    model_config = ConfigDict(populate_by_name=True)

    id: str
    conversationId: str
    assistantMessageId: str
    parentMessageId: str | None = None
    status: str
    agentSlug: str | None = None
    agentName: str | None = None
    messagePath: list[str] = Field(default_factory=list)
    content: str | None = None
    thinking: list[str] | None = None
    rawEvents: list[dict] = Field(default_factory=list)
    errorMessage: str | None = None
    startedAt: UTCDateTime
    completedAt: UTCDateTime | None = None
    cancelRequestedAt: UTCDateTime | None = None
    updatedAt: UTCDateTime

    @field_validator("messagePath", "rawEvents", mode="before")
    @classmethod
    def _coerce_json_lists(cls, value: Any) -> list:
        return value if isinstance(value, list) else []


class InferenceStartResponse(BaseModel):
    """201: the run is created and launched.

    ``message`` is the assistant placeholder the run fills; ``userMessage`` the
    user message this start created (None for a retry, which creates none).
    """

    summary: ConversationSummary
    run: InferenceRunOut
    message: MessageOut
    userMessage: MessageOut | None = None


class ResumeActionDecisionIn(BaseModel):
    """One approve/reject decision for a single gated tool call of a batched
    interrupt, index-aligned to the interrupt's ``action_requests``."""

    decision: Literal["approve", "reject"]
    reason: str | None = Field(default=None, max_length=4000)


class InferenceRunResumeIn(BaseModel):
    """``POST /v1/inference/runs/{run_id}/resume``: a HITL decision.

    ``interruptId`` is the interrupt the decision answers (from its
    ``HITL_INTERRUPT`` event); without it the first undecided pending interrupt
    is answered. ``decisions`` is the per-action list of a batched interrupt;
    ``value`` carries structured answers (an ``ask_user`` reply's ``answers``).
    """

    model_config = ConfigDict(populate_by_name=True)

    interruptId: str | None = Field(default=None, max_length=128)
    decision: Literal["approve", "reject"]
    reason: str | None = Field(default=None, max_length=4000)
    value: Any | None = None
    decisions: list[ResumeActionDecisionIn] | None = Field(default=None, max_length=64)


class QueuedMessageOut(BaseModel):
    """The conversation's one queued composer message (text only)."""

    model_config = ConfigDict(extra="ignore")

    content: str | None = None
    agent_slug: str
    agent_name: str | None = None
    queued_at: UTCDateTime


class QueuedStartResponse(BaseModel):
    """202: the conversation was busy, so the message is held and sent when
    the active run ends."""

    queued: Literal[True] = True
    queued_message: QueuedMessageOut


class RunStartedFrame(BaseModel):
    """Conversation channel: a run the browser did not start itself (the
    queued message being sent). The UI attaches to it over the run socket."""

    type: Literal["run_started"] = "run_started"
    run: InferenceRunOut
    from_queue: bool = False


class QueueFrame(BaseModel):
    """Conversation channel: the composer queue's state (None = empty)."""

    type: Literal["queue"] = "queue"
    queued_message: QueuedMessageOut | None = None


def queued_message_from_column(value: Any) -> QueuedMessageOut | None:
    """``conversations.queued_message`` as its wire shape, or None when empty/invalid."""
    if not isinstance(value, dict):
        return None
    try:
        return QueuedMessageOut.model_validate(value)
    except ValueError:
        return None
