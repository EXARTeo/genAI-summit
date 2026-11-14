"""Serving stored files: streamed downloads and inline previews (HTTP byte
ranges, chunked reads from the database), and the caller's image gallery.

Every lookup joins blob -> attachment -> message -> conversation and filters
on the caller's client id, so a blob id alone never reaches another client's
file. A miss is a 404 either way.
"""

import asyncio
from collections.abc import AsyncIterator
from typing import Literal
from urllib.parse import quote

from fastapi import HTTPException, Response, status
from fastapi.responses import StreamingResponse
from fastapi_pagination import Page, Params, create_page
from sqlalchemy import RowMapping, desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import AttachmentTable, BlobTable, ConversationTable, MessageTable
from core.logging import StreamMetrics, get_context, get_logger, set_context
from core.settings import settings
from schema.attachments import ImageOut

logger = get_logger(__name__)

Disposition = Literal["attachment", "inline"]

#: MIME types a browser executes or renders as a document: never served inline.
ACTIVE_CONTENT_MIMES = frozenset(
    {
        "text/html",
        "application/xhtml+xml",
        "image/svg+xml",
        "text/javascript",
        "application/javascript",
        "application/ecmascript",
        "text/ecmascript",
        "application/xml",
        "text/xml",
    }
)


def encode_disposition(name: str | None, disposition: Disposition) -> str:
    """A ``Content-Disposition`` header that cannot be broken by the file name:
    path separators and quotes replaced, an ASCII ``filename`` fallback, and
    the full name percent-encoded in ``filename*`` (RFC 6266 / 5987)."""
    fallback_name = "document.pdf" if disposition == "inline" else "download"
    safe_name = (name or fallback_name).replace("\\", "_").replace("/", "_").replace(
        '"', "'"
    ).strip() or fallback_name
    # Control characters (CR/LF above all) never reach a header.
    safe_name = "".join(ch for ch in safe_name if ch.isprintable()) or fallback_name
    ascii_name = safe_name.encode("ascii", "ignore").decode("ascii").strip() or fallback_name
    return f"{disposition}; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(safe_name)}"


