"""Conversation lifecycle: create (with the first message), message and
attachment inserts, archive / pin state, fork, delete and the sidebar queries.

Every function here takes a conversation the caller already owns (loaded
through ``utils.validators``) or a ``client_id`` to scope by; none looks a
conversation up by id alone.
"""

import hashlib
from copy import deepcopy
from datetime import UTC, datetime

from fastapi import HTTPException, status
from sqlalchemy import Select, delete, func, literal, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import (
    AttachmentTable,
    BlobTable,
    ConversationTable,
    ConversationTaskTable,
    MessageTable,
)
from core.logging import get_logger
from core.settings import settings
from schema.attachments import AttachmentIn
from schema.conversations import MAX_TITLE_LENGTH
from schema.messages import MessageIn
from utils.agents_tasks import AgentsTaskError, agents_cancel_scope

logger = get_logger(__name__)

#: Run states in which an AI message is still being written by a run.
ACTIVE_STREAMING_STATUSES = ("queued", "running", "cancelling")

PREVIEW_LENGTH = 40


def _utcnow() -> datetime:
    """Naive UTC, the way every timestamp column stores it."""
    return datetime.now(UTC).replace(tzinfo=None)


def _preview(text: str | None, limit: int = PREVIEW_LENGTH) -> str | None:
    """A one-line preview of ``text`` (newlines collapsed), at most ``limit`` chars."""
    if not text:
        return None
    collapsed = text.strip().replace("\r", " ").replace("\n", " ")
    return collapsed[:limit]


def resolve_conversation_title(
    explicit_title: str | None, first_message: MessageIn, agent_name: str | None
) -> str:
    """The title a new conversation starts with: the one asked for, else a
    preview of the first message, else the agent's name."""
    explicit = (explicit_title or "").strip()[:MAX_TITLE_LENGTH].rstrip()
    return explicit or _preview(first_message.content) or agent_name or "New conversation"


async def init_conv(
    db: AsyncSession,
    *,
    client_id: str,
    agent_slug: str,
    agent_name: str | None,
    title: str | None,
    first_message: MessageIn,
    system_id: str | None = None,
    audit_id: str | None = None,
) -> ConversationTable:
    """Add a conversation and its first message to the session (flushed, not committed)."""
    conv = ConversationTable(
        client_id=client_id,
        agent_slug=agent_slug,
        agent_name=agent_name,
        title=title,
        system_id=system_id,
        audit_id=audit_id,
        last_message_preview=_preview(first_message.content)
        or (first_message.attachments[0].name if first_message.attachments else None),
        last_message_at=_utcnow(),
    )
    db.add(conv)
    await db.flush()  # conv.id is needed by the first message.
    await init_message(db, conv, first_message, parent_message_id=None)
    return conv


async def init_message(
    db: AsyncSession,
    conv: ConversationTable,
    payload: MessageIn,
    parent_message_id: str | None = None,
) -> MessageTable:
    """Add one message (and its attachments) to the session (flushed, not committed)."""
    msg = MessageTable(
        conversation_id=conv.id,
        parent_message_id=parent_message_id,
        # Stamped here, not by the database: Postgres's now() is fixed for the
        # whole transaction, so a user message and the AI reply created with it
        # would tie and come back in whatever order an index scan yields.
        created_at=_utcnow(),
        sender=payload.sender,
        content=payload.content,
        reasoning_steps=payload.thinking,
        reasoning_time_seconds=payload.thinkingTime,
        is_error=bool(payload.error),
        error_message=payload.errorMessage,
        raw_events=payload.rawEvents,
    )
    db.add(msg)
    await db.flush()  # msg.id is needed by the attachment rows.
    if payload.attachments:
        init_attachments(db, msg.id, payload.attachments)
    return msg


def init_attachments(db: AsyncSession, message_id: str, items: list[AttachmentIn]) -> None:
    """Add a message's uploads, each with its blob and content hash, to the session."""
    for item in items:
        raw = item.raw_bytes()
        db.add(
            AttachmentTable(
                message_id=message_id,
                file_name=item.name,
                mime_type=item.mime,
                size_bytes=len(raw),
                content_sha256=hashlib.sha256(raw).hexdigest(),
                blob=BlobTable(data=raw),
            )
        )


async def set_conversation_archive_state(
    db: AsyncSession, conv: ConversationTable, archived: bool
) -> None:
    """Archive or unarchive, and commit. Archiving also unpins: an archived
    conversation leaves the sidebar, and unarchiving does not restore the pin."""
    conv.is_archived = archived
    conv.archived_at = _utcnow() if archived else None
    if archived:
        conv.is_pinned = False
        conv.pinned_at = None
    await db.commit()
    await db.refresh(conv)


