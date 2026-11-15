"""ORM tables (SQLAlchemy) for the backend database.

What this product stores: conversations (archive, pin, fork, title, queued message), messages
(branches via parent ids, AG-UI run state, checkpoint lineage, background-task
notices), attachments with their blobs, and the mirror of the agents service's
background sub-agent tasks (``conversation_tasks``).

There are no users and no login. ``conversations.client_id`` is the anonymous
browser id from ``X-Client-Id`` (see core/security/client.py); every query is
scoped by it. Agents live in the agents service, so a conversation names its
agent by slug instead of a foreign key.

``Base`` and ``gen_uuid`` come from ``core.database.engine``; everything is
re-exported from ``core.database``.
"""

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    DDL,
    JSON,
    Boolean,
    Column,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    and_,
    case,
    event,
    exists,
    select,
    text,
)
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import column_property, relationship
from sqlalchemy.sql import func

from core.database.engine import Base, gen_uuid


def _nullable_jsonb() -> JSON:
    """JSONB on Postgres (plain JSON on the test sqlite) where Python ``None``
    is SQL NULL, not the JSON value ``null``, so ``IS NULL`` means "unset"."""
    return JSON(none_as_null=True).with_variant(JSONB(none_as_null=True), "postgresql")


class ConversationTable(Base):
    __tablename__ = "conversations"
    __table_args__ = (
        # The sidebar: one client's conversations, most recent first.
        Index("ix_conversations_client_last_message", "client_id", "last_message_at"),
        # The Pinned section: one client's pins, newest pin first. Partial,
        # because pins are a handful of rows per client.
        Index(
            "ix_conversations_client_pinned",
            "client_id",
            "pinned_at",
            postgresql_where=text("is_pinned"),
            sqlite_where=text("is_pinned"),
        ),
    )

    id = Column(String, primary_key=True, default=gen_uuid)
    # The anonymous browser id that owns this conversation (not an account).
    client_id = Column(String, nullable=False, index=True)
    # The agent in the agents service this conversation talks to.
    agent_slug = Column(String, nullable=False)
    agent_name = Column(String, nullable=True)

    forked_parent_id = Column(
        String, ForeignKey("conversations.id", ondelete="SET NULL"), nullable=True, index=True
    )
    # conversations <-> messages reference each other: use_alter adds these two
    # foreign keys after both tables exist (same names as the baseline migration).
    forked_message_id = Column(
        String,
        ForeignKey(
            "messages.id",
            ondelete="SET NULL",
            use_alter=True,
            name="conversations_forked_message_id_fkey",
        ),
        nullable=True,
        index=True,
    )

    title = Column(String, nullable=True)
    is_archived = Column(Boolean, nullable=False, default=False, server_default="false")
    archived_at = Column(DateTime, nullable=True)
    # Pinned to the top of the sidebar. Archiving clears it; a fork starts
    # unpinned. The Python default makes every ORM insert write a real boolean
    # (sqlite would otherwise store the string 'false', which reads truthy).
    is_pinned = Column(Boolean, nullable=False, default=False, server_default="false")
    pinned_at = Column(DateTime, nullable=True)

    # The assistant message currently being streamed. Set when an AI
    # placeholder is created; cleared when the run reaches a terminal state.
    active_assistant_message_id = Column(
        String,
        ForeignKey(
            "messages.id",
            ondelete="SET NULL",
            use_alter=True,
            name="conversations_active_assistant_message_id_fkey",
        ),
        nullable=True,
        index=True,
    )

    # For fast conversation-list rendering.
    last_message_preview = Column(String, server_default="", nullable=True)
    last_message_at = Column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )

    # The composer's one queued message: a user message sent while a run was
    # active, sent as a normal turn when that run ends. One slot (a second
    # send replaces it). Text only, never attachment bytes. NULL = nothing queued.
    queued_message = Column(_nullable_jsonb(), nullable=True)

    # Optional subject of the chat: an audited system and/or one of its audits.
    # Systems are not owned by a client (see SystemTable), the conversation is.
    system_id = Column(
        String, ForeignKey("systems.id", ondelete="SET NULL"), nullable=True, index=True
    )
    audit_id = Column(
        String, ForeignKey("audits.id", ondelete="SET NULL"), nullable=True, index=True
    )

    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)

    messages = relationship(
        "MessageTable",
        back_populates="conversation",
        cascade="all, delete-orphan",
        passive_deletes=True,
        foreign_keys="MessageTable.conversation_id",
        # A run writes the user message and its AI placeholder in one
        # transaction, so both share created_at. The role breaks the tie (the
        # question precedes its answer) and the id makes the order total.
        order_by=lambda: (
            MessageTable.created_at.asc(),
            case((MessageTable.sender == "user", 0), else_=1).asc(),
            MessageTable.id.asc(),
        ),
    )
    active_assistant_message = relationship(
        "MessageTable",
        foreign_keys=[active_assistant_message_id],
        post_update=True,
    )


