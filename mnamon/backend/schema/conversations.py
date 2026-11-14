"""Conversation DTOs: create / fork / rename inputs, the sidebar summary and the
full detail (messages included)."""

from pydantic import BaseModel, ConfigDict, Field, computed_field, model_validator

from schema.base import UTCDateTime
from schema.messages import MessageIn, MessageOut

MAX_TITLE_LENGTH = 200

#: An agent slug from the agents service: letters, digits, ``.``, ``_``, ``-``.
AGENT_SLUG_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$"


class ConversationSummary(BaseModel):
    """A conversation as a sidebar row: no messages, no blob bytes."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: str
    agentSlug: str = Field(..., validation_alias="agent_slug")
    agentName: str | None = Field(None, validation_alias="agent_name")
    forkedParentId: str | None = Field(None, validation_alias="forked_parent_id")
    forkedMessageId: str | None = Field(None, validation_alias="forked_message_id")
    title: str | None = Field(None, validation_alias="title")
    isArchived: bool = Field(False, validation_alias="is_archived")
    archivedAt: UTCDateTime | None = Field(None, validation_alias="archived_at")
    isPinned: bool = Field(False, validation_alias="is_pinned")
    pinnedAt: UTCDateTime | None = Field(None, validation_alias="pinned_at")
    # The AI message being streamed, while a run is active.
    activeRunId: str | None = Field(None, validation_alias="active_assistant_message_id")
    # Background sub-agent tasks still working: the row spins like a streaming
    # answer even after the orchestrator's own run ended.
    hasActiveTasks: bool = Field(False, validation_alias="has_active_tasks")
    lastMessage: str | None = Field(None, validation_alias="last_message_preview")
    # The audited system / audit this chat is about (optional).
    systemId: str | None = Field(None, validation_alias="system_id")
    auditId: str | None = Field(None, validation_alias="audit_id")
    created_at: UTCDateTime = Field(..., validation_alias="created_at")
    updated_at: UTCDateTime = Field(..., validation_alias="updated_at")

    @computed_field
    @property
    def isStreaming(self) -> bool:
        return bool(self.activeRunId)


class ConversationDetail(ConversationSummary):
    """A conversation with all its messages (every branch); images inline."""

    # The answer that started the newest still-working task: opening the
    # conversation lands on that answer's branch.
    activeTaskMessageId: str | None = Field(None, validation_alias="active_task_message_id")
    messages: list[MessageOut] = Field(default_factory=list)


class ConversationIn(BaseModel):
    """Create a conversation with an agent and persist its first message."""

    agentSlug: str = Field(..., pattern=AGENT_SLUG_PATTERN, description="Agent slug")
    agentName: str | None = Field(None, max_length=200, description="Agent display name")
    title: str | None = Field(None, description="Optional custom title")
    systemId: str | None = Field(None, description="The audited system this chat is about")
    auditId: str | None = Field(None, description="The audit this chat is about")
    firstMessage: MessageIn


class ConversationForkIn(BaseModel):
    """Fork the branch that ends at the given AI message."""

    messageId: str


class CreateConversationResponse(BaseModel):
    """The new conversation: its full detail and its sidebar summary."""

    detail: ConversationDetail
    summary: ConversationSummary


class UpdateConversationResponse(BaseModel):
    """A created or updated message with the conversation's refreshed summary."""

    message: MessageOut
    summary: ConversationSummary


class ConversationTitleUpdate(BaseModel):
    """Rename a conversation. Trimmed; blank is refused; long titles are cut."""

    title: str

    @model_validator(mode="after")
    def _normalize_and_validate(self) -> "ConversationTitleUpdate":
        resolved = (self.title or "").strip()
        if not resolved:
            raise ValueError("Title cannot be empty.")
        self.title = resolved[:MAX_TITLE_LENGTH].rstrip()
        return self
