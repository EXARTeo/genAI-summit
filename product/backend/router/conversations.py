"""Conversation routes (``/v1/conversations``): the sidebar lists, create, read,
rename, archive, pin, fork and delete.

Every route is scoped to the caller's ``X-Client-Id`` (``get_caller``) and
rate-limited per client; a conversation of another client is a 404. Literal
paths (``/archived``, ``/pinned``) are declared before ``/{conversation_id}``.
Logic lives in ``utils.conversations``.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, status
from fastapi_pagination import Page
from fastapi_pagination.ext.sqlalchemy import apaginate
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import ConversationTable, get_db
from core.logging import get_logger, logged_db_operation, set_context
from core.security.client import Caller, get_caller
from core.security.rate_limit import conversation_rate_limit, message_post_rate_limit
from schema.conversations import (
    ConversationDetail,
    ConversationForkIn,
    ConversationIn,
    ConversationSummary,
    ConversationTitleUpdate,
    CreateConversationResponse,
)
from utils.conversations import (
    _preview,
    build_message_lineage,
    clone_branch_to_conversation,
    conversation_summaries_query,
    delete_conversation,
    init_conv,
    resolve_conversation_title,
    set_conversation_archive_state,
    set_conversation_pin_state,
)
from utils.validators import load_conversation, load_conversation_full, validate_conversation

router = APIRouter()
logger = get_logger(__name__)


async def _list_page(db: AsyncSession, client_id: str, event: str, **flags: bool) -> Page:
    page = await apaginate(db, conversation_summaries_query(client_id, **flags))
    logger.info(
        event,
        "Conversation summary list fetched",
        total=page.total,
        page=page.page,
        size=page.size,
    )
    return page


@router.get(
    "",
    response_model=Page[ConversationSummary],
    summary="List the caller's conversations (not archived, not pinned), most recent first",
)
async def list_conversations(
    caller: Annotated[Caller, Depends(get_caller)],
    _rate_limited: Annotated[None, Depends(conversation_rate_limit)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Page:
    """The sidebar's Chats list. Query params: ``?page=1&size=50``."""
    return await _list_page(db, caller.id, "conversation_summary_list_fetched")


