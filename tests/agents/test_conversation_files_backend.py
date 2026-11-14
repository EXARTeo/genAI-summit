"""The deepagents filesystem over a conversation's files.

The agent's file tools read and write rows, so this pins what it sees: the
results and error texts ``FilesystemBackend`` gives (write-once ``write``,
exact-match ``edit``, cat-style ``read`` windows, wcmatch ``glob``, literal
``grep``) behind the same virtual paths, plus what rows add: uploads are rows
under ``input/`` and read-only to the agent, one route for ``/conversation/``
(a grep from the root sees each file once), the offload folders out of reach
of ``/conversation/``'s writes, and a per-file safety cap.

Runs over the in-memory store from ``conftest``.
"""

from __future__ import annotations

import asyncio
import base64
import threading

import pytest
from conftest import CLIENT_ID, CONVERSATION_ID

from core.settings import settings
from harness.conversation_files import ConversationFiles, ConversationFilesBackend, paths
from harness.conversation_files import backend as backend_module
from harness.conversation_files.inputs import UPLOAD_WRITER
from harness.filesystem.workspace import build_workspace_backend
from harness.tools.present_artifact.tool import PresentedFiles, build_present_artifact_tool


@pytest.fixture
def backend(conversation_files):
    """The ``/conversation/`` mount, called as ``CompositeBackend`` calls it."""
    return ConversationFilesBackend(conversation_files, "/conversation")


@pytest.fixture
def composite(conversation_files):
    """The whole mount table of a run, as the agent's tools see it."""
    return build_workspace_backend(
        client_id=CLIENT_ID, agent_slug="assistant", files=conversation_files
    )


async def _upload(store, name: str, data: bytes) -> None:
    """An upload as ``ingest_uploads`` leaves it: a row under input/."""
    path = f"/conversation/input/{name}"
    outcome = await store.replace(CLIENT_ID, CONVERSATION_ID, path, data, agent_slug=UPLOAD_WRITER)
    assert outcome == "ok"


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("/conversation//output/a.md/", "/conversation/output/a.md"),
        ("/conversation/output/Café.md", "/conversation/output/Café.md"),
        # NFC: two spellings of one name are one file.
        ("/conversation/output/Café.md", "/conversation/output/Café.md"),
    ],
)
def test_paths_have_one_spelling(raw, expected):
    assert paths.normalise(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "relative.md",
        "/conversation/../etc/passwd",
        "/conversation/./x",
        "/conversation/.env",
        "/conversation/a\\b",
        "/conversation/a\x00b",
        "/" + "a/" * 40 + "x",
        "/" + "x" * 1100,
    ],
)
def test_unsafe_paths_never_reach_the_table(raw):
    with pytest.raises(paths.InvalidPath):
        paths.normalise(raw)


def test_children_range_never_matches_a_sibling_prefix():
    lower, upper = paths.children_range("/conversation/output")
    assert lower <= "/conversation/output/a.md" < upper
    assert not (lower <= "/conversation/output.md" < upper)
    assert not (lower <= "/conversation/output-old/x" < upper)


# ---------------------------------------------------------------------------
# write / read / edit
# ---------------------------------------------------------------------------
async def test_a_written_file_reads_back_in_windows(backend):
    assert (await backend.awrite("/output/notes.md", "one\ntwo\nthree\n")).error is None

    whole = await backend.aread("/output/notes.md")
    window = await backend.aread("/output/notes.md", offset=1, limit=1)
    past_the_end = await backend.aread("/output/notes.md", offset=9)

    assert whole.file_data == {"content": "one\ntwo\nthree\n", "encoding": "utf-8"}
    assert window.file_data["content"] == "two\n"
    assert past_the_end.error == "Line offset 9 exceeds file length (3 lines)"