MessageSenderEnum = Enum("user", "ai", name="message_sender_enum")
# What kind of row a message is, beyond its sender. NULL for every ordinary
# message. ``task_notification`` is the wake-up input row: sender stays "user"
# because the orchestrator receives it as a HumanMessage, but the UI renders it
# as a compact notice, never as the user's words.
MessageKindEnum = Enum("task_notification", name="message_kind_enum")


class MessageTable(Base):
    __tablename__ = "messages"
    __table_args__ = (
        # At most one assistant message per conversation can be streaming.
        Index(
            "uq_messages_one_active_stream_per_conversation",
            "conversation_id",
            unique=True,
            postgresql_where=text("streaming_status IN ('queued', 'running', 'cancelling')"),
            sqlite_where=text("streaming_status IN ('queued', 'running', 'cancelling')"),
        ),
        Index("ix_messages_conversation_id_id", "conversation_id", "id"),
        Index(
            "ix_messages_streaming_status",
            "streaming_status",
            postgresql_where=text("streaming_status IS NOT NULL"),
            sqlite_where=text("streaming_status IS NOT NULL"),
        ),
    )

    id = Column(String, primary_key=True, default=gen_uuid)
    conversation_id = Column(
        String, ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Branching: edits and retries create siblings under the same parent.
    parent_message_id = Column(
        String, ForeignKey("messages.id", ondelete="SET NULL"), nullable=True, index=True
    )

    sender = Column(MessageSenderEnum, nullable=False)
    content = Column(Text, nullable=True)  # NULL for pure file messages

    # User feedback: None (none), True (like), False (dislike).
    liked = Column(Boolean, nullable=True)

    # Agent "thinking" UX.
    reasoning_steps = Column(JSON, nullable=True)  # array[str]
    reasoning_time_seconds = Column(Integer, nullable=True)

    is_error = Column(Boolean, nullable=False, default=False, server_default="false")
    error_message = Column(Text, nullable=True)

    # Durable checkpointer lineage (the agents service's checkpointer).
    # checkpoint_thread_id: the per-branch thread this run resumed or created.
    # checkpoint_id: the checkpoint head this run committed (from the AG-UI
    # CHECKPOINT_COMMITTED event); the next turn resumes from it.
    checkpoint_thread_id = Column(String, nullable=True, index=True)
    checkpoint_id = Column(String, nullable=True)

    # The run's AG-UI events, in order, for replay after the live stream expires.
    raw_events = Column(JSON, nullable=True)

    # A background-task notification row. ``kind`` is NULL on every ordinary
    # message; ``task_notice`` is set only with it: {"task_id", "name",
    # "status", "duration_ms"} for the UI, plus "agent_kwargs" and
    # "agent_content", the notification's ``additional_kwargs`` and content
    # blocks the agents service needs to rebuild the exact HumanMessage it
    # wrote (never sent to the browser).
    kind = Column(MessageKindEnum, nullable=True)
    task_notice = Column(_nullable_jsonb(), nullable=True)

    # Which agent produced this AI message (NULL on user messages).
    agent_slug = Column(String, nullable=True)
    agent_name = Column(String, nullable=True)

    # Inference-run state, set only on AI messages produced by a run.
    # queued / running / cancelling / completed / cancelled / failed
    streaming_status = Column(String, nullable=True)
    # Branch context: the message ids the agent saw as history.
    streaming_message_path = Column(JSON, nullable=True)
    streaming_started_at = Column(DateTime, nullable=True)
    streaming_completed_at = Column(DateTime, nullable=True)
    streaming_cancel_requested_at = Column(DateTime, nullable=True)

    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)

    conversation = relationship(
        "ConversationTable", back_populates="messages", foreign_keys=[conversation_id]
    )
    attachments = relationship(
        "AttachmentTable",
        back_populates="message",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="AttachmentTable.created_at.asc()",
    )


