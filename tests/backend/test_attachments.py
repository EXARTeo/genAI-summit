"""Attachments: upload validation, streamed download / inline preview (ranges,
headers, active content), the image gallery and blob clean-up."""

from __future__ import annotations

import base64

import pytest
from conftest import AGENT_SLUG, CLIENT_ID
from fastapi import HTTPException
from fastapi.responses import StreamingResponse
from pydantic import ValidationError
from sqlalchemy import delete, func, select

import schema.attachments as attachment_schema
from core.database import AttachmentTable, BlobTable, ConversationTable, MessageTable
from core.settings import settings
from schema.attachments import AttachmentIn
from schema.messages import MessageIn
from utils.attachments import ACTIVE_CONTENT_MIMES, encode_disposition, stream_blob_response

DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


async def _seed_attachment(
    session_factory, *, file_name: str, mime_type: str, data: bytes, client_id: str = CLIENT_ID
) -> dict[str, str]:
    async with session_factory() as session:
        conversation = ConversationTable(
            client_id=client_id,
            agent_slug=AGENT_SLUG,
            title="Attachment conversation",
            last_message_preview=file_name,
        )
        session.add(conversation)
        await session.flush()
        message = MessageTable(conversation_id=conversation.id, sender="user", content=file_name)
        session.add(message)
        await session.flush()
        blob = BlobTable(data=data)
        attachment = AttachmentTable(
            message_id=message.id,
            file_name=file_name,
            mime_type=mime_type,
            size_bytes=len(data),
            blob=blob,
        )
        session.add(attachment)
        await session.commit()
        return {
            "conversation_id": conversation.id,
            "message_id": message.id,
            "attachment_id": attachment.id,
            "blob_id": blob.id,
        }


def _url(kind: str, seed: dict[str, str], blob_id: str | None = None) -> str:
    return (
        f"/v1/attachments/{kind}/{seed['conversation_id']}/{seed['message_id']}/"
        f"{blob_id or seed['blob_id']}"
    )


async def _drain(response: StreamingResponse) -> bytes:
    return b"".join([chunk async for chunk in response.body_iterator])


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


# --- upload validation --------------------------------------------------------


def test_attachment_in_decodes_once_and_records_the_size():
    item = AttachmentIn(name=" notes.txt ", mime="Text/Plain", dataB64=_b64(b"hello"))

    assert item.name == "notes.txt"
    assert item.mime == "text/plain"
    assert item.size == 5
    assert item.raw_bytes() == b"hello"


def test_an_oversized_upload_is_refused_before_it_is_decoded(monkeypatch):
    monkeypatch.setattr(settings.attachments, "max_size_bytes", 6)

    def must_not_decode(*_args, **_kwargs):
        raise AssertionError("decoded an upload that could not fit")

    monkeypatch.setattr(attachment_schema.base64, "b64decode", must_not_decode)

    with pytest.raises(ValidationError, match="exceeds"):
        AttachmentIn(name="big.bin", mime="application/octet-stream", dataB64=_b64(b"x" * 30))
    with pytest.raises(ValidationError, match="exceeds"):
        AttachmentIn(name="big.bin", mime="application/octet-stream", dataB64="QQ==", size=7)


@pytest.mark.parametrize(
    "mime", ["", "text", "text/plain; charset=utf-8", "text/<script>", "a/b/c", "x" * 300]
)
def test_an_invalid_mime_is_refused(mime):
    with pytest.raises(ValidationError):
        AttachmentIn(name="f.txt", mime=mime, dataB64=_b64(b"hi"))


@pytest.mark.parametrize("data", ["not-base64", "aGk", "aG k=", ""])
def test_invalid_or_empty_base64_is_refused(data):
    with pytest.raises(ValidationError):
        AttachmentIn(name="f.txt", mime="text/plain", dataB64=data)


def test_a_size_that_does_not_match_the_payload_is_refused():
    with pytest.raises(ValidationError, match="does not match"):
        AttachmentIn(name="f.txt", mime="text/plain", dataB64=_b64(b"hi"), size=3)


def test_too_many_attachments_are_refused_before_any_is_decoded(monkeypatch):
    monkeypatch.setattr(settings.attachments, "max_per_message", 2)
    item = {"name": "f.txt", "mime": "text/plain", "dataB64": "@@not base64@@"}

    with pytest.raises(ValidationError, match="No more than 2"):
        MessageIn(sender="user", content="x", attachments=[item, item, item])


def test_the_total_payload_limit_is_checked_on_the_encoded_length(monkeypatch):
    monkeypatch.setattr(settings.attachments, "max_total_bytes", 6)
    item = {"name": "f.txt", "mime": "text/plain", "dataB64": _b64(b"abcd")}

    with pytest.raises(ValidationError, match="Total attachment payload"):
        MessageIn(sender="user", content="x", attachments=[item, item])


# --- gallery --------------------------------------------------------------------