async def test_binary_files_read_back_as_base64(backend):
    png = b"\x89PNG\r\n\x1a\nbinary"
    await backend.aupload_files([("/output/chart.png", png)])

    result = await backend.aread("/output/chart.png")

    assert result.file_data["encoding"] == "base64"
    assert base64.b64decode(result.file_data["content"]) == png


async def test_an_empty_file_says_so(backend):
    await backend.awrite("/output/empty.md", "")
    assert "empty contents" in (await backend.aread("/output/empty.md")).file_data["content"]


async def test_write_never_replaces_a_file(backend):
    await backend.awrite("/output/a.md", "first")
    result = await backend.awrite("/output/a.md", "second")

    assert result.error == (
        "Cannot write to /conversation/output/a.md because it already exists. "
        "Read and then make an edit, or write to a new path."
    )
    assert (await backend.aread("/output/a.md")).file_data["content"] == "first"


async def test_a_missing_file_is_not_found(backend):
    result = await backend.aread("/output/nope.md")
    assert result.error == "File '/conversation/output/nope.md' not found"


async def test_an_invalid_path_is_an_error_not_a_raise(backend, memory_file_store):
    assert "Error writing file" in (await backend.awrite("/../etc/passwd", "x")).error
    assert "Error reading file" in (await backend.aread("/output/.secret")).error
    assert memory_file_store.rows == {}


async def test_files_and_directories_cannot_collide(backend):
    await backend.awrite("/output/report", "a file")
    await backend.awrite("/drafts/v1.md", "a draft")

    under_a_file = await backend.awrite("/output/report/part.md", "x")
    over_a_folder = await backend.awrite("/drafts", "x")

    assert "a parent of it is a file" in under_a_file.error
    assert "it is a directory" in over_a_folder.error


async def test_the_mount_root_itself_is_not_a_file(backend):
    assert "it is a directory" in (await backend.awrite("/", "x")).error


async def test_edit_replaces_exactly_as_the_filesystem_backend_does(backend):
    await backend.awrite("/output/a.md", "alpha beta alpha\r\n")

    ambiguous = await backend.aedit("/output/a.md", "alpha", "gamma")
    missing = await backend.aedit("/output/a.md", "delta", "x")
    unique = await backend.aedit("/output/a.md", "beta", "BETA")
    every = await backend.aedit("/output/a.md", "alpha", "omega", replace_all=True)

    assert "appears 2 times" in ambiguous.error
    assert missing.error == "Error: String not found in file: 'delta'"
    assert unique.occurrences == 1
    assert every.occurrences == 2
    # Universal newlines, as text-mode reads give them.
    assert (await backend.aread("/output/a.md")).file_data["content"] == "omega BETA omega\n"


async def test_editing_a_missing_file_is_not_found(backend):
    assert (await backend.aedit("/output/nope.md", "a", "b")).error == (
        "Error: File '/conversation/output/nope.md' not found"
    )


async def test_one_file_has_a_safety_cap(backend, monkeypatch):
    monkeypatch.setattr(settings.conversation_files, "max_file_bytes", 10)

    too_big = await backend.awrite("/output/big.md", "x" * 11)
    await backend.awrite("/output/small.md", "x" * 10)
    grown = await backend.aedit("/output/small.md", "x", "yy", replace_all=True)
    [uploaded] = await backend.aupload_files([("/output/big.bin", b"x" * 11)])

    assert "over the 10 byte limit for one file" in too_big.error
    assert "over the 10 byte limit for one file" in grown.error
    assert "over the 10 byte limit for one file" in uploaded.error


# ---------------------------------------------------------------------------
# The uploads: rows under input/, never written by the agent
# ---------------------------------------------------------------------------
async def test_uploads_are_listed_and_read(backend, memory_file_store):
    await _upload(memory_file_store, "image.png", b"png")
    await _upload(memory_file_store, "data.csv", b"a,b\n1,2\n")

    listing = await backend.als("/input")
    csv = await backend.aread("/input/data.csv")

    assert [entry["path"] for entry in listing.entries] == ["/input/data.csv", "/input/image.png"]
    assert csv.file_data["content"] == "a,b\n1,2\n"


