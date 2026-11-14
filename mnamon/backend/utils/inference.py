"""Conversation-branch helpers for runs: which messages a run sees, and how
they are serialised for the agents service.

Messages form a tree (edits and retries are siblings under one parent); a run
answers one branch. The backend derives that branch from the database and only
uses the UI's ``messagePath`` hint after checking it. History messages carry
their files inline — the agents service has no way to fetch uploads from the
backend — within a per-request byte budget (see ``utils/agents.py``).
"""

from __future__ import annotations

import base64
from dataclasses import dataclass, field
from typing import Any

from fastapi import HTTPException, status

from core.database import MessageTable
from core.logging import get_logger
from core.settings import settings

logger = get_logger(__name__)


def _bad_request(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=detail)


def nearest_committed_ai(
    messages: list[MessageTable], start_message_id: str | None
) -> MessageTable | None:
    """Walk parent links from ``start_message_id`` (inclusive) to the nearest AI
    message that committed a durable checkpoint (``checkpoint_thread_id`` and
    ``checkpoint_id`` both set); None when there is none.

    This one walk drives both branch-thread allocation (``send`` inherits the
    ancestor's thread, every other mode mints one) and the run's choice
    between a delta resume, a fork and a full cold seed.
    """
    if not start_message_id:
        return None
    lookup = {message.id: message for message in messages}
    current = lookup.get(start_message_id)
    seen: set[str] = set()
    while current is not None and current.id not in seen:
        seen.add(current.id)
        if current.sender == "ai" and current.checkpoint_thread_id and current.checkpoint_id:
            return current
        parent_id = current.parent_message_id
        current = lookup.get(parent_id) if parent_id else None
    return None


def build_path_to_message(messages: list[MessageTable], message_id: str) -> list[MessageTable]:
    """The parent-linked lineage from the root down to ``message_id``."""
    lookup = {message.id: message for message in messages}
    current = lookup.get(message_id)
    if current is None:
        raise _bad_request("Message does not belong to this conversation.")
    path: list[MessageTable] = []
    seen: set[str] = set()
    while current is not None:
        if current.id in seen:
            raise _bad_request("Conversation branch is cyclic.")
        seen.add(current.id)
        path.append(current)
        parent_id = current.parent_message_id
        if not parent_id:
            break
        current = lookup.get(parent_id)
        if current is None:
            raise _bad_request("Conversation branch is incomplete.")
    path.reverse()
    return path


def validate_and_order_message_path(
    messages: list[MessageTable], message_ids: list[str] | None
) -> list[MessageTable]:
    """The messages of ``message_ids`` in that order (all messages when empty);
    400 for blank, duplicate or foreign ids."""
    if not message_ids:
        return messages
    cleaned: list[str] = []
    for raw_id in message_ids:
        if not isinstance(raw_id, str) or not raw_id.strip():
            raise _bad_request("messagePath contains invalid ids.")
        cleaned.append(raw_id.strip())
    if len(set(cleaned)) != len(cleaned):
        raise _bad_request("messagePath contains duplicates.")
    lookup = {message.id: message for message in messages}
    ordered: list[MessageTable] = []
    for message_id in cleaned:
        match = lookup.get(message_id)
        if match is None:
            raise _bad_request("messagePath references messages outside this conversation.")
        ordered.append(match)
    return ordered


def resolve_inference_message_path(
    messages: list[MessageTable],
    parent_message_id: str,
    requested_message_ids: list[str] | None,
) -> list[str]:
    """Check the UI's branch hint when given, then return the authoritative
    database lineage ending at ``parent_message_id`` — client ordering is never
    trusted for the stored run path."""
    if requested_message_ids:
        ordered = validate_and_order_message_path(messages, requested_message_ids)
        for previous, current in zip(ordered, ordered[1:], strict=False):
            if current.parent_message_id != previous.id:
                raise _bad_request("messagePath is not a valid message lineage.")
        if ordered[-1].id != parent_message_id:
            raise _bad_request("messagePath must end at the inference parent message.")
    return [message.id for message in build_path_to_message(messages, parent_message_id)]


