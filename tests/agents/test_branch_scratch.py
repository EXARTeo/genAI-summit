"""The branch scratch store: one shared filesystem per conversation branch.

Pinned here:

* the **store contract** (last-write-wins ``put``, a compare-and-set that
  refuses a stale version, scoping by client, conversation and branch,
  copy-on-fork, the per-file cap) on an in-memory twin of
  ``BranchScratchStore``, the shape the backend is written against;
* the **backend**: two backends on one branch (an orchestrator and its task)
  see each other's writes live; another branch does not; ``edit_file`` fails
  cleanly when another agent changed the file;
* **which branch**: the run context's ``branch_thread_id``, else the run's
  ``thread_id``, bound at build time or read from the live LangGraph run; a
  thread-less run keeps deepagents' in-state scratch;
* **copy-on-fork** through ``harness.checkpointer.fork``;
* the **workspace default**, and the sandbox default reading and writing the
  same rows.

The store's SQL needs Postgres and is not exercised here.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import TypedDict, get_type_hints

import httpx
import psycopg
import pytest
from conftest import CLIENT_ID, CONVERSATION_ID, OTHER_CLIENT_ID
from deepagents.backends.protocol import SandboxBackendProtocol
from deepagents.middleware.filesystem import FilesystemState
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph

from core.settings import settings
from harness.checkpointer import fork
from harness.checkpointer import store as checkpointer_store
from harness.filesystem import resolve_branch_thread_id
from harness.filesystem import sandbox_backend as sandbox_module
from harness.filesystem import workspace as workspace_module
from harness.filesystem.scratch_backend import UNAVAILABLE, BranchScratchBackend
from harness.filesystem.scratch_store import (
    ENCODINGS,
    BranchScratchStore,
    ScratchEntry,
    ScratchFile,
    ScratchFileTooLarge,
    ScratchScope,
)

RUNNER_URL = "https://sandbox-runner.test:8090"

# deepagents' own `files` channel (with its reducer), so a thread-less run's
# in-state fallback behaves exactly as in a real deep agent.
_FILES_CHANNEL = get_type_hints(FilesystemState, include_extras=True)["files"]


class _FilesState(TypedDict, total=False):
    files: _FILES_CHANNEL


# ---------------------------------------------------------------------------
# The store, in memory
# ---------------------------------------------------------------------------
class MemoryScratchStore:
    """``BranchScratchStore`` in memory: the same methods and return shapes."""

    def __init__(self) -> None:
        self.rows: dict[tuple[str, str, str], dict] = {}  # (conv, branch, path) -> row
        self.setups = 0

    async def ensure_setup(self) -> None:
        self.setups += 1

    @staticmethod
    def _entry(path: str, row: dict) -> ScratchEntry:
        return ScratchEntry(
            path,
            len(row["data"]),
            row["sha256"],
            row["encoding"],
            row["created_at"],
            row["updated_at"],
        )

    def _in_scope(self, scope: ScratchScope) -> dict[str, dict]:
        return {
            path: row
            for (conv, branch, path), row in self.rows.items()
            if (conv, branch, row["client_id"])
            == (scope.conversation_id, scope.branch_thread_id, scope.client_id)
        }

    @staticmethod
    def _checked(data: bytes, encoding: str) -> None:
        assert encoding in ENCODINGS
        if len(data) > settings.conversation_files.max_file_bytes:
            raise ScratchFileTooLarge("too large")

    async def list_files(self, scope, directory="/"):
        prefix = directory.rstrip("/") + "/"
        return [
            self._entry(p, r)
            for p, r in sorted(self._in_scope(scope).items())
            if p == directory or p.startswith(prefix)
        ]

    async def get(self, scope, path):
        return (await self.read_many(scope, [path])).get(path)

    async def read_many(self, scope, file_paths):
        rows = self._in_scope(scope)
        return {
            p: ScratchFile(self._entry(p, rows[p]), rows[p]["data"])
            for p in file_paths
            if p in rows
        }

    def _write(self, scope, path, data, encoding, agent_slug):
        key = (scope.conversation_id, scope.branch_thread_id, path)
        now = datetime.now(UTC)
        previous = self.rows.get(key)
        self.rows[key] = {
            "client_id": scope.client_id,
            "data": bytes(data),
            "encoding": encoding,
            "sha256": hashlib.sha256(data).hexdigest(),
            "agent_slug": agent_slug,
            "created_at": previous["created_at"] if previous else now,
            "updated_at": now,
        }
        return self.rows[key]["sha256"]

    async def put(self, scope, path, data, *, encoding, agent_slug):
        self._checked(data, encoding)
        existing = self.rows.get((scope.conversation_id, scope.branch_thread_id, path))
        if existing is not None and existing["client_id"] != scope.client_id:
            return None
        return self._write(scope, path, data, encoding, agent_slug)

    async def compare_and_set(self, scope, path, expected_sha256, data, *, encoding, agent_slug):
        self._checked(data, encoding)
        current = self._in_scope(scope).get(path)
        if current is None or current["sha256"] != expected_sha256:
            return None
        return self._write(scope, path, data, encoding, agent_slug)

    async def copy_branch(self, source_thread_id, target_thread_id):
        if not source_thread_id or not target_thread_id or source_thread_id == target_thread_id:
            return 0
        copied = 0
        for (conv, branch, path), row in list(self.rows.items()):
            if branch == source_thread_id and (conv, target_thread_id, path) not in self.rows:
                self.rows[(conv, target_thread_id, path)] = dict(row)
                copied += 1
        return copied


@pytest.fixture
def store() -> MemoryScratchStore:
    return MemoryScratchStore()


def _scope(client=CLIENT_ID, conversation=CONVERSATION_ID, branch="b1") -> ScratchScope:
    return ScratchScope(client, conversation, branch)


def _backend(store, branch: str | None = "b1", agent: str = "assistant") -> BranchScratchBackend:
    return BranchScratchBackend(
        store=store,
        client_id=CLIENT_ID,
        conversation_id=CONVERSATION_ID,
        agent_slug=agent,
        branch_thread_id=branch,
    )


def _one_node_graph(node):
    builder = StateGraph(_FilesState)
    builder.add_node("write", node)
    builder.add_edge(START, "write")
    builder.add_edge("write", END)
    return builder


# ---------------------------------------------------------------------------
# The store contract
# ---------------------------------------------------------------------------
async def test_put_then_get_and_list_by_prefix(store):
    scope = _scope()
    for path in ["/notes.md", "/drafts/v1.md", "/drafts/deep/v2.md", "/drafts.md"]:
        await store.put(scope, path, path.encode(), encoding="utf-8", agent_slug="assistant")

    under = [entry.path for entry in await store.list_files(scope, "/drafts")]
    file = await store.get(scope, "/notes.md")

    assert under == ["/drafts/deep/v2.md", "/drafts/v1.md"]
    assert len(await store.list_files(scope)) == 4
    assert file.data == b"/notes.md"
    assert file.entry.sha256 == hashlib.sha256(b"/notes.md").hexdigest()


async def test_rows_never_cross_clients_conversations_or_branches(store):
    await store.put(_scope(), "/a.md", b"mine", encoding="utf-8", agent_slug="assistant")

    for other in (_scope(client=OTHER_CLIENT_ID), _scope(conversation="c2"), _scope(branch="b2")):
        assert await store.get(other, "/a.md") is None
        assert await store.list_files(other) == []
    # Another client can never overwrite the row at the same key.
    theirs = await store.put(
        _scope(client=OTHER_CLIENT_ID), "/a.md", b"theirs", encoding="utf-8", agent_slug="x"
    )
    assert theirs is None
    assert (await store.get(_scope(), "/a.md")).data == b"mine"


async def test_put_is_last_write_wins(store):
    scope = _scope()
    await store.put(scope, "/a.md", b"one", encoding="utf-8", agent_slug="assistant")
    version = await store.put(scope, "/a.md", b"two", encoding="utf-8", agent_slug="writer")

    assert (await store.get(scope, "/a.md")).data == b"two"
    assert version == hashlib.sha256(b"two").hexdigest()


async def test_compare_and_set_refuses_a_stale_version(store):
    scope = _scope()
    first = await store.put(scope, "/a.md", b"v1", encoding="utf-8", agent_slug="assistant")
    await store.put(scope, "/a.md", b"v2", encoding="utf-8", agent_slug="writer")  # someone else

    stale = await store.compare_and_set(
        scope, "/a.md", first, b"v1-edit", encoding="utf-8", agent_slug="assistant"
    )
    assert stale is None
    current = await store.get(scope, "/a.md")
    assert current.data == b"v2"
    fresh = await store.compare_and_set(
        scope, "/a.md", current.entry.sha256, b"v2-edit", encoding="utf-8", agent_slug="assistant"
    )
    assert fresh == hashlib.sha256(b"v2-edit").hexdigest()
    gone = await store.compare_and_set(
        scope, "/none.md", first, b"x", encoding="utf-8", agent_slug="a"
    )
    assert gone is None


async def test_copy_branch_gives_the_fork_the_files_and_then_they_diverge(store):
    source, forked = _scope(branch="b1"), _scope(branch="b2")
    await store.put(source, "/a.md", b"shared", encoding="utf-8", agent_slug="assistant")
    await store.put(source, "/bin.dat", b"\x00\xff", encoding="base64", agent_slug="assistant")

    assert await store.copy_branch("b1", "b2") == 2
    assert await store.copy_branch("b1", "b2") == 0  # a retried fork changes nothing
    await store.put(forked, "/a.md", b"forked", encoding="utf-8", agent_slug="assistant")

    assert (await store.get(source, "/a.md")).data == b"shared"
    assert (await store.get(forked, "/a.md")).data == b"forked"
    assert (await store.get(forked, "/bin.dat")).entry.encoding == "base64"


async def test_a_file_over_the_cap_is_refused(store, monkeypatch):
    monkeypatch.setattr(settings.conversation_files, "max_file_bytes", 4)
    with pytest.raises(ScratchFileTooLarge):
        await store.put(_scope(), "/a.md", b"12345", encoding="utf-8", agent_slug="a")
    assert await store.get(_scope(), "/a.md") is None


async def test_the_real_store_refuses_an_unknown_encoding_before_any_query():
    # The pool is the conftest stub: reaching it would raise AttributeError.
    with pytest.raises(ValueError, match="encoding"):
        await BranchScratchStore().put(_scope(), "/a.md", b"x", encoding="utf-16", agent_slug="a")


async def test_the_real_store_refuses_an_oversized_file_before_any_query(monkeypatch):
    monkeypatch.setattr(settings.conversation_files, "max_file_bytes", 1)
    with pytest.raises(ScratchFileTooLarge):
        await BranchScratchStore().put(_scope(), "/a.md", b"xx", encoding="utf-8", agent_slug="a")


def test_the_real_store_resolves_the_runtime_pool_lazily():
    """Minting a store does no I/O: the pool is looked up at the first query."""
    pool = object()
    checkpointer_store.set_runtime_pool(pool)
    assert BranchScratchStore().pool is pool
    checkpointer_store.set_runtime_pool(None)
    lazy = BranchScratchStore()
    with pytest.raises(RuntimeError, match="agent_runtime pool"):
        _ = lazy.pool


# ---------------------------------------------------------------------------
# Which branch
# ---------------------------------------------------------------------------
def test_the_context_branch_wins_over_the_runs_own_thread():
    resolve = resolve_branch_thread_id

    assert resolve({"branch_thread_id": "orch"}, {"configurable": {"thread_id": "task-1"}}) == (
        "orch"
    )
    assert resolve({"client_id": CLIENT_ID}, {"configurable": {"thread_id": "orch"}}) == "orch"
    assert resolve({"branch_thread_id": "  "}, {"configurable": {"thread_id": "orch"}}) == "orch"
    assert resolve(None, {"configurable": {}}) is None
    assert resolve(None, None) is None


@pytest.mark.parametrize("branch", ["../other", "a/b", " lead", "x" * 200])
def test_an_ill_formed_branch_id_is_refused(store, branch):
    with pytest.raises(ValueError, match="branch thread"):
        _backend(store, branch=branch)


# ---------------------------------------------------------------------------
# The backend: one filesystem per branch, live
# ---------------------------------------------------------------------------
async def test_two_agents_on_one_branch_see_each_others_writes(store):
    orchestrator, task = _backend(store, agent="assistant"), _backend(store, agent="writer")

    assert (await orchestrator.awrite("/plan.md", "step 1\n")).error is None
    assert (await task.aread("/plan.md")).file_data["content"] == "step 1\n"
    assert (await task.awrite("/findings/a.md", "found TODO here\n")).error is None

    listing = await orchestrator.als("/")
    assert [e["path"] for e in listing.entries] == ["/findings/", "/plan.md"]
    globbed = await orchestrator.aglob("**/*.md")
    assert [m["path"] for m in globbed.matches] == ["/findings/a.md", "/plan.md"]
    grep = await orchestrator.agrep("TODO")
    assert [(m["path"], m["line"]) for m in grep.matches] == [("/findings/a.md", 1)]
    # Each backend ensured the table once for the branch, not once per call.
    assert store.setups == 2


async def test_another_branch_sees_none_of_it(store):
    await _backend(store, branch="b1").awrite("/plan.md", "branch one")

    other = _backend(store, branch="b2")
    assert (await other.aread("/plan.md")).error == "File '/plan.md' not found"
    assert (await other.als("/")).entries == []


async def test_an_edit_on_a_file_changed_by_another_agent_fails_cleanly(store):
    orchestrator, task = _backend(store, agent="assistant"), _backend(store, agent="writer")
    await orchestrator.awrite("/plan.md", "status: draft\n")
    await task.aread("/plan.md")
    await orchestrator.awrite("/plan.md", "status: review\n")  # the orchestrator moves on

    stale = await task.aedit("/plan.md", "status: draft", "status: done")
    assert stale.error is not None
    assert "changed by another agent" in stale.error
    assert (await orchestrator.aread("/plan.md")).file_data["content"] == "status: review\n"

    await task.aread("/plan.md")  # re-read, then retry
    retried = await task.aedit("/plan.md", "status: review", "status: done")
    assert (retried.error, retried.occurrences) == (None, 1)
    assert (await orchestrator.aread("/plan.md")).file_data["content"] == "status: done\n"


async def test_a_write_that_lands_mid_edit_loses_the_compare_and_set(store, monkeypatch):
    backend = _backend(store)
    await backend.awrite("/a.md", "one\n")
    real = store.compare_and_set

    async def racing(scope, path, expected, data, **kwargs):
        await store.put(scope, path, b"someone else\n", encoding="utf-8", agent_slug="writer")
        return await real(scope, path, expected, data, **kwargs)

    monkeypatch.setattr(store, "compare_and_set", racing)
    result = await backend.aedit("/a.md", "one", "two")

    assert "changed by another agent" in result.error
    assert (await store.get(_scope(), "/a.md")).data == b"someone else\n"


async def test_edit_without_a_prior_read_and_binary_files(store):
    backend = _backend(store)
    other = _backend(store, agent="writer")
    await other.awrite("/a.md", "alpha beta\n")

    assert (await backend.aedit("/a.md", "beta", "gamma")).occurrences == 1
    missing = await backend.aedit("/missing.md", "x", "y")
    assert missing.error == "Error: File '/missing.md' not found"

    [upload] = await backend.aupload_files([("/img.bin", b"\x89PNG\x00\xff")])
    assert upload.error is None
    assert "binary" in (await backend.aedit("/img.bin", "PNG", "JPG")).error
    [download] = await other.adownload_files(["/img.bin"])
    assert download.content == b"\x89PNG\x00\xff"


async def test_a_write_over_the_cap_is_an_error_result(store, monkeypatch):
    monkeypatch.setattr(settings.conversation_files, "max_file_bytes", 3)
    result = await _backend(store).awrite("/a.md", "four")
    assert result.error.startswith("Error writing file '/a.md'")
    assert store.rows == {}


async def test_invalid_paths_never_reach_the_store(store):
    backend = _backend(store)
    assert "Error writing file" in (await backend.awrite("/../etc/passwd", "x")).error
    [download] = await backend.adownload_files(["/.hidden"])
    assert download.error == "invalid_path"
    assert store.rows == {}


async def test_delete_is_refused_on_the_shared_store(store):
    await _backend(store).awrite("/a.md", "kept")
    result = await _backend(store).adelete("/a.md")
    assert "not supported" in result.error
    assert len(store.rows) == 1


async def test_a_store_outage_is_an_error_result_never_a_raise(store, monkeypatch):
    async def down(*args, **kwargs):
        raise psycopg.OperationalError("connection refused")

    monkeypatch.setattr(store, "get", down)
    monkeypatch.setattr(store, "put", down)
    backend = _backend(store)

    assert (await backend.aread("/a.md")).error == UNAVAILABLE
    assert (await backend.awrite("/a.md", "x")).error == UNAVAILABLE


async def test_the_live_run_decides_the_branch_when_none_is_bound(store):
    """Unbound, the backend reads the branch from the running graph: the
    orchestrator's thread, or, on a task's own thread, the context's branch."""
    backend = _backend(store, branch=None)

    async def write(state):
        await backend.awrite("/from-run.md", "hello")
        return {}

    graph = _one_node_graph(write).compile(checkpointer=InMemorySaver())

    await graph.ainvoke({}, {"configurable": {"thread_id": "orch-thread"}})
    await graph.ainvoke(
        {},
        {"configurable": {"thread_id": "task-thread"}},
        context={"branch_thread_id": "orch-thread"},
    )

    assert {key[1] for key in store.rows} == {"orch-thread"}


