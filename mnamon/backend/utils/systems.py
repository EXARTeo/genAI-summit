"""Systems (audited AI systems) and the request side of workspace file writes.

Systems are NOT scoped by ``X-Client-Id``: every caller sees every system
(a deliberate exception to the client-isolation rule, for now). Attachments
copied into a system folder still have to belong to the caller.
"""

from typing import Any

from fastapi import HTTPException, Request, status
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import (
    AttachmentTable,
    BlobTable,
    ConversationTable,
    MessageTable,
    SystemTable,
    WorkspaceFileTable,
)
from core.settings import settings
from schema.systems import FileTextIn, SystemIn, SystemPatch
from utils.workspace import normalize_path, put_file, system_namespace


def actor_for(client_id: str) -> str:
    return f"client:{client_id}"


async def list_systems(db: AsyncSession) -> list[SystemTable]:
    return list((await db.scalars(select(SystemTable).order_by(SystemTable.id))).all())


async def create_system(db: AsyncSession, payload: SystemIn) -> SystemTable:
    if await db.get(SystemTable, payload.id) is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="System already exists.")
    system = SystemTable(id=payload.id, name=payload.name, status=payload.status, data=payload.data)
    db.add(system)
    try:
        await db.flush()
    except IntegrityError as exc:
        raise HTTPException(status_code=409, detail="System already exists.") from exc
    return system


def patch_system(system: SystemTable, payload: SystemPatch) -> None:
    if payload.name is not None:
        system.name = payload.name
    if payload.status is not None:
        system.status = payload.status
    if payload.data is not None:
        system.data = {**(system.data or {}), **payload.data}


async def read_write_request(request: Request) -> tuple[bytes, str | None, str | None, dict]:
    """The body of a file write: multipart (``file`` + optional ``reason``,
    ``contentType``) or JSON :class:`FileTextIn`. Returns
    ``(content, content_type, reason, meta)``."""
    content_type_header = request.headers.get("content-type", "")
    if content_type_header.startswith("multipart/form-data"):
        form = await request.form()
        upload = form.get("file")
        if upload is None or isinstance(upload, str):
            raise HTTPException(status_code=422, detail="Multipart write needs a 'file' part.")
        limit = settings.workspace.max_file_bytes
        content = await upload.read(limit + 1)
        if len(content) > limit:
            raise HTTPException(status_code=413, detail="File exceeds the workspace size limit.")
        reason = form.get("reason")
        declared = form.get("contentType")
        return (
            content,
            declared if isinstance(declared, str) and declared else upload.content_type,
            reason if isinstance(reason, str) and reason else None,
            {},
        )
    try:
        payload = FileTextIn.model_validate(await request.json())
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.errors(include_url=False)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Body must be JSON or multipart.") from exc
    return payload.content.encode("utf-8"), payload.contentType, payload.reason, payload.data


async def copy_attachment_to_system(
    db: AsyncSession,
    *,
    client_id: str,
    system_id: str,
    attachment_id: str,
    path: str | None,
    reason: str | None,
) -> tuple[WorkspaceFileTable, bool]:
    """Copy one of the caller's attachments into ``system:<id>`` (404 if not theirs)."""
    row = (
        await db.execute(
            select(AttachmentTable.file_name, AttachmentTable.mime_type, BlobTable.data)
            .join(BlobTable, BlobTable.id == AttachmentTable.blob_id)
            .join(MessageTable, MessageTable.id == AttachmentTable.message_id)
            .join(ConversationTable, ConversationTable.id == MessageTable.conversation_id)
            .where(AttachmentTable.id == attachment_id, ConversationTable.client_id == client_id)
        )
    ).one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Attachment not found or not accessible.")
    file_name, mime, data = row
    safe_name = "".join(c if c.isalnum() or c in "._-" else "_" for c in file_name) or "file"
    target = normalize_path(path) if path else f"uploads/{safe_name}"
    meta: dict[str, Any] = {"source": {"attachment_id": attachment_id, "file_name": file_name}}
    return await put_file(
        db,
        namespace=system_namespace(system_id),
        path=target,
        content=data.tobytes() if isinstance(data, memoryview) else bytes(data),
        content_type=mime,
        actor=actor_for(client_id),
        reason=reason or "copied from a conversation attachment",
        meta=meta,
    )
