"""Ownership checks: a conversation is visible only to the client that created it.

There is no login. The caller is the anonymous browser id from ``X-Client-Id``
(``core.security.client.get_caller``); every conversation lookup filters on
``ConversationTable.client_id`` so one browser can never read or change
another's conversations by guessing an id. A miss is always a 404, never a
403, so the response does not reveal that the id exists.
"""

from typing import Annotated

from fastapi import Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from core.database import AttachmentTable, ConversationTable, MessageTable, get_db
from core.logging import set_context
from core.security.client import Caller, get_caller


def _not_found() -> HTTPException:
    return HTTPException(status_code=404, detail="Conversation not found.")


async def load_conversation(
    db: AsyncSession, client_id: str, conversation_id: str
) -> ConversationTable:
    """The caller's conversation row (no messages); 404 otherwise."""
    set_context(user_id=client_id, conversation_id=conversation_id)
    conv = await db.scalar(
        select(ConversationTable).where(
            ConversationTable.id == conversation_id,
            ConversationTable.client_id == client_id,
        )
    )
    if conv is None:
        raise _not_found()
    return conv


async def load_conversation_full(
    db: AsyncSession, client_id: str, conversation_id: str
) -> ConversationTable:
    """The caller's conversation with its messages, attachments and blobs; 404 otherwise."""
    set_context(user_id=client_id, conversation_id=conversation_id)
    conv = await db.scalar(
        select(ConversationTable)
        .options(
            selectinload(ConversationTable.messages)
            .selectinload(MessageTable.attachments)
            .selectinload(AttachmentTable.blob)
        )
        .where(
            ConversationTable.id == conversation_id,
            ConversationTable.client_id == client_id,
        )
    )
    if conv is None:
        raise _not_found()
    return conv


async def validate_conversation(
    conversation_id: str,
    caller: Annotated[Caller, Depends(get_caller)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ConversationTable:
    """Route dependency: the caller's conversation from the ``{conversation_id}`` path param."""
    return await load_conversation(db, caller.id, conversation_id)


async def validate_conversation_full(
    conversation_id: str,
    caller: Annotated[Caller, Depends(get_caller)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ConversationTable:
    """Route dependency: like :func:`validate_conversation`, with messages loaded."""
    return await load_conversation_full(db, caller.id, conversation_id)
