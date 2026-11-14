"""``/conversation/input/``: the user's uploads, written from the run request.

The backend sends every non-image file of a message (and any image past its
inline budget) as an inline ``attachments`` entry with ``data_base64``
(``docs/contracts/agents-contract.md`` § Attachment). Before a run starts, each one is
written into the conversation's files at ``/conversation/input/<name>``, where
the agent, every sub-agent and the sandbox read it. The agent can never write
there (the workspace write-deny and the files backend both refuse it).

Writing is idempotent: the store is content-addressed and an upload already
there under its name is left alone, so a full-history seed that re-sends every
earlier upload costs a hash per file. Two different files with the same name
keep both: the second gets the attachment id in its name. Bytes are checked
against the declared ``sha256`` and size; a mismatch, a missing payload
(``"omitted": "budget"``) or an unusable name is skipped and logged, never a
failed run.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any

from core.logging import get_logger
from core.settings import settings
from harness.conversation_files import paths
from harness.conversation_files.store import ConversationFileStore

logger = get_logger(__name__)

#: ``agent_slug`` recorded on an upload's row: nobody's agent wrote it.
UPLOAD_WRITER = "user-upload"

_MAX_NAME_CHARS = 200


@dataclass(frozen=True)
class StoredUpload:
    """One upload as it now lives in the conversation's files."""

    message_id: str
    name: str
    path: str
    mime_type: str


def _safe_name(raw: object) -> str | None:
    """A file name that is one legal path segment, or None.

    Strips any directory part a client might send, then the characters the
    path normaliser refuses (control characters, a leading dot).
    """
    if not isinstance(raw, str):
        return None
    name = PurePosixPath(raw.replace("\\", "/")).name.strip()
    name = "".join(ch for ch in name if ord(ch) >= 32 and ord(ch) != 127).lstrip(".").strip()
    if not name or name in (".", ".."):
        return None
    return name[:_MAX_NAME_CHARS]


def _decoded(attachment: Mapping[str, Any]) -> bytes | None:
    """The attachment's bytes when present and matching its declared hash and size."""
    encoded = attachment.get("data_base64")
    if not isinstance(encoded, str) or not encoded:
        return None
    try:
        data = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError):
        return None
    declared_sha = attachment.get("sha256")
    if (
        isinstance(declared_sha, str)
        and declared_sha
        and (hashlib.sha256(data).hexdigest() != declared_sha.lower())
    ):
        return None
    declared_size = attachment.get("size_bytes")
    if isinstance(declared_size, int) and declared_size != len(data):
        return None
    return data


def _with_id(name: str, attachment_id: object) -> str:
    """``report.pdf`` -> ``report-<id8>.pdf``: the name a same-named second upload gets."""
    suffix = "".join(ch for ch in str(attachment_id or "") if ch.isalnum())[:8] or "copy"
    stem, dot, ext = name.rpartition(".")
    return f"{stem}-{suffix}.{ext}" if dot and stem else f"{name}-{suffix}"


async def ingest_uploads(
    store: ConversationFileStore,
    *,
    client_id: str,
    conversation_id: str,
    messages: Sequence[Mapping[str, Any]],
) -> list[StoredUpload]:
    """Write every inline upload of ``messages`` under ``/conversation/input/``.

    Returns what is stored, in message order, so the run route can tell the
    model where each upload is.
    """
    stored: list[StoredUpload] = []
    skipped = 0
    for message in messages:
        attachments = message.get("attachments")
        if message.get("role") != "user" or not isinstance(attachments, list):
            continue
        for attachment in attachments:
            if not isinstance(attachment, Mapping) or attachment.get("origin") == "generated":
                continue
            upload = await _store_one(
                store, client_id, conversation_id, str(message.get("id") or ""), attachment
            )
            if upload is None:
                skipped += 1
            else:
                stored.append(upload)
    if stored or skipped:
        logger.info(
            "conversation_uploads_ingested",
            "Wrote the request's uploads into the conversation's input folder",
            stored=len(stored),
            skipped=skipped,
        )
    return stored


async def _store_one(
    store: ConversationFileStore,
    client_id: str,
    conversation_id: str,
    message_id: str,
    attachment: Mapping[str, Any],
) -> StoredUpload | None:
    name = _safe_name(attachment.get("name"))
    data = _decoded(attachment)
    if name is None or data is None:
        reason = "name" if name is None else attachment.get("omitted") or "payload"
        logger.warning("conversation_upload_skipped", "Skipped an upload", reason=str(reason)[:32])
        return None
    if len(data) > settings.conversation_files.max_file_bytes:
        logger.warning("conversation_upload_skipped", "Skipped an upload", reason="file_cap")
        return None
    sha256 = hashlib.sha256(data).hexdigest()
    for candidate in (name, _with_id(name, attachment.get("id"))):
        try:
            path = paths.normalise(f"{paths.INPUT_PREFIX}{candidate}")
        except paths.InvalidPath:
            logger.warning("conversation_upload_skipped", "Skipped an upload", reason="name")
            return None
        existing = await store.stat(client_id, conversation_id, path)
        if existing is not None and existing.sha256 != sha256:
            continue  # another file has this name: try the id-suffixed one
        if existing is None:
            outcome = await store.replace(
                client_id, conversation_id, path, data, agent_slug=UPLOAD_WRITER
            )
            if outcome != "ok":
                logger.warning("conversation_upload_skipped", "Skipped an upload", reason=outcome)
                return None
        mime = attachment.get("mime_type")
        return StoredUpload(
            message_id=message_id,
            name=candidate,
            path=path,
            mime_type=mime if isinstance(mime, str) and mime else "application/octet-stream",
        )
    logger.warning("conversation_upload_skipped", "Skipped an upload", reason="name_taken")
    return None


__all__ = ["UPLOAD_WRITER", "StoredUpload", "ingest_uploads"]
