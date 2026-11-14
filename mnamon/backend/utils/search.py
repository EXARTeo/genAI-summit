"""Sidebar search: case-insensitive substring match (``ILIKE``) over the caller's
non-archived conversations (title, preview, agent name), their messages and
their file names.

The query is whitespace-normalized and its LIKE wildcards are escaped, so a
``%`` or ``_`` typed by the user matches itself. Every value goes in as a
bound parameter.
"""

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import contains_eager

from core.database import AttachmentTable, ConversationTable, MessageTable
from schema.search import WorkspaceSearchResult
from utils.conversations import _preview

TITLE_PREVIEW_LENGTH = 72
_ESCAPE = "\\"


def clean_search_query(value: str | None) -> str:
    """Trim and collapse every run of whitespace to one space."""
    return " ".join((value or "").split())


def build_like_pattern(value: str) -> str:
    """``%value%`` with LIKE's wildcards (and the escape character) escaped."""
    escaped = (
        value.replace(_ESCAPE, _ESCAPE * 2).replace("%", _ESCAPE + "%").replace("_", _ESCAPE + "_")
    )
    return f"%{escaped}%"


def resolve_search_conversation_title(conversation: ConversationTable) -> str:
    """The title a result shows: the conversation's, else its preview, else its agent."""
    title = (conversation.title or "").strip()
    if title:
        return title
    preview = _preview(conversation.last_message_preview, TITLE_PREVIEW_LENGTH)
    if preview:
        return preview
    return conversation.agent_name or conversation.agent_slug or "Untitled chat"


async def search_workspace_data(
    *, db: AsyncSession, client_id: str, query: str, limit: int
) -> list[WorkspaceSearchResult]:
    """Up to ``limit`` matches of each kind, merged and cut to ``limit``, newest first."""
    pattern = build_like_pattern(query)
    visible = (
        ConversationTable.client_id == client_id,
        ConversationTable.is_archived.is_(False),
    )
    results: list[WorkspaceSearchResult] = []

    conversations = await db.scalars(
        select(ConversationTable)
        .where(
            *visible,
            or_(
                ConversationTable.title.ilike(pattern, escape=_ESCAPE),
                ConversationTable.last_message_preview.ilike(pattern, escape=_ESCAPE),
                ConversationTable.agent_name.ilike(pattern, escape=_ESCAPE),
            ),
        )
        .order_by(ConversationTable.updated_at.desc())
        .limit(limit)
    )
    for conversation in conversations:
        results.append(
            WorkspaceSearchResult(
                kind="conversation",
                id=conversation.id,
                conversationId=conversation.id,
                agentSlug=conversation.agent_slug,
                title=resolve_search_conversation_title(conversation),
                subtitle=conversation.agent_name,
                snippet=_preview(conversation.last_message_preview),
                updatedAt=conversation.updated_at,
            )
        )

    messages = await db.scalars(
        select(MessageTable)
        .join(MessageTable.conversation)
        .options(contains_eager(MessageTable.conversation))
        .where(*visible, MessageTable.content.ilike(pattern, escape=_ESCAPE))
        .order_by(MessageTable.updated_at.desc())
        .limit(limit)
    )
    for message in messages:
        conversation = message.conversation
        sender = "You" if message.sender == "user" else "Assistant"
        results.append(
            WorkspaceSearchResult(
                kind="message",
                id=message.id,
                conversationId=conversation.id,
                agentSlug=conversation.agent_slug,
                title=resolve_search_conversation_title(conversation),
                subtitle=f"{sender} message",
                snippet=_preview(message.content),
                updatedAt=message.updated_at,
            )
        )

    # Attachment rows only: the blob relationship is lazy, so no bytes are read.
    attachments = await db.scalars(
        select(AttachmentTable)
        .join(AttachmentTable.message)
        .join(MessageTable.conversation)
        .options(contains_eager(AttachmentTable.message).contains_eager(MessageTable.conversation))
        .where(*visible, AttachmentTable.file_name.ilike(pattern, escape=_ESCAPE))
        .order_by(AttachmentTable.updated_at.desc())
        .limit(limit)
    )
    for attachment in attachments:
        conversation = attachment.message.conversation
        results.append(
            WorkspaceSearchResult(
                kind="file",
                id=attachment.id,
                conversationId=conversation.id,
                agentSlug=conversation.agent_slug,
                title=attachment.file_name,
                subtitle=resolve_search_conversation_title(conversation),
                snippet=attachment.mime_type,
                updatedAt=attachment.updated_at,
            )
        )

    results.sort(key=lambda item: item.updatedAt.timestamp() if item.updatedAt else 0, reverse=True)
    return results[:limit]