#: The statuses of a task that has settled (its subtree included).
TASK_SETTLED_STATUSES = ("success", "error", "cancelled")


class ConversationTaskTable(Base):
    """The UI-facing mirror of one background sub-agent task.

    The agents service owns and runs tasks; it announces every status change
    on the Redis stream ``tasks:status``, which the backend consumes into this
    table (utils/async_tasks.py). The conversation's task tree, its reload and
    its drill-down read the mirror, so the UI never needs the agents service
    to draw it. The columns are the ``TaskOut`` fields plus:

    * ``raw_events`` — the task's AG-UI events, coalesced like
      ``messages.raw_events``, captured from ``task:{id}:events`` when the task
      settles, so a settled node still opens after the Redis stream expires;
    * ``notified_at`` — when the backend handled the task's wake-up (woke the
      orchestrator, or deliberately skipped it). Bookkeeping only: the durable
      truth is the agents service's ``parent_notified_at``.

    ``client_id`` is the owning browser, checked against the conversation's
    when the row is written. ``parent_task_id``, ``root_run_id`` and
    ``spawned_by_message_id`` are plain strings, not foreign keys: entries can
    arrive out of order, and a task row must never block a message or a parent
    from being written first. Cascades with its conversation.
    """

    __tablename__ = "conversation_tasks"

    task_id = Column(String, primary_key=True)
    conversation_id = Column(
        String, ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    client_id = Column(String, nullable=False, index=True)
    parent_task_id = Column(String, nullable=True, index=True)
    root_run_id = Column(String, nullable=True)
    branch_thread_id = Column(String, nullable=True)
    spawned_by_message_id = Column(String, nullable=True)
    depth = Column(Integer, nullable=False, server_default="1")
    name = Column(String, nullable=False)
    subagent_path = Column(String, nullable=True)
    description = Column(Text, nullable=True)
    model = Column(String, nullable=True)
    # pending | running | waiting_children | waiting | success | error | cancelled
    status = Column(String, nullable=False)
    result_preview = Column(Text, nullable=True)
    error = Column(Text, nullable=True)
    usage = Column(_nullable_jsonb(), nullable=True)
    raw_events = Column(_nullable_jsonb(), nullable=True)
    started_at = Column(DateTime, nullable=True)
    settled_at = Column(DateTime, nullable=True)
    notified_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)


# A conversation whose background tasks are still working is busy like one with
# a streaming answer: its sidebar row spins, and opening it lands on the branch
# of the answer that started them. Both are loaded with the conversation (one
# indexed subquery each), so a list or a detail needs no extra round trip.
_UNSETTLED_TASK = and_(
    ConversationTaskTable.conversation_id == ConversationTable.id,
    ConversationTaskTable.status.not_in(TASK_SETTLED_STATUSES),
)
ConversationTable.active_tasks_flag = column_property(exists().where(_UNSETTLED_TASK))
ConversationTable.active_task_message = column_property(
    select(ConversationTaskTable.spawned_by_message_id)
    .where(_UNSETTLED_TASK, ConversationTaskTable.spawned_by_message_id.is_not(None))
    .order_by(ConversationTaskTable.created_at.desc())
    .limit(1)
    .correlate_except(ConversationTaskTable)
    .scalar_subquery()
)


def _loaded_value(obj: Any, key: str) -> Any:
    """``key`` as last loaded, or None: never a lazy load (under asyncio that
    raises MissingGreenlet). A conversation built in this session, or refreshed
    without these columns, reads as having no working tasks."""
    return sa_inspect(obj).dict.get(key)


# What the response schemas read (``hasActiveTasks`` / ``activeTaskMessageId``).
ConversationTable.has_active_tasks = property(
    lambda self: bool(_loaded_value(self, "active_tasks_flag"))
)
ConversationTable.active_task_message_id = property(
    lambda self: _loaded_value(self, "active_task_message")
)