async def test_uploads_are_read_only(backend, memory_file_store):
    await _upload(memory_file_store, "data.csv", b"a")

    write = await backend.awrite("/input/new.csv", "x")
    edit = await backend.aedit("/input/data.csv", "a", "b")
    [upload] = await backend.aupload_files([("/input/data.csv", b"b")])
    folder = await backend.awrite("/input", "x")

    assert "uploads are read-only" in write.error
    assert "uploads are read-only" in edit.error
    assert "uploads are read-only" in folder.error
    assert upload.error == "permission_denied"
    assert (await backend.aread("/input/data.csv")).file_data["content"] == "a"


# ---------------------------------------------------------------------------
# ls / glob / grep
# ---------------------------------------------------------------------------
async def test_ls_lists_children_and_the_folders_that_always_exist(backend, memory_file_store):
    await _upload(memory_file_store, "image.png", b"png")
    await backend.awrite("/output/report.md", "r")
    await backend.awrite("/output/charts/q3.png", "c")
    await backend.awrite("/notes.md", "n")

    root = await backend.als("/")
    output = await backend.als("/output")

    assert [(e["path"], e["is_dir"]) for e in root.entries] == [
        ("/input/", True),
        ("/notes.md", False),
        ("/output/", True),
    ]
    assert [(e["path"], e["is_dir"]) for e in output.entries] == [
        ("/output/charts/", True),
        ("/output/report.md", False),
    ]
    assert (await backend.als("/nowhere")).error == "Path '/conversation/nowhere': path_not_found"
    assert (await backend.als("/notes.md")).error == (
        "Path '/conversation/notes.md': not_a_directory"
    )


async def test_an_empty_conversation_still_lists_input_and_output(backend):
    root = await backend.als("/")
    assert [e["path"] for e in root.entries] == ["/input/", "/output/"]
    assert (await backend.als("/input")).entries == []


async def test_glob_matches_like_the_filesystem_backend(backend):
    for path in ("/output/a.md", "/output/sub/b.md", "/output/c.txt"):
        await backend.awrite(path, "x")

    flat = await backend.aglob("*.md", "/output")
    deep = await backend.aglob("**/*.md", "/output")

    # deepagents' shared glob contract: a bare pattern matches the basename
    # at any depth, as on every other route.
    assert sorted(m["path"] for m in flat.matches) == ["/output/a.md", "/output/sub/b.md"]
    assert sorted(m["path"] for m in deep.matches) == ["/output/a.md", "/output/sub/b.md"]


async def test_grep_searches_text_files_only(backend, memory_file_store):
    await _upload(memory_file_store, "brief.txt", b"the budget is tight\n")
    await backend.awrite("/output/plan.md", "intro\nbudget: 10k\n")
    await backend.aupload_files([("/output/chart.png", b"budget in a picture")])

    result = await backend.agrep("budget", "/")
    only_md = await backend.agrep("budget", "/", glob="*.md")

    assert sorted((m["path"], m["line"]) for m in result.matches) == [
        ("/input/brief.txt", 1),
        ("/output/plan.md", 2),
    ]
    assert [m["path"] for m in only_md.matches] == ["/output/plan.md"]


async def test_grep_stays_within_its_budget(backend, monkeypatch):
    monkeypatch.setattr(backend_module, "GREP_MAX_FILES", 2)
    for name in ("a", "b", "c"):
        await backend.awrite(f"/output/{name}.md", "needle")

    result = await backend.agrep("needle", "/")

    assert len(result.matches) == 2
    assert result.error is None


async def test_downloads_and_uploads_round_trip(backend):
    [uploaded] = await backend.aupload_files([("/output/data.bin", b"\x00\x01")])
    await backend.aupload_files([("/output/data.bin", b"\x02")])  # an upload replaces
    found, missing = await backend.adownload_files(["/output/data.bin", "/output/nope"])

    assert uploaded.error is None
    assert found.content == b"\x02"
    assert missing.error == "file_not_found"