async def test_a_thread_less_run_keeps_the_in_state_scratch(store):
    backend = _backend(store, branch=None)

    async def write(state):
        await backend.awrite("/eph.md", "in state")
        return {}

    result = await _one_node_graph(write).compile().ainvoke({})

    assert store.rows == {}
    assert result["files"]["/eph.md"]["content"] == "in state"


# ---------------------------------------------------------------------------
# Copy-on-fork
# ---------------------------------------------------------------------------
class _ForkGraph:
    def __init__(self, states):
        self._states = states
        self.updated: list = []
        self.checkpointer = None

    async def aget_state(self, cfg):
        conf = cfg["configurable"]
        return self._states.get(
            (conf["thread_id"], conf.get("checkpoint_id")), SimpleNamespace(values={})
        )

    async def aupdate_state(self, cfg, values, as_node=None):
        self.updated.append((cfg["configurable"]["thread_id"], values))


async def test_a_fork_copies_the_source_branchs_scratch(store, monkeypatch):
    monkeypatch.setattr(fork, "BranchScratchStore", lambda: store)
    await store.put(
        _scope(branch="src"), "/notes.md", b"before the fork", encoding="utf-8", agent_slug="a"
    )
    graph = _ForkGraph({("src", "cp-1"): SimpleNamespace(values={"messages": ["m"]})})

    assert await fork.seed_thread_from_checkpoint(
        graph=graph, source_thread_id="src", source_checkpoint_id="cp-1", target_thread_id="new"
    )
    assert (await store.get(_scope(branch="new"), "/notes.md")).data == b"before the fork"

    # An already-seeded target still gets (only) the files it lacks.
    await store.put(
        _scope(branch="new"), "/notes.md", b"edited on the fork", encoding="utf-8", agent_slug="a"
    )
    await store.put(_scope(branch="src"), "/later.md", b"later", encoding="utf-8", agent_slug="a")
    seeded = _ForkGraph({("new", None): SimpleNamespace(values={"messages": ["m"]})})
    assert await fork.seed_thread_from_checkpoint(
        graph=seeded, source_thread_id="src", source_checkpoint_id="cp-1", target_thread_id="new"
    )
    assert (await store.get(_scope(branch="new"), "/notes.md")).data == b"edited on the fork"
    assert (await store.get(_scope(branch="new"), "/later.md")).data == b"later"


