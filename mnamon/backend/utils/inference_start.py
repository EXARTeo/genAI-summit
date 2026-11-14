"""Starting a run: write the user side of the turn, then create the run.

Four modes (``schema.inference.InferenceStartPayload``):

* ``new``   — a conversation for ``agentSlug`` with its first message;
* ``send``  — a user message under ``parentMessageId`` (optionally switching
  the agent for this turn);
* ``edit``  — a sibling of the user message ``targetMessageId`` (a new branch),
  answered by the agent that answered the original;
* ``retry`` — a new answer to the prompt above the AI message
  ``targetMessageId``, by the agent that produced it.

The agent is named by slug only; the agents service validates it (an unknown
slug fails the run with "This agent is not available."). Everything is written
in one transaction with the run's placeholder, so a refused start (409 busy,
429 over the active-run cap) leaves nothing behind.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import ConversationTable, MessageTable
from schema.conversations import ConversationSummary
from schema.inference import InferenceStartPayload, InferenceStartResponse
from schema.messages import MessageIn, MessageOut
from utils.audits import validate_conversation_subject
from utils.conversations import _preview, init_conv, init_message, resolve_conversation_title
from utils.inference import resolve_inference_message_path
from utils.inference_runs import (
    build_run_out_from_message,
    create_inference_run_record,
    load_run_message,
)
from utils.validators import load_conversation, load_conversation_full


@dataclass
class _Turn:
    """What a start mode resolved: where the run hangs and which agent runs it."""

    conversation: ConversationTable
    parent_message_id: str
    agent_slug: str
    agent_name: str | None
    user_message_id: str | None


def _bad_request(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=detail)


def _require_message(payload: InferenceStartPayload) -> MessageIn:
    if payload.message is None:
        raise _bad_request("message is required for this inference mode.")
    if payload.message.sender != "user":
        raise _bad_request("Inference start messages must be user messages.")
    return payload.message


def _message_by_id(messages: list[MessageTable], message_id: str, detail: str) -> MessageTable:
    match = next((message for message in messages if message.id == message_id), None)
    if match is None:
        raise _bad_request(detail)
    return match


def _touch_conversation(conversation: ConversationTable, message: MessageIn) -> None:
    preview = _preview(message.content) or (
        message.attachments[0].name if message.attachments else None
    )
    if preview is not None:
        conversation.last_message_preview = preview
    conversation.last_message_at = datetime.now(UTC).replace(tzinfo=None)


async def _reload(
    db: AsyncSession, client_id: str, conversation: ConversationTable
) -> ConversationTable:
    await db.flush()
    db.expire(conversation, ["messages"])
    return await load_conversation_full(db, client_id, conversation.id)


async def _new_conversation(
    db: AsyncSession, client_id: str, payload: InferenceStartPayload
) -> _Turn:
    if not payload.agentSlug:
        raise _bad_request("agentSlug is required for new inference starts.")
    first_message = _require_message(payload)
    await validate_conversation_subject(db, payload.systemId, payload.auditId)
    conversation = await init_conv(
        db,
        client_id=client_id,
        agent_slug=payload.agentSlug,
        agent_name=payload.agentName,
        title=resolve_conversation_title(payload.title, first_message, payload.agentName),
        first_message=first_message,
        system_id=payload.systemId,
        audit_id=payload.auditId,
    )
    conversation = await _reload(db, client_id, conversation)
    first = next((m for m in conversation.messages if m.sender == "user"), None)
    if first is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Conversation first message was not created.",
        )
    return _Turn(conversation, first.id, payload.agentSlug, payload.agentName, first.id)


async def _send(db: AsyncSession, client_id: str, payload: InferenceStartPayload) -> _Turn:
    if not payload.conversationId or not payload.parentMessageId:
        raise _bad_request(
            "conversationId and parentMessageId are required for send inference starts."
        )
    message = _require_message(payload)
    conversation = await load_conversation_full(db, client_id, payload.conversationId)
    _message_by_id(
        conversation.messages,
        payload.parentMessageId,
        "Parent message does not belong to this conversation.",
    )
    resolve_inference_message_path(
        conversation.messages, payload.parentMessageId, payload.messagePath
    )
    if payload.agentSlug and payload.agentSlug != conversation.agent_slug:
        agent_slug, agent_name = payload.agentSlug, payload.agentName
    else:
        agent_slug = conversation.agent_slug
        agent_name = payload.agentName or conversation.agent_name
    created = await init_message(
        db, conversation, message, parent_message_id=payload.parentMessageId
    )
    _touch_conversation(conversation, message)
    created_id = created.id
    conversation = await _reload(db, client_id, conversation)
    return _Turn(conversation, created_id, agent_slug, agent_name, created_id)


def _answering_agent(
    conversation: ConversationTable, message: MessageTable | None
) -> tuple[str, str | None]:
    """The agent of ``message`` (an AI reply), else the conversation's."""
    if message is not None and message.agent_slug:
        return message.agent_slug, message.agent_name
    return conversation.agent_slug, conversation.agent_name