class AttachmentTable(Base):
    __tablename__ = "attachments"

    id = Column(String, primary_key=True, default=gen_uuid)
    message_id = Column(
        String, ForeignKey("messages.id", ondelete="CASCADE"), nullable=False, index=True
    )

    file_name = Column(String, nullable=False)
    mime_type = Column(String, nullable=False)
    size_bytes = Column(Integer, nullable=True)
    # "upload" for user files, "generated" for a file the agent produced.
    origin = Column(String, nullable=False, server_default="upload")
    # Agent-supplied display metadata, for generated files only.
    title = Column(String, nullable=True)
    summary = Column(String, nullable=True)
    content_sha256 = Column(String(64), nullable=True)

    blob_id = Column(String, ForeignKey("blobs.id", ondelete="CASCADE"), nullable=True, index=True)

    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)

    message = relationship("MessageTable", back_populates="attachments")
    blob = relationship(
        "BlobTable",
        back_populates="attachment",
        cascade="all, delete-orphan",
        uselist=False,
        single_parent=True,
    )


class BlobTable(Base):
    __tablename__ = "blobs"

    id = Column(String, primary_key=True, default=gen_uuid)
    data = Column(LargeBinary, nullable=False)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)

    attachment = relationship("AttachmentTable", back_populates="blob", uselist=False)


# Deleting an attachment row deletes its blob. The foreign key points
# attachments -> blobs, so a cascade from a conversation or message reaches the
# attachment but never its bytes; this trigger closes that gap. Declared here so
# `create_all` (the test database) has it too; the baseline migration creates
# the Postgres version.
event.listen(
    AttachmentTable.__table__,
    "after_create",
    DDL(
        "CREATE TRIGGER trg_attachments_delete_blob AFTER DELETE ON attachments "
        "FOR EACH ROW WHEN OLD.blob_id IS NOT NULL "
        "BEGIN DELETE FROM blobs WHERE id = OLD.blob_id; END"
    ).execute_if(dialect="sqlite"),
)
event.listen(
    AttachmentTable.__table__,
    "after_create",
    DDL(
        "CREATE OR REPLACE FUNCTION delete_attachment_blob() RETURNS trigger "
        "LANGUAGE plpgsql AS $$ "
        "BEGIN DELETE FROM blobs WHERE id = OLD.blob_id; RETURN NULL; END; $$"
    ).execute_if(dialect="postgresql"),
)
event.listen(
    AttachmentTable.__table__,
    "after_create",
    DDL(
        "CREATE TRIGGER trg_attachments_delete_blob AFTER DELETE ON attachments "
        "FOR EACH ROW WHEN (OLD.blob_id IS NOT NULL) EXECUTE FUNCTION delete_attachment_blob()"
    ).execute_if(dialect="postgresql"),
)


# --- Audited systems, their files and audits (migration 0003) ---------------
#
# Few typed columns (what we filter or join on); everything else lives in the
# JSONB ``data`` column so the shapes can change without a migration.
# Systems are deliberately NOT scoped by client id: for now every caller sees
# every system (a documented exception to the client-isolation rule).


def _jsonb() -> JSON:
    """JSONB on Postgres (JSON on sqlite) for the flexible ``data`` columns."""
    return JSON().with_variant(JSONB(), "postgresql")


class SystemTable(Base):
    """One audited AI system (``SYS-001``). Its dossier is the workspace
    namespace ``system:<id>``; ``data`` holds the parsed card and anything else."""

    __tablename__ = "systems"

    id = Column(String, primary_key=True)
    name = Column(String, nullable=False)
    # draft | active | archived (free text, not an enum: flexible).
    status = Column(String, nullable=False, server_default="active", default="active")
    data = Column(_jsonb(), nullable=False, default=dict)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)


class WorkspaceFileBlobTable(Base):
    """File content, stored once per sha256 (content-addressed, plain bytes)."""

    __tablename__ = "workspace_file_blobs"

    sha256 = Column(String(64), primary_key=True)
    data = Column(LargeBinary, nullable=False)
    size_bytes = Column(Integer, nullable=False)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)