async def test_a_fork_without_a_store_still_seeds():
    checkpointer_store.set_runtime_pool(None)
    graph = _ForkGraph({("src", "cp-1"): SimpleNamespace(values={"messages": ["m"]})})

    assert await fork.seed_thread_from_checkpoint(
        graph=graph, source_thread_id="src", source_checkpoint_id="cp-1", target_thread_id="new"
    )
    assert graph.updated == [("new", {"messages": ["m"]})]
    assert await fork.copy_branch_scratch("src", "new") == 0


async def test_a_failing_scratch_copy_never_fails_the_fork(monkeypatch):
    class _Broken:
        async def ensure_setup(self):
            raise psycopg.OperationalError("down")

    monkeypatch.setattr(fork, "BranchScratchStore", _Broken)
    assert await fork.copy_branch_scratch("src", "dst") == 0


# ---------------------------------------------------------------------------
# The workspace and the sandbox default
# ---------------------------------------------------------------------------
def test_the_workspace_default_is_the_branch_scratch_store(conversation_files):
    backend = workspace_module.build_workspace_backend(
        client_id=CLIENT_ID,
        agent_slug="assistant",
        files=conversation_files,
        branch_thread_id="orch",
    )

    default = backend.default
    assert type(default) is BranchScratchBackend
    assert not isinstance(default, SandboxBackendProtocol)
    assert (default._client_id, default._conversation_id, default._branch) == (
        CLIENT_ID,
        CONVERSATION_ID,
        "orch",
    )