@router.get(
    "/archived",
    response_model=Page[ConversationSummary],
    summary="List the caller's archived conversations, newest archived first",
)
async def list_archived_conversations(
    caller: Annotated[Caller, Depends(get_caller)],
    _rate_limited: Annotated[None, Depends(conversation_rate_limit)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Page:
    """The archive view."""
    return await _list_page(
        db, caller.id, "conversation_archived_summary_list_fetched", archived=True
    )


@router.get(
    "/pinned",
    response_model=Page[ConversationSummary],
    summary="List the caller's pinned conversations, newest pin first",
)
async def list_pinned_conversations(
    caller: Annotated[Caller, Depends(get_caller)],
    _rate_limited: Annotated[None, Depends(conversation_rate_limit)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Page:
    """The sidebar's Pinned list; the pin cap keeps it to one page."""
    return await _list_page(db, caller.id, "conversation_pinned_summary_list_fetched", pinned=True)


@router.post(
    "",
    response_model=CreateConversationResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a conversation with its first message",
)
async def create_conversation(
    payload: ConversationIn,
    caller: Annotated[Caller, Depends(get_caller)],
    _rate_limited: Annotated[None, Depends(conversation_rate_limit)],
    # The first message may carry the full attachment budget.
    _upload_limited: Annotated[None, Depends(message_post_rate_limit)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> CreateConversationResponse:
    """Create a conversation with an agent (by slug) and persist its first
    message, attachments included. Returns the full detail and the summary."""
    title = resolve_conversation_title(payload.title, payload.firstMessage, payload.agentName)
    async with logged_db_operation(
        logger=logger,
        db=db,
        success_event="conversation_created",
        failure_event="conversation_create_failed",
        success_message="Conversation created",
        failure_message="Conversation creation failed",
        agent_slug=payload.agentSlug,
        attachment_count=len(payload.firstMessage.attachments),
        sender=payload.firstMessage.sender,
    ) as operation:
        conv = await init_conv(
            db,
            client_id=caller.id,
            agent_slug=payload.agentSlug,
            agent_name=payload.agentName,
            title=title,
            first_message=payload.firstMessage,
        )
        await db.commit()
        operation.add(conversation_id=conv.id)
    set_context(conversation_id=conv.id)

    conv_full = await load_conversation_full(db, caller.id, conv.id)
    return CreateConversationResponse(
        detail=ConversationDetail.model_validate(conv_full),
        summary=ConversationSummary.model_validate(conv_full),
    )


@router.get(
    "/{conversation_id}",
    response_model=ConversationDetail,
    summary="Get one conversation with all its messages",
)
async def get_conversation(
    conversation_id: str,
    caller: Annotated[Caller, Depends(get_caller)],
    _rate_limited: Annotated[None, Depends(conversation_rate_limit)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ConversationDetail:
    """One conversation, every branch of messages included, images inline."""
    conv = await load_conversation_full(db, caller.id, conversation_id)
    logger.info(
        "conversation_details_fetched",
        "Conversation details fetched",
        message_count=len(conv.messages),
    )
    return ConversationDetail.model_validate(conv)


@router.delete(
    "/{conversation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a conversation (409 while a run is active)",
)
async def remove_conversation(
    _caller: Annotated[Caller, Depends(get_caller)],
    _rate_limited: Annotated[None, Depends(conversation_rate_limit)],
    conv: Annotated[ConversationTable, Depends(validate_conversation)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    """Delete a conversation permanently: messages, attachments and blobs go with it."""
    await delete_conversation(db, conv)
    logger.info("conversation_deleted", "Conversation deleted", agent_slug=conv.agent_slug)


@router.patch(
    "/{conversation_id}/title",
    response_model=ConversationSummary,
    summary="Rename a conversation",
)
async def rename_conversation(
    payload: ConversationTitleUpdate,
    _caller: Annotated[Caller, Depends(get_caller)],
    _rate_limited: Annotated[None, Depends(conversation_rate_limit)],
    conv: Annotated[ConversationTable, Depends(validate_conversation)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ConversationSummary:
    """Set a new title (trimmed, at most 200 characters) and return the summary."""
    conv.title = payload.title
    await db.commit()
    await db.refresh(conv)
    logger.info(
        "conversation_renamed",
        "Conversation title updated",
        title_length=len(payload.title),
        title_preview=_preview(payload.title),
    )
    return ConversationSummary.model_validate(conv)


@router.patch(
    "/{conversation_id}/archive",
    response_model=ConversationSummary,
    summary="Archive a conversation (also unpins it)",
)
async def archive_conversation(
    _caller: Annotated[Caller, Depends(get_caller)],
    _rate_limited: Annotated[None, Depends(conversation_rate_limit)],
    conv: Annotated[ConversationTable, Depends(validate_conversation)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ConversationSummary:
    """Move a conversation to the archive and return the summary."""
    await set_conversation_archive_state(db, conv, True)
    logger.info("conversation_archived", "Conversation archived")
    return ConversationSummary.model_validate(conv)


@router.patch(
    "/{conversation_id}/unarchive",
    response_model=ConversationSummary,
    summary="Unarchive a conversation",
)
async def unarchive_conversation(
    _caller: Annotated[Caller, Depends(get_caller)],
    _rate_limited: Annotated[None, Depends(conversation_rate_limit)],
    conv: Annotated[ConversationTable, Depends(validate_conversation)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ConversationSummary:
    """Bring an archived conversation back to the Chats list."""
    await set_conversation_archive_state(db, conv, False)
    logger.info("conversation_unarchived", "Conversation unarchived")
    return ConversationSummary.model_validate(conv)


@router.patch(
    "/{conversation_id}/pin",
    response_model=ConversationSummary,
    summary="Pin a conversation (409 if archived or past the pin cap)",
)
async def pin_conversation(
    _caller: Annotated[Caller, Depends(get_caller)],
    _rate_limited: Annotated[None, Depends(conversation_rate_limit)],
    conv: Annotated[ConversationTable, Depends(validate_conversation)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ConversationSummary:
    """Pin to the top of the sidebar. Idempotent: a repeated pin keeps its place."""
    await set_conversation_pin_state(db, conv, True)
    logger.info("conversation_pinned", "Conversation pinned")
    return ConversationSummary.model_validate(conv)


@router.patch(
    "/{conversation_id}/unpin",
    response_model=ConversationSummary,
    summary="Unpin a conversation",
)
async def unpin_conversation(
    _caller: Annotated[Caller, Depends(get_caller)],
    _rate_limited: Annotated[None, Depends(conversation_rate_limit)],
    conv: Annotated[ConversationTable, Depends(validate_conversation)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ConversationSummary:
    """Unpin; the conversation returns to Chats in its place by recency."""
    await set_conversation_pin_state(db, conv, False)
    logger.info("conversation_unpinned", "Conversation unpinned")
    return ConversationSummary.model_validate(conv)


@router.post(
    "/{conversation_id}/fork",
    response_model=ConversationSummary,
    status_code=status.HTTP_201_CREATED,
    summary="Fork a conversation branch into a new conversation",
)
async def fork_conversation(
    conversation_id: str,
    payload: ConversationForkIn,
    caller: Annotated[Caller, Depends(get_caller)],
    _rate_limited: Annotated[None, Depends(conversation_rate_limit)],
    # A fork copies every file of the branch.
    _upload_limited: Annotated[None, Depends(message_post_rate_limit)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ConversationSummary:
    """Copy the branch ending at the given finished AI message (messages,
    attachments, files) into a new conversation of the caller."""
    set_context(message_id=payload.messageId)
    source = await load_conversation_full(db, caller.id, conversation_id)
    branch = build_message_lineage(source.messages, payload.messageId)
    async with logged_db_operation(
        logger=logger,
        db=db,
        success_event="conversation_forked",
        failure_event="conversation_fork_failed",
        success_message="Conversation forked",
        failure_message="Conversation fork failed",
        source_conversation_id=conversation_id,
        forked_message_id=payload.messageId,
        branch_message_count=len(branch),
    ) as operation:
        forked = await clone_branch_to_conversation(
            db=db, source_conv=source, branch=branch, forked_message_id=payload.messageId
        )
        await db.commit()
        operation.add(forked_conversation_id=forked.id)
    return ConversationSummary.model_validate(await load_conversation(db, caller.id, forked.id))