class WorkspaceFileTable(Base):
    """One version of one file in a namespace. A write adds a row; old rows stay.

    Namespaces: ``system:<id>`` (the dossier, plugins under ``plugins/<name>/``).
    Agent memory lives in the agents service, not here. At most one
    row per (namespace, path) is current; a delete clears it (and logs an event).
    """

    __tablename__ = "workspace_files"
    __table_args__ = (
        Index(
            "uq_workspace_files_namespace_path_version",
            "namespace",
            "path",
            "version",
            unique=True,
        ),
        Index(
            "uq_workspace_files_current",
            "namespace",
            "path",
            unique=True,
            postgresql_where=text("is_current"),
            sqlite_where=text("is_current"),
        ),
    )

    id = Column(String, primary_key=True, default=gen_uuid)
    namespace = Column(String, nullable=False, index=True)
    path = Column(String, nullable=False)
    version = Column(Integer, nullable=False)
    blob_sha256 = Column(
        String(64), ForeignKey("workspace_file_blobs.sha256"), nullable=False, index=True
    )
    content_type = Column(String, nullable=False, server_default="application/octet-stream")
    size_bytes = Column(Integer, nullable=False)
    created_by = Column(String, nullable=False)
    is_current = Column(Boolean, nullable=False, default=True, server_default="true")
    data = Column(_jsonb(), nullable=False, default=dict)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)


