"""``/conversation/input/``: the uploads, written from the run request.

The backend sends every non-image file (and any image past its inline budget)
as an inline ``attachments`` entry (``docs/contracts/agents-contract.md`` § Attachment).
``ingest_uploads`` writes each one into the conversation's files before the run
starts. Pinned here:

* what is written, where, and what is returned (``StoredUpload``);
* idempotency: a full-history seed re-sends every earlier upload, and an
  unchanged one must not be rewritten;
* a second, different file under a taken name keeps both (``<stem>-<id8>``);
* everything unusable is skipped, never a failed run: a hash or size mismatch,
  a missing payload (``omitted: budget``), an unusable name, a file over the
  per-file cap, a generated file, a non-user message;
* once written, uploads are read-only to the agent, listed by
  ``ConversationFiles.entries`` and sent into the sandbox with each command.
"""

from __future__ import annotations

import base64
import hashlib
import json

import httpx
import pytest
from conftest import CLIENT_ID, CONVERSATION_ID, OTHER_CLIENT_ID

from core.settings import settings
from harness.conversation_files import ConversationFilesBackend
from harness.conversation_files.inputs import UPLOAD_WRITER, StoredUpload, ingest_uploads
from harness.filesystem.sandbox_backend import RemoteSandboxBackend

RUNNER_URL = "https://sandbox-runner.test:8090"
CSV = b"col1,col2\n1,2\n"
PDF = b"%PDF-1.7 not really a pdf"


def attachment(
    name: object = "data.csv",
    data: bytes = CSV,
    *,
    attachment_id: str = "att-0001-aaaa",
    mime_type: str | None = "text/csv",
    **overrides: object,
) -> dict:
    """One contract ``Attachment`` with its bytes inline and honest metadata."""
    body: dict = {
        "id": attachment_id,
        "name": name,
        "mime_type": mime_type,
        "size_bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "origin": "upload",
        "data_base64": base64.b64encode(data).decode("ascii"),
    }
    body.update(overrides)
    return body


def user_message(*attachments: dict, message_id: str = "m1", role: str = "user") -> dict:
    return {
        "id": message_id,
        "role": role,
        "content": "see attached",
        "attachments": [*attachments],
    }


async def ingest(store, *messages: dict, client_id: str = CLIENT_ID) -> list[StoredUpload]:
    return await ingest_uploads(
        store, client_id=client_id, conversation_id=CONVERSATION_ID, messages=list(messages)
    )


class _CountingStore:
    """Wraps the in-memory store and counts writes, to prove a no-op is a no-op."""

    def __init__(self, inner) -> None:
        self._inner = inner
        self.writes = 0

    async def stat(self, *args):
        return await self._inner.stat(*args)

    async def replace(self, *args, **kwargs):
        self.writes += 1
        return await self._inner.replace(*args, **kwargs)


# ---------------------------------------------------------------------------
# What is written
# ---------------------------------------------------------------------------
async def test_an_upload_lands_under_input_and_is_returned(memory_file_store):
    stored = await ingest(memory_file_store, user_message(attachment()))

    assert stored == [
        StoredUpload(
            message_id="m1",
            name="data.csv",
            path="/conversation/input/data.csv",
            mime_type="text/csv",
        )
    ]
    path = "/conversation/input/data.csv"
    assert await memory_file_store.read(CLIENT_ID, CONVERSATION_ID, path) == CSV
    # Provenance: nobody's agent wrote it.
    entry = await memory_file_store.stat(CLIENT_ID, CONVERSATION_ID, path)
    assert entry.agent_slug == UPLOAD_WRITER


async def test_uploads_are_returned_in_message_order(memory_file_store):
    stored = await ingest(
        memory_file_store,
        user_message(attachment("a.csv"), attachment("b.pdf", PDF), message_id="m1"),
        user_message(attachment("c.csv", b"c"), message_id="m2"),
    )

    assert [(s.message_id, s.name) for s in stored] == [
        ("m1", "a.csv"),
        ("m1", "b.pdf"),
        ("m2", "c.csv"),
    ]


async def test_a_missing_mime_type_falls_back_to_octet_stream(memory_file_store):
    [stored] = await ingest(memory_file_store, user_message(attachment(mime_type=None)))
    assert stored.mime_type == "application/octet-stream"