async def test_get_images_batch_returns_base64_payloads(client, session_factory):
    image_bytes = b"png-bytes"
    seed = await _seed_attachment(
        session_factory, file_name="chart.png", mime_type="image/png", data=image_bytes
    )
    await _seed_attachment(
        session_factory, file_name="notes.txt", mime_type="text/plain", data=b"x"
    )

    response = await client.get("/v1/attachments/images?page=1&size=10")

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 1
    item = payload["items"][0]
    assert item["attachmentId"] == seed["attachment_id"]
    assert item["blobId"] == seed["blob_id"]
    assert item["conversationId"] == seed["conversation_id"]
    assert item["messageId"] == seed["message_id"]
    assert item["dataB64"] == _b64(image_bytes)


# --- download / preview -----------------------------------------------------------


async def test_download_blob_stream_supports_full_and_partial_reads(client, session_factory):
    blob_bytes = b"hello attachment"
    seed = await _seed_attachment(
        session_factory, file_name="notes.txt", mime_type="text/plain", data=blob_bytes
    )

    full = await client.get(_url("download", seed))
    partial = await client.get(_url("download", seed), headers={"Range": "bytes=0-4"})
    open_ended = await client.get(_url("download", seed), headers={"Range": "bytes=12-"})

    assert full.status_code == 200
    assert full.content == blob_bytes
    assert full.headers["content-length"] == str(len(blob_bytes))
    assert partial.status_code == 206
    assert partial.content == b"hello"
    assert partial.headers["content-range"] == f"bytes 0-4/{len(blob_bytes)}"
    assert open_ended.status_code == 206
    assert open_ended.content == b"ment"


@pytest.mark.parametrize("range_header", ["bytes=99-120", "items=0-4", "bytes=5-2", "bytes=a-b"])
async def test_download_blob_stream_rejects_invalid_ranges(client, session_factory, range_header):
    seed = await _seed_attachment(
        session_factory, file_name="notes.txt", mime_type="text/plain", data=b"hello attachment"
    )

    response = await client.get(_url("download", seed), headers={"Range": range_header})

    assert response.status_code == 416
    assert response.headers["content-range"] == "bytes */16"


async def test_preview_blob_inline_allows_non_image_blobs(client, session_factory):
    pdf = await _seed_attachment(
        session_factory, file_name="brief.pdf", mime_type="application/pdf", data=b"%PDF test"
    )
    txt = await _seed_attachment(
        session_factory, file_name="notes.txt", mime_type="text/plain", data=b"plain text"
    )

    pdf_response = await client.get(_url("preview", pdf))
    txt_response = await client.get(_url("preview", txt))

    assert pdf_response.status_code == 200
    assert pdf_response.headers["content-type"].startswith("application/pdf")
    assert pdf_response.headers["cache-control"] == "private, max-age=300"
    assert pdf_response.headers["content-security-policy"] == "sandbox; default-src 'none'"
    assert pdf_response.headers["content-disposition"].startswith("inline")
    assert pdf_response.headers["x-content-type-options"] == "nosniff"
    assert txt_response.status_code == 200
    assert txt_response.content == b"plain text"
    assert txt_response.headers["content-type"].startswith("text/plain")


async def test_a_docx_is_previewed_inline_without_a_token(client, session_factory):
    seed = await _seed_attachment(
        session_factory, file_name="report.docx", mime_type=DOCX_MIME, data=b"PK\x03\x04docx"
    )

    response = await client.get(_url("preview", seed))

    assert response.status_code == 200
    assert response.content == b"PK\x03\x04docx"
    assert response.headers["content-type"] == DOCX_MIME
    assert response.headers["content-disposition"].startswith("inline")


async def test_download_allows_images_but_preview_refuses_them(client, session_factory):
    seed = await _seed_attachment(
        session_factory, file_name="chart.png", mime_type="image/png", data=b"image bytes"
    )

    download = await client.get(_url("download", seed))
    preview = await client.get(_url("preview", seed))
    missing = await client.get(_url("download", seed, blob_id="missing-blob"))

    assert download.status_code == 200
    assert download.content == b"image bytes"
    assert download.headers["content-disposition"].startswith("attachment")
    assert download.headers["x-content-type-options"] == "nosniff"
    assert "content-security-policy" not in download.headers
    assert preview.status_code == 400
    assert preview.json()["detail"] == "Images are not served by this endpoint."
    assert missing.status_code == 404
    assert missing.json()["detail"] == "Blob not found or not accessible."


@pytest.mark.parametrize(
    ("file_name", "mime"),
    [
        ("report.html", "text/html"),
        ("report.html", "text/html; charset=utf-8"),
        ("page.xhtml", "application/xhtml+xml"),
        ("x.js", "text/javascript"),
        ("x.js", "application/javascript"),
        ("data.xml", "application/xml"),
    ],
)
async def test_active_content_is_never_served_inline(client, session_factory, file_name, mime):
    seed = await _seed_attachment(
        session_factory, file_name=file_name, mime_type=mime, data=b"<script>alert(1)</script>"
    )

    response = await client.get(_url("preview", seed))

    assert response.status_code == 200
    assert response.headers["content-disposition"].startswith("attachment")
    assert response.headers["content-security-policy"] == "sandbox; default-src 'none'"