class WorkspaceEventTable(Base):
    """Append-only ledger of every create / update / delete / read / approve."""

    __tablename__ = "workspace_events"
    __table_args__ = (Index("ix_workspace_events_namespace_path", "namespace", "path"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    namespace = Column(String, nullable=False)
    path = Column(String, nullable=False)
    version = Column(Integer, nullable=True)
    action = Column(String, nullable=False)
    actor = Column(String, nullable=False)
    reason = Column(Text, nullable=True)
    audit_id = Column(String, nullable=True, index=True)
    run_id = Column(String, nullable=True)
    trace_id = Column(String, nullable=True)
    data = Column(_jsonb(), nullable=False, default=dict)
    at = Column(DateTime, server_default=func.now(), nullable=False)


class AuditTable(Base):
    """One audit of one system. ``stage`` is where the workflow is
    (context, model_profile, scenarios, ...); ``data`` locks versions
    (``dossier_version``, ``kb_version``) and plugin ids."""

    __tablename__ = "audits"

    # utils/audits.py sets a readable ``<SYSTEM_ID>-<YYYYMMDD>-<HHMM>``; the uuid
    # default only covers rows made elsewhere (and every audit created before).
    id = Column(String, primary_key=True, default=gen_uuid)
    system_id = Column(
        String, ForeignKey("systems.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # open | running | waiting_approval | completed | cancelled (free text).
    status = Column(String, nullable=False, server_default="open", default="open")
    stage = Column(String, nullable=False, server_default="context", default="context")
    created_by = Column(String, nullable=True)
    data = Column(_jsonb(), nullable=False, default=dict)
    # What the run pinned (kb_version, dossier_version, config_version,
    # model_version, seeds): copied from ``data.pins`` when the pipeline writes it.
    pins = Column(_nullable_jsonb(), nullable=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)


class AuditArtifactTable(Base):
    """One version of one stage output. Versioned per (audit, kind, name):
    ``name`` is ``main`` for single outputs, or e.g. a finding id."""

    __tablename__ = "audit_artifacts"
    __table_args__ = (
        Index(
            "uq_audit_artifacts_slot_version",
            "audit_id",
            "kind",
            "name",
            "version",
            unique=True,
        ),
    )

    id = Column(String, primary_key=True, default=gen_uuid)
    audit_id = Column(
        String, ForeignKey("audits.id", ondelete="CASCADE"), nullable=False, index=True
    )
    kind = Column(String, nullable=False)
    name = Column(String, nullable=False, server_default="main", default="main")
    version = Column(Integer, nullable=False)
    # proposed | approved | rejected | changes_requested | superseded
    status = Column(String, nullable=False, server_default="proposed", default="proposed")
    data = Column(_jsonb(), nullable=False, default=dict)
    # Workspace paths, MLflow URIs, Langfuse trace ids the artifact points at.
    file_refs = Column(_jsonb(), nullable=False, default=list)
    parent_id = Column(String, ForeignKey("audit_artifacts.id", ondelete="SET NULL"), nullable=True)
    created_by = Column(String, nullable=False)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)


class ApprovalTable(Base):
    """One human decision at a gate, with its reason. Append-only."""

    __tablename__ = "approvals"

    id = Column(String, primary_key=True, default=gen_uuid)
    audit_id = Column(
        String, ForeignKey("audits.id", ondelete="CASCADE"), nullable=False, index=True
    )
    artifact_id = Column(
        String, ForeignKey("audit_artifacts.id", ondelete="SET NULL"), nullable=True, index=True
    )
    gate = Column(String, nullable=False)
    # approved | rejected | changes_requested
    decision = Column(String, nullable=False)
    reason_category = Column(String, nullable=True)
    comment = Column(Text, nullable=True)
    edits = Column(_jsonb(), nullable=False, default=dict)
    decided_by = Column(String, nullable=False)
    at = Column(DateTime, server_default=func.now(), nullable=False)


class RegulationChangeTable(Base):
    """A RegChange reg-memory announced (``POST /internal/regulation/changes``),
    plus what the humans decided about it. reg-memory stays the source of the
    change itself; ``data`` keeps its payload, the decision and the per-system
    overrides (``affected``)."""

    __tablename__ = "regulation_changes"

    # reg-memory's id, e.g. RC-2026.11.14-2.
    id = Column(String, primary_key=True)
    # proposed | accepted | rejected
    status = Column(String, nullable=False, server_default="proposed", default="proposed")
    data = Column(_jsonb(), nullable=False, default=dict)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)


class TelegramPromptTable(Base):
    """One HITL gate announced on Telegram (audit gate, regulation change,
    chat tool approval). ``id`` is the short token in the buttons'
    callback data; ``key`` dedupes (one open prompt per gate)."""

    __tablename__ = "telegram_prompts"

    id = Column(String, primary_key=True)
    # audit_gate | public_dataset | regulation_change | chat_hitl
    kind = Column(String, nullable=False)
    key = Column(String, nullable=False, index=True)
    # open | decided
    status = Column(String, nullable=False, server_default="open", default="open")
    decision = Column(String, nullable=True)
    decided_by = Column(String, nullable=True)
    # What the decision applies to (audit/gate/artifact, change id, run/interrupt)
    # and the reject flow's state.
    data = Column(_jsonb(), nullable=False, default=dict)
    # [{chat_id, message_id}] of the sent messages, edited after the decision.
    messages = Column(_jsonb(), nullable=False, default=list)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    decided_at = Column(DateTime, nullable=True)


# --- Sealed findings (migration 0006) -----------------------------------------
#
# ``findings``, ``finding_annotations`` and ``finding_status_events`` are
# append-only: a trigger rejects UPDATE and DELETE on all three. A verdict is
# never edited; humans annotate it, and a regulation change or a later audit
# adds a status event (``stale``, ``superseded``). No foreign key to ``audits``
# on purpose: a sealed finding outlives a deleted audit row.


def _utcnow() -> datetime:
    """Microsecond timestamps set in Python, so rows written in one second keep their order."""
    return datetime.now(UTC).replace(tzinfo=None)


class FindingTable(Base):
    """One sealed verdict on one obligation in one audit, hash-chained."""

    __tablename__ = "findings"
    __table_args__ = (
        Index("ix_findings_system_obligation", "system_id", "obligation_id"),
        Index("uq_findings_hash", "hash", unique=True),
    )

    id = Column(String, primary_key=True, default=gen_uuid)
    audit_id = Column(String, nullable=False, index=True)
    system_id = Column(String, nullable=False, index=True)
    obligation_id = Column(String, nullable=False)
    # pass | partial | gap | inconclusive | not_applicable | not_assessable_by_testing
    verdict = Column(String, nullable=False)
    # critical | high | medium | low (NULL when not a gap)
    severity = Column(String, nullable=True)
    gap_id = Column(String, nullable=True)
    metrics_ref = Column(_nullable_jsonb(), nullable=True)
    evidence_refs = Column(_jsonb(), nullable=False, default=list)
    citations = Column(_jsonb(), nullable=False, default=list)
    kb_version = Column(String, nullable=True)
    reasoning = Column(Text, nullable=True)
    counter_arguments = Column(_nullable_jsonb(), nullable=True)
    would_change_if = Column(_nullable_jsonb(), nullable=True)
    judges = Column(_jsonb(), nullable=False, default=dict)
    critic = Column(_jsonb(), nullable=False, default=dict)
    # Anything else the pipeline sent (article, title, ...).
    data = Column(_jsonb(), nullable=False, default=dict)
    prev_hash = Column(String, nullable=True)
    hash = Column(String, nullable=False)
    created_by = Column(String, nullable=False)
    created_at = Column(DateTime, server_default=func.now(), default=_utcnow, nullable=False)


class FindingAnnotationTable(Base):
    """A human note on a sealed finding: contest | accept_risk | remediation_planned | comment."""

    __tablename__ = "finding_annotations"

    id = Column(String, primary_key=True, default=gen_uuid)
    finding_id = Column(String, ForeignKey("findings.id"), nullable=False, index=True)
    kind = Column(String, nullable=False)
    body = Column(Text, nullable=False)
    actor = Column(String, nullable=False)
    created_at = Column(DateTime, server_default=func.now(), default=_utcnow, nullable=False)


class FindingStatusEventTable(Base):
    """A finding's status over time (``stale``, ``superseded``, ``current``); never an edit."""

    __tablename__ = "finding_status_events"

    id = Column(String, primary_key=True, default=gen_uuid)
    finding_id = Column(String, ForeignKey("findings.id"), nullable=False, index=True)
    status = Column(String, nullable=False)
    superseded_by = Column(String, nullable=True)
    reason = Column(Text, nullable=True)
    data = Column(_jsonb(), nullable=False, default=dict)
    actor = Column(String, nullable=False)
    created_at = Column(DateTime, server_default=func.now(), default=_utcnow, nullable=False)


#: The append-only tables (the migration creates the same Postgres triggers).
APPEND_ONLY_TABLES = ("findings", "finding_annotations", "finding_status_events")

event.listen(
    FindingTable.__table__,
    "after_create",
    DDL(
        "CREATE OR REPLACE FUNCTION reject_append_only_change() RETURNS trigger "
        "LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION "
        "'% is append-only: % is not allowed', TG_TABLE_NAME, TG_OP; END; $$"
    ).execute_if(dialect="postgresql"),
)
for _table in (
    FindingTable.__table__,
    FindingAnnotationTable.__table__,
    FindingStatusEventTable.__table__,
):
    for _op in ("UPDATE", "DELETE"):
        event.listen(
            _table,
            "after_create",
            DDL(
                f"CREATE TRIGGER trg_{_table.name}_no_{_op.lower()} BEFORE {_op} ON {_table.name} "
                f"BEGIN SELECT RAISE(ABORT, '{_table.name} is append-only'); END"
            ).execute_if(dialect="sqlite"),
        )
        event.listen(
            _table,
            "after_create",
            DDL(
                f"CREATE TRIGGER trg_{_table.name}_no_{_op.lower()} BEFORE {_op} ON {_table.name} "
                "FOR EACH ROW EXECUTE FUNCTION reject_append_only_change()"
            ).execute_if(dialect="postgresql"),
        )


# --- Findings register (migration 0007) ---------------------------------------
#
# The system's current state per obligation, across audits: an issue tracker
# over the sealed findings. Mutable on purpose (state moves), with an
# append-only ``history`` list inside the row. Sealed findings stay untouched.


class FindingRegisterTable(Base):
    """One row per (system, obligation): its state now and how it got there."""

    __tablename__ = "finding_register"
    __table_args__ = (
        Index("uq_finding_register_system_obligation", "system_id", "obligation_id", unique=True),
    )

    id = Column(String, primary_key=True, default=gen_uuid)
    system_id = Column(
        String, ForeignKey("systems.id", ondelete="CASCADE"), nullable=False, index=True
    )
    obligation_id = Column(String, nullable=False)
    # open | closed | resolved | monitoring
    state = Column(String, nullable=False)
    # The last sealed verdict and severity.
    verdict = Column(String, nullable=False)
    severity = Column(String, nullable=True)
    # Denormalised for display (from the last finding's data).
    article = Column(String, nullable=True)
    title = Column(Text, nullable=True)
    gap_id = Column(String, nullable=True)
    first_seen_audit_id = Column(String, nullable=False)
    last_seen_audit_id = Column(String, nullable=False)
    last_finding_id = Column(String, nullable=True)
    opened_at = Column(DateTime, nullable=True)
    closed_by = Column(String, nullable=True)
    close_reason = Column(Text, nullable=True)
    closed_at = Column(DateTime, nullable=True)
    # [{at, audit_id, actor, kind, from, to, verdict, note}], append-only by convention.
    history = Column(_jsonb(), nullable=False, default=list)
    data = Column(_jsonb(), nullable=False, default=dict)
    created_at = Column(DateTime, server_default=func.now(), default=_utcnow, nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), default=_utcnow, nullable=False)