async def test_a_declared_hash_is_compared_case_insensitively(memory_file_store):
    upper = hashlib.sha256(CSV).hexdigest().upper()
    stored = await ingest(memory_file_store, user_message(attachment(sha256=upper)))
    assert [s.path for s in stored] == ["/conversation/input/data.csv"]


async def test_uploads_are_kept_per_client(memory_file_store):
    """Two browsers in conversations with the same id never see each other's uploads."""
    await ingest(memory_file_store, user_message(attachment()), client_id=CLIENT_ID)

    path = "/conversation/input/data.csv"
    assert await memory_file_store.read(OTHER_CLIENT_ID, CONVERSATION_ID, path) is None


# ---------------------------------------------------------------------------
# Idempotent: a re-sent upload is left alone
# ---------------------------------------------------------------------------
async def test_resending_the_same_upload_writes_nothing(memory_file_store):
    counting = _CountingStore(memory_file_store)
    first = await ingest(counting, user_message(attachment()))
    again = await ingest(counting, user_message(attachment()))

    assert first == again
    assert counting.writes == 1
    assert len(memory_file_store.rows) == 1


async def test_a_different_file_under_a_taken_name_keeps_both(memory_file_store):
    await ingest(memory_file_store, user_message(attachment("report.pdf", PDF)))

    [second] = await ingest(
        memory_file_store,
        user_message(
            attachment("report.pdf", b"another report", attachment_id="9f8e7d6c-5b4a"),
            message_id="m2",
        ),
    )

    # The first eight alphanumerics of the attachment id, before the extension.
    assert second.name == "report-9f8e7d6c.pdf"
    assert second.path == "/conversation/input/report-9f8e7d6c.pdf"
    read = memory_file_store.read
    assert await read(CLIENT_ID, CONVERSATION_ID, "/conversation/input/report.pdf") == PDF
    assert await read(CLIENT_ID, CONVERSATION_ID, second.path) == b"another report"


async def test_a_name_without_an_extension_gets_the_suffix_at_the_end(memory_file_store):
    await ingest(memory_file_store, user_message(attachment("Makefile", b"one")))
    [second] = await ingest(
        memory_file_store, user_message(attachment("Makefile", b"two", attachment_id="abc"))
    )
    assert second.name == "Makefile-abc"


async def test_the_id_suffixed_name_is_idempotent_too(memory_file_store):
    """A history seed re-sends both same-named uploads: neither is duplicated again."""
    messages = [
        user_message(attachment("r.pdf", PDF, attachment_id="first111"), message_id="m1"),
        user_message(attachment("r.pdf", b"other", attachment_id="second22"), message_id="m2"),
    ]
    first = await ingest(memory_file_store, *messages)
    again = await ingest(memory_file_store, *messages)

    assert [s.name for s in first] == ["r.pdf", "r-second22.pdf"]
    assert again == first
    assert len(memory_file_store.rows) == 2


async def test_a_third_different_file_with_the_same_name_and_id_is_skipped(memory_file_store):
    await ingest(memory_file_store, user_message(attachment("r.pdf", b"1", attachment_id="x1")))
    await ingest(memory_file_store, user_message(attachment("r.pdf", b"2", attachment_id="x1")))

    stored = await ingest(
        memory_file_store, user_message(attachment("r.pdf", b"3", attachment_id="x1"))
    )

    assert stored == []
    assert len(memory_file_store.rows) == 2


# ---------------------------------------------------------------------------
# Skipped, never a failed run
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "overrides",
    [
        pytest.param({"sha256": "0" * 64}, id="hash-mismatch"),
        pytest.param({"size_bytes": len(CSV) + 1}, id="size-mismatch"),
        pytest.param({"data_base64": None, "omitted": "budget"}, id="omitted-budget"),
        pytest.param({"data_base64": ""}, id="empty-payload"),
        pytest.param({"data_base64": "%%% not base64 %%%"}, id="bad-base64"),
        pytest.param({"origin": "generated"}, id="generated-file"),
    ],
)
async def test_an_unusable_attachment_is_skipped(memory_file_store, overrides):
    stored = await ingest(
        memory_file_store,
        user_message(attachment(**overrides), attachment("ok.csv", b"fine")),
    )

    # The good one in the same message still lands.
    assert [s.name for s in stored] == ["ok.csv"]
    assert set(memory_file_store.rows) == {(CONVERSATION_ID, "/conversation/input/ok.csv")}