async def _lock_client_pins(db: AsyncSession, client_id: str) -> None:
    """Serialize one client's pin requests so two concurrent pins cannot both
    pass the cap check. A transaction-scoped advisory lock on Postgres (there is
    no per-client row to lock); SQLite already serializes writers."""
    if db.get_bind().dialect.name == "postgresql":
        await db.execute(select(func.pg_advisory_xact_lock(func.hashtext(literal(client_id)))))


async def set_conversation_pin_state(
    db: AsyncSession, conv: ConversationTable, pinned: bool
) -> None:
    """Pin a conversation to the sidebar's Pinned section, or unpin it, and commit.

    Idempotent: asking for the state it is already in changes nothing, so a
    repeated pin keeps its place. Archived conversations cannot be pinned, and
    a client holds at most ``settings.conversations.max_pinned`` pins (409),
    which keeps the Pinned list to one bounded page.

    Written with a Core UPDATE that sets ``updated_at`` to itself: the ORM's
    ``onupdate=now()`` would otherwise mark the conversation as just active,
    and unpinning would drop it at the top of Chats instead of in its place.
    """
    if conv.is_pinned == pinned:
        return
    if pinned:
        if conv.is_archived:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Only conversations in your chat history can be pinned.",
            )
        await _lock_client_pins(db, conv.client_id)
        pinned_count = await db.scalar(
            select(func.count())
            .select_from(ConversationTable)
            .where(
                ConversationTable.client_id == conv.client_id,
                ConversationTable.is_pinned.is_(True),
            )
        )
        limit = settings.conversations.max_pinned
        if (pinned_count or 0) >= limit:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"You can pin up to {limit} conversations. Unpin one first.",
            )

    await db.execute(
        update(ConversationTable)
        .where(ConversationTable.id == conv.id)
        .values(
            is_pinned=pinned,
            pinned_at=_utcnow() if pinned else None,
            updated_at=ConversationTable.updated_at,
        )
        .execution_options(synchronize_session=False)
    )
    await db.commit()
    await db.refresh(conv)


async def has_active_run(db: AsyncSession, conv: ConversationTable) -> bool:
    """Whether a run is still writing to this conversation."""
    if conv.active_assistant_message_id:
        return True
    streaming = await db.scalar(
        select(MessageTable.id)
        .where(
            MessageTable.conversation_id == conv.id,
            MessageTable.streaming_status.in_(ACTIVE_STREAMING_STATUSES),
        )
        .limit(1)
    )
    return streaming is not None


async def delete_conversation(db: AsyncSession, conv: ConversationTable) -> None:
    """Delete a conversation and commit. The foreign-key cascade removes its
    messages and attachments; a database trigger removes their blobs.

    Refused (409) while a run is active: the run would keep writing into a
    conversation that no longer exists. Stop the run first. Its background
    tasks are stopped first (best effort: a task that still settles later is
    refused by the mirror, its conversation being gone) and their mirror rows
    are deleted in the same transaction.
    """
    if await has_active_run(db, conv):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This conversation has a response in progress. Stop it before deleting.",
        )
    has_tasks = await db.scalar(
        select(ConversationTaskTable.task_id)
        .where(ConversationTaskTable.conversation_id == conv.id)
        .limit(1)
    )
    if has_tasks is not None:
        try:
            await agents_cancel_scope(conv.client_id, conv.id)
        except AgentsTaskError as exc:
            logger.warning(
                "conversation_tasks_cancel_failed",
                "Could not stop the conversation's background tasks before deleting it",
                conversation_id=conv.id,
                error_type=str(exc),
            )
        await db.execute(
            delete(ConversationTaskTable).where(ConversationTaskTable.conversation_id == conv.id)
        )
    await db.delete(conv)
    await db.commit()


def build_message_lineage(
    messages: list[MessageTable], target_message_id: str
) -> list[MessageTable]:
    """The branch from the root down to ``target_message_id`` (a finished AI
    message), oldest first. 400 if the target is not forkable or the chain breaks."""
    lookup = {message.id: message for message in messages}
    target = lookup.get(target_message_id)
    if target is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Fork target message does not belong to this conversation.",
        )
    if target.sender != "ai":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only AI messages can be used as a fork target.",
        )
    if not target.content and not target.attachments:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot fork from an unfinished AI message.",
        )

    lineage: list[MessageTable] = []
    current: MessageTable | None = target
    seen: set[str] = set()
    while current is not None:
        if current.id in seen:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="Conversation branch is cyclic."
            )
        seen.add(current.id)
        lineage.append(current)
        parent_id = current.parent_message_id
        if not parent_id:
            break
        current = lookup.get(parent_id)
        if current is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Conversation branch is incomplete.",
            )
    lineage.reverse()
    return lineage