@dataclass
class InlineBudget:
    """Bytes of attachment data one agents-service request may still inline."""

    remaining: int = field(default_factory=lambda: settings.attachments.max_total_bytes)

    def take(self, size: int) -> bool:
        if size > self.remaining or size > settings.attachments.max_size_bytes:
            return False
        self.remaining -= size
        return True


def _attachment_entry(attachment: Any, data: bytes | None, budget: InlineBudget) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "id": attachment.id,
        "name": attachment.file_name,
        "mime_type": attachment.mime_type,
        "size_bytes": attachment.size_bytes
        if attachment.size_bytes is not None
        else len(data or b""),
        "sha256": attachment.content_sha256,
        "origin": attachment.origin or "upload",
        "data_base64": None,
    }
    if data is not None and budget.take(len(data)):
        entry["data_base64"] = base64.b64encode(data).decode("ascii")
    elif data is not None:
        entry["omitted"] = "budget"
    return entry


def serialise_message_for_agent(message: MessageTable, budget: InlineBudget) -> dict[str, Any]:
    """One history message in the agents-service shape (``utils/agents.py``).

    Images go inline as ``image_url`` data-URL parts so a vision model sees
    them; every other file goes in ``attachments`` with its bytes base64-encoded
    while ``budget`` lasts, and is also named in a text note so a model without
    file handling knows it exists. A background-task notice row also carries
    ``kind`` and the notification's ``additional_kwargs``.
    """
    parts: list[dict[str, Any]] = []
    text = (message.content or "").strip()
    if text:
        parts.append({"type": "text", "text": text})
    files: list[dict[str, Any]] = []
    for attachment in message.attachments or []:
        mime = (attachment.mime_type or "").lower()
        data = attachment.blob.data if attachment.blob is not None else None
        if mime.startswith("image/") and data and budget.take(len(data)):
            encoded = base64.b64encode(data).decode("ascii")
            parts.append(
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:{mime};base64,{encoded}", "detail": "auto"},
                }
            )
            continue
        files.append(_attachment_entry(attachment, data, budget))
    if files:
        note = "\n".join(f"- {entry['name']} ({entry['mime_type']})" for entry in files)
        parts.append({"type": "text", "text": f"Attachments:\n{note}"})
    if len(parts) == 1 and parts[0]["type"] == "text":
        content: Any = parts[0]["text"]
    else:
        content = parts or ""
    serialised: dict[str, Any] = {
        "id": message.id,
        "role": "user" if message.sender == "user" else "assistant",
        "content": content,
        "attachments": files,
    }
    if message.kind == "task_notification":
        # A background task's notification: the agents service rebuilds the
        # exact HumanMessage it wrote (its original content blocks when kept);
        # its additional_kwargs are how the async-subagent middleware
        # recognises and dedupes it.
        notice = message.task_notice if isinstance(message.task_notice, dict) else {}
        agent_kwargs = notice.get("agent_kwargs")
        agent_content = notice.get("agent_content")
        if isinstance(agent_content, list) and agent_content:
            serialised["content"] = agent_content
        serialised["kind"] = "task_notification"
        serialised["additional_kwargs"] = (
            dict(agent_kwargs) if isinstance(agent_kwargs, dict) else {}
        )
    return serialised


def prepare_inference_history(
    messages: list[MessageTable], message_ids: list[str] | None
) -> list[dict[str, Any]]:
    """The serialised branch for a cold seed: the messages of ``message_ids``
    without the run's own trailing empty placeholder."""
    history = list(validate_and_order_message_path(messages, message_ids))
    if (
        history
        and history[-1].sender == "ai"
        and not history[-1].content
        and not history[-1].attachments
    ):
        history = history[:-1]
    budget = InlineBudget()
    serialised = [serialise_message_for_agent(message, budget) for message in history]
    logger.info(
        "inference_branch_resolved",
        "Inference branch resolved",
        requested_message_path_length=len(message_ids or []),
        serialised_messages=len(serialised),
        inline_budget_left=budget.remaining,
    )
    return serialised