@pytest.mark.parametrize("name", [None, 42, "", "   ", "..", "...", "\x00\x01", "/"])
async def test_an_unusable_name_is_skipped(memory_file_store, name):
    assert await ingest(memory_file_store, user_message(attachment(name))) == []
    assert memory_file_store.rows == {}


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("../../etc/passwd", "passwd"),
        ("C:\\Users\\me\\report.pdf", "report.pdf"),
        (".env", "env"),
        ("tab\there.txt", "tabhere.txt"),
    ],
)
async def test_a_name_is_reduced_to_one_safe_segment(memory_file_store, raw, expected):
    [stored] = await ingest(memory_file_store, user_message(attachment(raw)))

    assert stored.name == expected
    assert stored.path == f"/conversation/input/{expected}"


async def test_a_long_name_is_cut_to_a_storable_length(memory_file_store):
    [stored] = await ingest(memory_file_store, user_message(attachment("x" * 500 + ".csv")))
    assert len(stored.name) == 200


async def test_a_file_over_the_per_file_cap_is_skipped(memory_file_store, monkeypatch):
    monkeypatch.setattr(settings.conversation_files, "max_file_bytes", len(CSV) - 1)
    assert await ingest(memory_file_store, user_message(attachment())) == []
    assert memory_file_store.rows == {}


async def test_only_user_messages_carry_uploads(memory_file_store):
    stored = await ingest(
        memory_file_store,
        user_message(attachment("from-assistant.csv"), role="assistant"),
        {"id": "m3", "role": "user", "content": "no files"},
        {"id": "m4", "role": "user", "content": "odd", "attachments": "not-a-list"},
        user_message("not-a-mapping", attachment("real.csv"), message_id="m5"),
    )

    assert [(s.message_id, s.name) for s in stored] == [("m5", "real.csv")]


# ---------------------------------------------------------------------------
# Once written: read-only, listed, and in the sandbox
# ---------------------------------------------------------------------------
async def test_uploads_are_read_only_to_the_agent(memory_file_store, conversation_files):
    await ingest(memory_file_store, user_message(attachment()))
    backend = ConversationFilesBackend(conversation_files, "/conversation")

    write = await backend.awrite("/input/new.csv", "x")
    edit = await backend.aedit("/input/data.csv", "col1", "hacked")
    [upload] = await backend.aupload_files([("/input/data.csv", b"overwritten")])

    assert "uploads are read-only" in write.error
    assert "uploads are read-only" in edit.error
    assert upload.error == "permission_denied"
    # Reading them is the point.
    assert (await backend.aread("/input/data.csv")).file_data["content"] == CSV.decode()
    path = "/conversation/input/data.csv"
    assert await memory_file_store.read(CLIENT_ID, CONVERSATION_ID, path) == CSV


async def test_uploads_are_listed_through_the_conversation_files(
    memory_file_store, conversation_files
):
    await ingest(memory_file_store, user_message(attachment(), attachment("b.pdf", PDF)))

    entries = await conversation_files.entries("/conversation/input")
    listing = await ConversationFilesBackend(conversation_files, "/conversation").als("/input")

    assert [(e.path, e.size) for e in entries] == [
        ("/conversation/input/b.pdf", len(PDF)),
        ("/conversation/input/data.csv", len(CSV)),
    ]
    assert [e["path"] for e in listing.entries] == ["/input/b.pdf", "/input/data.csv"]


async def test_uploads_travel_into_the_sandbox_with_each_command(
    memory_file_store, conversation_files
):
    await ingest(memory_file_store, user_message(attachment(), attachment("b.pdf", PDF)))
    bodies: list[dict] = []

    def runner(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={"exit_code": 0, "stdout": "", "stderr": "", "truncated": False},
        )

    mount = ConversationFilesBackend(conversation_files, "/conversation")
    sandbox = RemoteSandboxBackend(
        client_id=CLIENT_ID,
        agent_slug=conversation_files.agent_slug,
        conversation_id=CONVERSATION_ID,
        files=conversation_files,
        conversation_mount=mount,
        branch_thread_id="t1",
        runner_url=RUNNER_URL,
        async_transport=httpx.MockTransport(runner),
    )

    result = await sandbox.aexecute("ls input")

    assert result.exit_code == 0
    [body] = bodies
    sent = {f["path"]: base64.b64decode(f["content_b64"]) for f in body["files"]}
    assert sent == {"input/data.csv": CSV, "input/b.pdf": PDF}