async def clone_branch_to_conversation(
    *,
    db: AsyncSession,
    source_conv: ConversationTable,
    branch: list[MessageTable],
    forked_message_id: str,
) -> ConversationTable:
    """Copy ``branch`` (messages, attachments, blobs) into a new conversation of
    the same client and agent. Added to the session, not committed."""
    target_message = branch[-1]
    fallback_attachment_name = (
        target_message.attachments[0].file_name if target_message.attachments else None
    )
    now = _utcnow()
    forked_conv = ConversationTable(
        client_id=source_conv.client_id,
        agent_slug=source_conv.agent_slug,
        agent_name=source_conv.agent_name,
        forked_parent_id=source_conv.id,
        forked_message_id=forked_message_id,
        title=source_conv.title,
        is_archived=False,
        is_pinned=False,
        last_message_preview=_preview(target_message.content) or fallback_attachment_name,
        last_message_at=now,
        updated_at=now,
    )
    db.add(forked_conv)
    await db.flush()

    message_id_map: dict[str, str] = {}
    for source_message in branch:
        # Deliberately NOT copying checkpoint_thread_id / checkpoint_id: the fork
        # gets its own checkpoint thread. Carrying the source's ids would make the
        # fork resume another conversation's live checkpoint; left NULL, its
        # first run cold-seeds a fresh thread from the copied history.
        cloned_message = MessageTable(
            conversation_id=forked_conv.id,
            parent_message_id=message_id_map.get(source_message.parent_message_id),
            sender=source_message.sender,
            content=source_message.content,
            liked=source_message.liked,
            agent_slug=source_message.agent_slug,
            agent_name=source_message.agent_name,
            reasoning_steps=deepcopy(source_message.reasoning_steps),
            reasoning_time_seconds=source_message.reasoning_time_seconds,
            is_error=source_message.is_error,
            error_message=source_message.error_message,
            raw_events=deepcopy(source_message.raw_events),
            kind=source_message.kind,
            task_notice=deepcopy(source_message.task_notice),
            created_at=source_message.created_at,
            updated_at=source_message.updated_at,
        )
        db.add(cloned_message)
        await db.flush()
        message_id_map[source_message.id] = cloned_message.id

        for source_attachment in source_message.attachments:
            source_blob = source_attachment.blob
            db.add(
                AttachmentTable(
                    message_id=cloned_message.id,
                    file_name=source_attachment.file_name,
                    mime_type=source_attachment.mime_type,
                    size_bytes=source_attachment.size_bytes,
                    # Carried over, or a generated file would turn into an upload.
                    origin=source_attachment.origin,
                    title=source_attachment.title,
                    summary=source_attachment.summary,
                    content_sha256=source_attachment.content_sha256,
                    blob=BlobTable(data=source_blob.data) if source_blob is not None else None,
                    created_at=source_attachment.created_at,
                    updated_at=source_attachment.updated_at,
                )
            )
    return forked_conv


def conversation_summaries_query(
    client_id: str, *, archived: bool = False, pinned: bool = False
) -> Select:
    """The paginated query behind one of the client's conversation lists.

    The sidebar shows two disjoint lists, Pinned (``pinned=True``, newest pin
    first) and Chats (the rest, most recent first), so a pinned conversation
    never appears twice. ``archived=True`` is the archive, newest archived
    first; nothing there is pinned and ``pinned`` is ignored. Only conversation
    columns are read: no messages, no blob bytes.
    """
    stmt = select(ConversationTable).where(
        ConversationTable.client_id == client_id,
        ConversationTable.is_archived.is_(archived),
    )
    if archived:
        return stmt.order_by(
            ConversationTable.archived_at.desc(),
            ConversationTable.updated_at.desc(),
            ConversationTable.id,
        )
    stmt = stmt.where(ConversationTable.is_pinned.is_(pinned))
    if pinned:
        return stmt.order_by(
            ConversationTable.pinned_at.desc(),
            ConversationTable.updated_at.desc(),
            ConversationTable.id,
        )
    return stmt.order_by(ConversationTable.updated_at.desc(), ConversationTable.id)