# ---------------------------------------------------------------------------
# The mount table
# ---------------------------------------------------------------------------
async def test_offloads_live_in_their_own_folders(composite, memory_file_store):
    await composite.awrite("/large_tool_results/call-1", "a huge tool result")
    await composite.awrite("/conversation/large_tool_results/sneaky", "not an offload")

    stored = {path for _, path in memory_file_store.rows}
    assert stored == {"/large_tool_results/call-1", "/conversation/large_tool_results/sneaky"}
    read = await composite.aread("/large_tool_results/call-1")
    assert read.file_data["content"] == "a huge tool result"


async def test_a_grep_over_the_conversation_sees_each_file_once(composite, memory_file_store):
    """One route for the whole of ``/conversation/``, uploads included, so a
    match under input/ or output/ is reported once, not once per route."""
    await _upload(memory_file_store, "brief.txt", b"needle\n")
    await composite.awrite("/conversation/output/a.md", "needle")

    result = await composite.agrep("needle", "/conversation")

    assert sorted(m["path"] for m in result.matches) == [
        "/conversation/input/brief.txt",
        "/conversation/output/a.md",
    ]


async def test_uploads_are_read_only_through_the_composite_too(composite, memory_file_store):
    await _upload(memory_file_store, "data.csv", b"a")
    result = await composite.awrite("/conversation/input/evil.csv", "x")
    assert "uploads are read-only" in result.error


async def test_every_agent_of_the_conversation_sees_the_same_files(
    conversation_files, memory_file_store
):
    other_agent = ConversationFiles(
        client_id=CLIENT_ID,
        conversation_id=CONVERSATION_ID,
        agent_slug="writer",
        store=memory_file_store,
    )
    await ConversationFilesBackend(conversation_files, "/conversation").awrite(
        "/output/a.md", "the assistant's"
    )

    read = await ConversationFilesBackend(other_agent, "/conversation").aread("/output/a.md")

    assert read.file_data["content"] == "the assistant's"


async def test_the_sync_methods_run_on_the_service_loop(conversation_files):
    backend = ConversationFilesBackend(
        conversation_files, "/conversation", loop=asyncio.get_running_loop()
    )
    await backend.awrite("/output/a.md", "from the loop")

    result = await asyncio.to_thread(backend.read, "/output/a.md")

    assert result.file_data["content"] == "from the loop"
    with pytest.raises(RuntimeError, match="event loop"):
        backend.read("/output/a.md")  # on the loop thread it would deadlock
    assert threading.current_thread() is threading.main_thread()


def test_the_sync_methods_need_a_running_service_loop(conversation_files):
    backend = ConversationFilesBackend(conversation_files, "/conversation")
    with pytest.raises(RuntimeError, match="service event loop"):
        backend.read("/output/a.md")


# ---------------------------------------------------------------------------
# The tools that read files directly
# ---------------------------------------------------------------------------
async def test_present_artifact_needs_a_written_output_file(
    conversation_files, backend, memory_file_store
):
    tool = build_present_artifact_tool(files=conversation_files, presented=PresentedFiles())
    await backend.awrite("/output/report.md", "# Q3")
    await _upload(memory_file_store, "brief.txt", b"brief")

    async def present(path: str, call_id: str) -> str:
        message = await tool.ainvoke(
            {
                "name": tool.name,
                "args": {"path": path, "title": "Q3"},
                "id": call_id,
                "type": "tool_call",
            }
        )
        return message.content

    presented = await present("/conversation/output/report.md", "call-1")
    not_written = await present("/conversation/output/nope.md", "call-2")
    an_upload = await present("/conversation/input/brief.txt", "call-3")

    assert "is now a document card" in presented
    assert "no file at" in not_written
    assert "must be under /conversation/output/" in an_upload