class _Runner:
    def __init__(self):
        self.bodies: list[dict] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.bodies.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "exit_code": 0,
                "stdout": "ok\n",
                "stderr": "",
                "truncated": False,
                "duration_ms": 1,
                "killed_reason": None,
            },
        )


async def test_the_sandbox_default_reads_and_writes_the_same_rows(
    store, conversation_files, monkeypatch
):
    fs = settings.filesystem
    monkeypatch.setattr(fs, "sandbox_execution_enabled", True)
    monkeypatch.setattr(fs, "sandbox_runner_url", RUNNER_URL)
    runner = _Runner()

    class _Wired(sandbox_module.RemoteSandboxBackend):
        def __init__(self, **kwargs):
            kwargs["scratch_store"] = store
            super().__init__(
                **kwargs,
                transport=httpx.MockTransport(runner),
                async_transport=httpx.MockTransport(runner),
            )

    monkeypatch.setattr(workspace_module, "RemoteSandboxBackend", _Wired)
    composite = workspace_module.build_workspace_backend(
        client_id=CLIENT_ID,
        agent_slug="assistant",
        files=conversation_files,
        branch_thread_id="orch",
    )
    assert isinstance(composite.default, sandbox_module.RemoteSandboxBackend)
    assert isinstance(composite.default, BranchScratchBackend)

    await composite.awrite("/plan.md", "from the sandbox default")
    task = _backend(store, branch="orch", agent="writer")
    assert (await task.aread("/plan.md")).file_data["content"] == "from the sandbox default"
    await task.awrite("/plan.md", "from a task")
    assert (await composite.aread("/plan.md")).file_data["content"] == "from a task"

    # The scratch files do not travel into the box: only input/ and output/ do.
    result = await composite.aexecute("ls")
    assert result.exit_code == 0
    [body] = runner.bodies
    assert body["files"] == []
    assert body["conversation_id"] == CONVERSATION_ID
