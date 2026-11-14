"""Message routes (``/v1/messages``): append a message, finalize an AI
placeholder, like / dislike.

Every route is scoped to the caller's ``X-Client-Id`` and rate-limited per
client; the message must belong to a conversation the caller owns (404).
Logic lives in ``utils.messages``.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import ConversationTable, get_db
from core.logging import get_logger, logged_db_operation, set_context
from core.security.client import Caller, get_caller
from core.security.rate_limit import conversation_rate_limit, message_post_rate_limit
from schema.conversations import ConversationSummary, UpdateConversationResponse
from schema.messages import MessageIn, MessageOut, MessageUpdate
from utils.messages import (
    append_message,
    finalize_ai_message,
    get_owned_message,
    require_owned_message,
    toggle_message_reaction,
)
from utils.validators import validate_conversation

router = APIRouter()
logger = get_logger(__name__)


@router.post(
    "/{conversation_id}",
    response_model=UpdateConversationResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Add a message to a conversation",
)
async def add_message(
    payload: MessageIn,
    _caller: Annotated[Caller, Depends(get_caller)],
    # Each call may carry the full attachment budget: caps blob growth.
    _rate_limited: Annotated[None, Depends(message_post_rate_limit)],
    conv: Annotated[ConversationTable, Depends(validate_conversation)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> UpdateConversationResponse:
    """Append a message (attachments optional) under ``parentMessageId``.
    Returns the new message and the conversation's refreshed summary."""
    async with logged_db_operation(
        logger=logger,
        db=db,
        success_event="message_created",
        failure_event="message_create_failed",
        success_message="Message added to conversation",
        failure_message="Message creation failed",
        parent_message_id=payload.parentMessageId,
        sender=payload.sender,
        attachment_count=len(payload.attachments),
    ) as operation:
        msg = await append_message(db, conv, payload)
        await db.commit()
        operation.add(message_id=msg.id)

    msg_row = await get_owned_message(db, conv.id, msg.id)
    await db.refresh(conv)
    return UpdateConversationResponse(
        message=MessageOut.model_validate(msg_row),
        summary=ConversationSummary.model_validate(conv),
    )


@router.patch(
    "/{conversation_id}/{message_id}",
    response_model=UpdateConversationResponse,
    summary="Finalize an AI message after streaming",
)
async def update_message(
    message_id: str,
    payload: MessageUpdate,
    _caller: Annotated[Caller, Depends(get_caller)],
    _rate_limited: Annotated[None, Depends(message_post_rate_limit)],
    conv: Annotated[ConversationTable, Depends(validate_conversation)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> UpdateConversationResponse:
    """Write content, reasoning, error state and raw events onto an AI message
    (400 for a user message). Returns it with the refreshed summary."""
    set_context(message_id=message_id)
    msg = await require_owned_message(db, conv.id, message_id)
    async with logged_db_operation(
        logger=logger,
        db=db,
        success_event="message_updated",
        failure_event="message_update_failed",
        success_message="AI message updated",
        failure_message="AI message update failed",
        message_id=message_id,
        raw_event_count=len(payload.rawEvents),
    ) as operation:
        finalize_ai_message(conv, msg, payload)
        operation.add(is_error=bool(msg.is_error))
        await db.commit()

    await db.refresh(msg)
    await db.refresh(conv)
    return UpdateConversationResponse(
        message=MessageOut.model_validate(msg),
        summary=ConversationSummary.model_validate(conv),
    )


async def _react(
    db: AsyncSession, conv: ConversationTable, message_id: str, liked: bool
) -> MessageOut:
    set_context(message_id=message_id)
    msg = await require_owned_message(db, conv.id, message_id)
    toggle_message_reaction(msg, liked)
    await db.commit()
    await db.refresh(msg)
    logger.info("message_reaction_toggled", "Message reaction toggled", liked=msg.liked)
    return MessageOut.model_validate(msg)


@router.post(
    "/{conversation_id}/{message_id}/like",
    response_model=MessageOut,
    summary="Like a message (again to clear)",
)
async def like_message(
    message_id: str,
    _caller: Annotated[Caller, Depends(get_caller)],
    _rate_limited: Annotated[None, Depends(conversation_rate_limit)],
    conv: Annotated[ConversationTable, Depends(validate_conversation)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> MessageOut:
    """Toggle a like on a message."""
    return await _react(db, conv, message_id, True)


@router.post(
    "/{conversation_id}/{message_id}/dislike",
    response_model=MessageOut,
    summary="Dislike a message (again to clear)",
)
async def dislike_message(
    message_id: str,
    _caller: Annotated[Caller, Depends(get_caller)],
    _rate_limited: Annotated[None, Depends(conversation_rate_limit)],
    conv: Annotated[ConversationTable, Depends(validate_conversation)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> MessageOut:
    """Toggle a dislike on a message."""
    return await _react(db, conv, message_id, False)