async def _edit(db: AsyncSession, client_id: str, payload: InferenceStartPayload) -> _Turn:
    if not payload.conversationId or not payload.targetMessageId:
        raise _bad_request(
            "conversationId and targetMessageId are required for edit inference starts."
        )
    message = _require_message(payload)
    conversation = await load_conversation_full(db, client_id, payload.conversationId)
    target = _message_by_id(
        conversation.messages,
        payload.targetMessageId,
        "Edited message does not belong to this conversation.",
    )
    if target.sender != "user":
        raise _bad_request("Only user messages can be edited into a new inference branch.")
    original_reply = next(
        (m for m in conversation.messages if m.parent_message_id == target.id and m.sender == "ai"),
        None,
    )
    agent_slug, agent_name = _answering_agent(conversation, original_reply)
    created = await init_message(
        db, conversation, message, parent_message_id=target.parent_message_id
    )
    _touch_conversation(conversation, message)
    created_id = created.id
    conversation = await _reload(db, client_id, conversation)
    return _Turn(conversation, created_id, agent_slug, agent_name, created_id)


async def _retry(db: AsyncSession, client_id: str, payload: InferenceStartPayload) -> _Turn:
    if not payload.conversationId or not payload.targetMessageId:
        raise _bad_request(
            "conversationId and targetMessageId are required for retry inference starts."
        )
    conversation = await load_conversation_full(db, client_id, payload.conversationId)
    target = _message_by_id(
        conversation.messages,
        payload.targetMessageId,
        "Retry target does not belong to this conversation.",
    )
    if target.sender != "ai":
        raise _bad_request("Only AI messages can be retried.")
    if not target.parent_message_id:
        raise _bad_request("Retry target is missing a parent prompt.")
    _message_by_id(
        conversation.messages,
        target.parent_message_id,
        "Retry parent message does not belong to this conversation.",
    )
    agent_slug, agent_name = _answering_agent(conversation, target)
    return _Turn(conversation, target.parent_message_id, agent_slug, agent_name, None)


_MODES = {"new": _new_conversation, "send": _send, "edit": _edit, "retry": _retry}


async def start_inference_flow(
    *, db: AsyncSession, client_id: str, payload: InferenceStartPayload
) -> InferenceStartResponse:
    """Write the turn and create its run (committed, not yet launched)."""
    turn = await _MODES[payload.mode](db, client_id, payload)
    # Only a retry can name the run's parent path; every other mode creates the
    # parent in this request, so a client path would end above it.
    message_path = payload.messagePath if payload.mode == "retry" else None
    assistant_message = await create_inference_run_record(
        db=db,
        client_id=client_id,
        conversation=turn.conversation,
        parent_message_id=turn.parent_message_id,
        message_path=message_path,
        agent_slug=turn.agent_slug,
        agent_name=turn.agent_name,
        mode=payload.mode,
    )
    conversation_id, run_id = turn.conversation.id, assistant_message.id
    await db.commit()
    db.expire_all()

    conversation = await load_conversation(db, client_id, conversation_id)
    run_message = await load_run_message(db, run_id)
    user_message = (
        await load_run_message(db, turn.user_message_id) if turn.user_message_id else None
    )
    if run_message is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Inference run start could not be loaded after creation.",
        )
    return InferenceStartResponse(
        summary=ConversationSummary.model_validate(conversation),
        run=build_run_out_from_message(run_message),
        message=MessageOut.model_validate(run_message),
        userMessage=MessageOut.model_validate(user_message) if user_message is not None else None,
    )
