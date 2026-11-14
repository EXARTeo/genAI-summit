"""Message operations inside a conversation the caller owns: append, finalize an
AI placeholder, and like / dislike feedback."""

from datetime import UTC, datetime

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from core.database import AttachmentTable, ConversationTable, MessageTable
from schema.messages import MessageIn, MessageUpdate
from utils.conversations import _preview, init_message


async def get_owned_message(
    db: AsyncSession,
    conversation_id: str,
    message_id: str,
    *,
    with_attachments: bool = True,
) -> MessageTable | None:
    """One message of the given conversation (attachments and their blobs
    eager-loaded, for image inlining), or None."""
    stmt = select(MessageTable).where(
        MessageTable.id == message_id,
        MessageTable.conversation_id == conversation_id,
    )
    if with_attachments:
        stmt = stmt.options(
            selectinload(MessageTable.attachments).selectinload(AttachmentTable.blob)
        )
    return await db.scalar(stmt)


async def require_owned_message(
    db: AsyncSession, conversation_id: str, message_id: str
) -> MessageTable:
    """Like :func:`get_owned_message`, but a miss is a 404."""
    msg = await get_owned_message(db, conversation_id, message_id)
    if msg is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Message not found.")
    return msg


async def append_message(
    db: AsyncSession, conv: ConversationTable, payload: MessageIn
) -> MessageTable:
    """Add a message under ``payload.parentMessageId`` and bump the conversation's
    preview when the message has something to show. Flushed, not committed.

    The parent, when given, must belong to the same conversation (400).
    """
    parent_id = payload.parentMessageId
    if (
        parent_id
        and await get_owned_message(db, conv.id, parent_id, with_attachments=False) is None
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Parent message does not belong to this conversation.",
        )
    msg = await init_message(db, conv, payload, parent_message_id=parent_id)
    preview = _preview(payload.content) or (
        payload.attachments[0].name if payload.attachments else None
    )
    if preview is not None:
        conv.last_message_preview = preview
        conv.last_message_at = datetime.now(UTC).replace(tzinfo=None)
    return msg


def finalize_ai_message(
    conv: ConversationTable, message: MessageTable, payload: MessageUpdate
) -> None:
    """Write a streaming-finalization payload onto an AI message and bump the
    conversation's preview. Only AI messages can be updated (400)."""
    if message.sender != "ai":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Only AI messages can be updated."
        )
    message.content = payload.content
    message.reasoning_steps = payload.thinking
    message.reasoning_time_seconds = payload.thinkingTime
    if payload.error is not None:
        message.is_error = bool(payload.error)
    message.error_message = payload.errorMessage
    message.raw_events = payload.rawEvents

    preview = _preview(payload.content)
    if preview is not None:
        conv.last_message_preview = preview
    conv.last_message_at = datetime.now(UTC).replace(tzinfo=None)


def toggle_message_reaction(message: MessageTable, reaction: bool) -> None:
    """Like (``True``) or dislike (``False``); repeating the same one clears it."""
    message.liked = None if message.liked is reaction else reaction