async def _get_attachment_blob_row(
    *,
    client_id: str,
    conversation_id: str,
    message_id: str,
    blob_id: str,
    db: AsyncSession,
) -> RowMapping:
    """The attachment's name, MIME and size (never its bytes), if the caller owns it."""
    row = (
        (
            await db.execute(
                select(
                    AttachmentTable.mime_type,
                    AttachmentTable.file_name,
                    func.coalesce(AttachmentTable.size_bytes, func.length(BlobTable.data)).label(
                        "blob_size"
                    ),
                )
                .select_from(BlobTable)
                .join(AttachmentTable, AttachmentTable.blob_id == BlobTable.id)
                .join(MessageTable, MessageTable.id == AttachmentTable.message_id)
                .join(ConversationTable, ConversationTable.id == MessageTable.conversation_id)
                .where(
                    BlobTable.id == blob_id,
                    MessageTable.id == message_id,
                    ConversationTable.id == conversation_id,
                    ConversationTable.client_id == client_id,
                )
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Blob not found or not accessible.")
    return row


def _parse_range(range_header: str, file_size: int) -> tuple[int, int] | None:
    """``bytes=start-end`` (either end open) within the file, or None if invalid."""
    try:
        units, rng = range_header.split("=", 1)
        if units.strip().lower() != "bytes":
            return None
        start_s, end_s = (part.strip() for part in rng.split("-", 1))
        start = int(start_s) if start_s else 0
        end = int(end_s) if end_s else file_size - 1
    except ValueError:
        return None
    if start < 0 or start > end or end >= file_size:
        return None
    return start, end


async def stream_blob_response(
    *,
    client_id: str,
    conversation_id: str,
    message_id: str,
    blob_id: str,
    range_header: str | None,
    db: AsyncSession,
    disposition: Disposition,
) -> Response:
    """Stream a blob in chunks (200, or 206 for a byte range; 416 for a bad one).

    ``inline`` is the in-app preview: images are refused (the gallery serves
    them), active content is downgraded to ``attachment``, and the response
    carries a sandbox CSP so, opened as a page, it runs nothing. Every
    response is ``nosniff``.
    """
    set_context(conversation_id=conversation_id, message_id=message_id)
    request_context = get_context()

    row = await _get_attachment_blob_row(
        client_id=client_id,
        conversation_id=conversation_id,
        message_id=message_id,
        blob_id=blob_id,
        db=db,
    )
    mime: str | None = row["mime_type"]
    file_name: str | None = row["file_name"]
    file_size: int | None = row["blob_size"]

    # An inline image (an SVG above all) could render as a page; as a download
    # (attachment + nosniff) it is only saved to disk.
    if mime and mime.startswith("image/") and disposition != "attachment":
        raise HTTPException(status_code=400, detail="Images are not served by this endpoint.")

    if file_size is None:
        logger.error(
            "blob_size_unavailable",
            "Blob size could not be determined before streaming",
            context=request_context,
            blob_id=blob_id,
            disposition=disposition,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="The attachment could not be prepared for download. Please try again.",
        )

    inline = disposition == "inline"
    # A type a browser would run is never served inline: the stored MIME is the
    # uploader's word, or derived from an agent's file name.
    if inline and (mime or "").split(";")[0].strip().lower() in ACTIVE_CONTENT_MIMES:
        disposition = "attachment"
    headers = {
        "Accept-Ranges": "bytes",
        "Content-Disposition": encode_disposition(file_name, disposition),
        "X-Content-Type-Options": "nosniff",
    }
    if inline:
        headers["Cache-Control"] = (
            f"private, max-age={settings.attachments.inline_cache_max_age_seconds}"
        )
        # The UI fetch()es a preview and renders the bytes itself; opened
        # directly as a page it runs nothing and loads nothing.
        headers["Content-Security-Policy"] = "sandbox; default-src 'none'"

    chunk_size = settings.attachments.stream_chunk_bytes

    async def stream_range(start: int, end: int, *, partial: bool) -> AsyncIterator[bytes]:
        metrics = StreamMetrics()
        pos = start
        completed = False
        caught_exc: BaseException | None = None
        try:
            while pos <= end:
                length = min(chunk_size, end - pos + 1)
                chunk = await db.scalar(
                    select(func.substring(BlobTable.data, pos + 1, length)).where(
                        BlobTable.id == blob_id
                    )
                )
                if not chunk:
                    break
                chunk = chunk.tobytes() if isinstance(chunk, memoryview) else bytes(chunk)
                yield metrics.track(chunk)
                pos += len(chunk)
            completed = True
        except BaseException as exc:
            caught_exc = exc
            raise
        finally:
            fields = {
                "blob_id": blob_id,
                "file_size": file_size,
                "partial": partial,
                "served_bytes": metrics.bytes_forwarded,
                "chunk_count": metrics.chunk_count,
                "first_byte_latency_ms": metrics.first_byte_latency_ms,
                "total_stream_duration_ms": metrics.snapshot()["total_stream_duration_ms"],
                "disposition": disposition,
            }
            if completed:
                logger.info(
                    "blob_download_completed",
                    "Blob download completed",
                    context=request_context,
                    **fields,
                )
            elif isinstance(caught_exc, asyncio.CancelledError | GeneratorExit):
                logger.warning(
                    "blob_download_aborted",
                    "Blob download aborted by client",
                    context=request_context,
                    **fields,
                )
            else:
                logger.error(
                    "blob_download_error",
                    "Blob download failed",
                    exc_info=True,
                    context=request_context,
                    error=str(caught_exc) if caught_exc else None,
                    **fields,
                )

    media_type = mime or "application/octet-stream"
    if not range_header:
        logger.info(
            "blob_download_started",
            "Blob download started",
            context=request_context,
            blob_id=blob_id,
            file_size=file_size,
            partial=False,
            disposition=disposition,
        )
        return StreamingResponse(
            stream_range(0, file_size - 1, partial=False),
            media_type=media_type,
            headers={**headers, "Content-Length": str(file_size)},
        )

    byte_range = _parse_range(range_header, file_size)
    if byte_range is None:
        logger.warning(
            "blob_range_invalid",
            "Blob download received an invalid range header",
            context=request_context,
            blob_id=blob_id,
            file_size=file_size,
            disposition=disposition,
        )
        return Response(status_code=416, headers={"Content-Range": f"bytes */{file_size}"})

    start, end = byte_range
    logger.info(
        "blob_download_started",
        "Blob partial download started",
        context=request_context,
        blob_id=blob_id,
        file_size=file_size,
        partial=True,
        range_start=start,
        range_end=end,
        disposition=disposition,
    )
    return StreamingResponse(
        stream_range(start, end, partial=True),
        status_code=206,
        media_type=media_type,
        headers={
            **headers,
            "Content-Range": f"bytes {start}-{end}/{file_size}",
            "Content-Length": str(end - start + 1),
        },
    )


async def list_client_images(db: AsyncSession, client_id: str, params: Params) -> Page[ImageOut]:
    """A page of the caller's image attachments, newest first, base64 included.

    Base64 is produced by the database, and only for the rows of the page.
    """
    raw_params = params.to_raw_params()
    rows = (
        await db.execute(
            select(
                BlobTable.id.label("blob_id"),
                AttachmentTable.id.label("attachment_id"),
                MessageTable.conversation_id,
                AttachmentTable.message_id,
                AttachmentTable.file_name,
                AttachmentTable.mime_type,
                AttachmentTable.created_at,
                func.replace(func.encode(BlobTable.data, "base64"), "\n", "").label("data_b64"),
                func.count().over().label("total_count"),
            )
            .join(AttachmentTable, AttachmentTable.blob_id == BlobTable.id)
            .join(MessageTable, MessageTable.id == AttachmentTable.message_id)
            .join(ConversationTable, ConversationTable.id == MessageTable.conversation_id)
            .where(
                ConversationTable.client_id == client_id,
                AttachmentTable.mime_type.like("image/%"),
            )
            .order_by(desc(AttachmentTable.created_at), AttachmentTable.id)
            .limit(raw_params.limit)
            .offset(raw_params.offset)
        )
    ).all()
    total = rows[0].total_count if rows else 0
    items = [
        ImageOut(
            blob_id=r.blob_id,
            attachment_id=r.attachment_id,
            conversation_id=r.conversation_id,
            message_id=r.message_id,
            file_name=r.file_name,
            mime_type=r.mime_type,
            created_at=r.created_at,
            dataB64=r.data_b64,
        )
        for r in rows
    ]
    return create_page(items, total=total, params=params)