def test_the_active_types_cover_html_svg_js_and_xml():
    assert {
        "text/html",
        "image/svg+xml",
        "text/javascript",
        "application/javascript",
        "application/xml",
    } <= ACTIVE_CONTENT_MIMES


async def test_a_blob_is_only_reachable_through_its_own_message(client, session_factory):
    first = await _seed_attachment(
        session_factory, file_name="a.txt", mime_type="text/plain", data=b"a"
    )
    second = await _seed_attachment(
        session_factory, file_name="b.txt", mime_type="text/plain", data=b"b"
    )

    response = await client.get(_url("download", first, blob_id=second["blob_id"]))

    assert response.status_code == 404


# --- encode_disposition -----------------------------------------------------------


def test_encode_disposition_default_names():
    assert 'filename="download"' in encode_disposition(None, "attachment")
    assert encode_disposition(None, "attachment").startswith("attachment;")
    assert 'filename="document.pdf"' in encode_disposition(None, "inline")


def test_encode_disposition_sanitises_path_separators_quotes_and_newlines():
    header = encode_disposition('a/b\\c".txt', "attachment")
    assert '"a_b_c' in header

    injected = encode_disposition("evil\r\nSet-Cookie: x=1.txt", "attachment")
    assert "\r" not in injected and "\n" not in injected


def test_encode_disposition_unicode_falls_back_to_ascii_then_encodes():
    header = encode_disposition("résumé.txt", "attachment")
    assert 'filename="rsum.txt"' in header
    assert "filename*=UTF-8''r%C3%A9sum%C3%A9.txt" in header


# --- stream_blob_response, called directly -----------------------------------------


async def test_stream_blob_bodies(session_factory):
    data = b"0123456789"
    seed = await _seed_attachment(
        session_factory, file_name="f.bin", mime_type="application/octet-stream", data=data
    )
    common = {
        "client_id": CLIENT_ID,
        "conversation_id": seed["conversation_id"],
        "message_id": seed["message_id"],
        "blob_id": seed["blob_id"],
        "disposition": "attachment",
    }
    async with session_factory() as session:
        full = await stream_blob_response(range_header=None, db=session, **common)
        assert full.status_code == 200
        assert await _drain(full) == data

        partial = await stream_blob_response(range_header="bytes=2-5", db=session, **common)
        assert partial.status_code == 206
        assert partial.headers["content-length"] == "4"
        assert await _drain(partial) == b"2345"


async def test_stream_blob_reads_in_chunks(session_factory, monkeypatch):
    monkeypatch.setattr(settings.attachments, "stream_chunk_bytes", 3)
    data = b"abcdefghij"
    seed = await _seed_attachment(
        session_factory, file_name="f.bin", mime_type="application/octet-stream", data=data
    )
    async with session_factory() as session:
        response = await stream_blob_response(
            client_id=CLIENT_ID,
            conversation_id=seed["conversation_id"],
            message_id=seed["message_id"],
            blob_id=seed["blob_id"],
            range_header=None,
            db=session,
            disposition="attachment",
        )
        chunks = [chunk async for chunk in response.body_iterator]

    assert chunks == [b"abc", b"def", b"ghi", b"j"]


async def test_stream_blob_of_another_client_is_404(session_factory):
    seed = await _seed_attachment(
        session_factory, file_name="f.bin", mime_type="application/octet-stream", data=b"data"
    )
    async with session_factory() as session:
        with pytest.raises(HTTPException) as exc:
            await stream_blob_response(
                client_id="someone-else",
                conversation_id=seed["conversation_id"],
                message_id=seed["message_id"],
                blob_id=seed["blob_id"],
                range_header=None,
                db=session,
                disposition="attachment",
            )
    assert exc.value.status_code == 404


# --- blob clean-up ------------------------------------------------------------------


async def test_deleting_an_attachment_deletes_its_blob_and_only_its_blob(session_factory):
    seed = await _seed_attachment(
        session_factory, file_name="f.txt", mime_type="text/plain", data=b"bytes"
    )
    async with session_factory() as session:
        keep = BlobTable(data=b"someone else's bytes")
        session.add(keep)
        await session.commit()
        keep_id = keep.id

    async with session_factory() as session:
        await session.execute(
            delete(AttachmentTable).where(AttachmentTable.id == seed["attachment_id"])
        )
        await session.commit()

    async with session_factory() as session:
        remaining = await session.scalar(
            select(func.count())
            .select_from(BlobTable)
            .where(BlobTable.id.in_([seed["blob_id"], keep_id]))
        )
        kept = await session.get(BlobTable, keep_id)
    assert remaining == 1
    assert kept is not None
