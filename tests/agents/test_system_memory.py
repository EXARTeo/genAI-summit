"""Agent memory per audited system (``harness/memory``), mounted at ``/memory/``.

Pinned, with no Postgres and no model:

* the store: CRUD, the per-system cap (updates always allowed), the SQL it runs;
* ``MEMORY.md`` is derived (grouped by audit, newest first) and a write to it is
  ignored;
* the mount through deepagents' ``StoreBackend``: reads, listing, a write into
  the run's own audit folder (provenance from the binding, never the body), and
  refusals for other audits and deletes;
* ``remember`` / ``forget``: slugged names, idempotent, never raise, strings back;
  ``forget`` is approval-gated and both names are reserved against MCP;
* the run: ``/memory/``, the tools and the prompt section exist only with a
  ``system_id`` in the context, and the binding travels to async tasks.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from conftest import CLIENT_ID, CONVERSATION_ID
from deepagents.backends import StoreBackend
from langchain_core.tools import tool as lc_tool
from langgraph.checkpoint.memory import MemorySaver

from core.settings import settings
from harness.abstractions import deep_agent
from harness.abstractions.base_agent import BaseAgent
from harness.async_tasks.runner import task_context
from harness.async_tasks.token import InheritedContext
from harness.memory import (
    MemoryBinding,
    MemoryRecord,
    MemoryWriteRefused,
    SystemMemoryFiles,
    SystemMemoryStore,
    build_index,
    memory_binding_from_context,
    memory_namespace,
    render_entry,
    save_memory,
    slugify_name,
)
from harness.memory.entries import parse_entry_key, summary_of
from harness.prompt_engineering import PromptContext, compose_system_prompt
from harness.tools.builtins import builtin_hitl_defaults
from harness.tools.forget import build_forget_tool
from harness.tools.gates import strip_reserved_names
from harness.tools.registry import NativeToolContext, build_auto_attach_tools
from harness.tools.remember import build_remember_tool
from utils.agents import resolve_agent_definition

SYS = "SYS-001"
AUDIT = "AUD-7"
T0 = datetime(2026, 11, 14, 9, 0, tzinfo=UTC)


# ---------------------------------------------------------------------------
# An in-memory twin of SystemMemoryStore (the typed API)
# ---------------------------------------------------------------------------
class FakeMemoryStore:
    def __init__(self, *, fail: bool = False) -> None:
        self.rows: dict[tuple[str, str, str], MemoryRecord] = {}
        self.fail = fail
        self._tick = 0

    def _check(self) -> None:
        if self.fail:
            raise ConnectionError("db down")

    async def get(self, system_id, audit_id, name):
        self._check()
        return self.rows.get((system_id, audit_id, name))

    async def list_system(self, system_id):
        self._check()
        rows = [r for (s, _, _), r in self.rows.items() if s == system_id]
        return sorted(rows, key=lambda r: r.updated_at, reverse=True)

    async def count_system(self, system_id):
        self._check()
        return sum(1 for (s, _, _) in self.rows if s == system_id)

    async def upsert(self, record):
        self._check()
        self._tick += 1
        key = (record.system_id, record.audit_id, record.name)
        prior = self.rows.get(key)
        stamp = T0 + timedelta(minutes=self._tick)
        stored = replace(
            record,
            created_at=prior.created_at if prior else stamp,
            created_by=prior.created_by if prior else record.created_by,
            updated_at=stamp,
        )
        self.rows[key] = stored
        return stored

    async def delete(self, system_id, audit_id, name):
        self._check()
        return self.rows.pop((system_id, audit_id, name), None) is not None


def _binding(**overrides: Any) -> MemoryBinding:
    base = {
        "system_id": SYS,
        "audit_id": AUDIT,
        "step": "plan_tests",
        "agent_name": "auditor",
        "run_id": "run-1",
        "thread_id": "th-1",
    }
    return MemoryBinding(**{**base, **overrides})


def _record(name: str, *, audit: str = AUDIT, minutes: int = 0, **kw: Any) -> MemoryRecord:
    stamp = T0 + timedelta(minutes=minutes)
    return MemoryRecord(
        system_id=kw.pop("system_id", SYS),
        audit_id=audit,
        name=name,
        summary=kw.pop("summary", f"summary of {name}"),
        content_md=kw.pop("content_md", render_entry(name, f"summary of {name}", "detail")),
        created_at=stamp,
        updated_at=stamp,
        **kw,
    )


# ---------------------------------------------------------------------------
# Entries and the derived index
# ---------------------------------------------------------------------------
def test_names_slug_to_safe_keys():
    assert slugify_name("  Wrong Metric: Use EO!  ") == "wrong-metric-use-eo"
    assert slugify_name("***") == ""
    assert len(slugify_name("x" * 500)) == 80


def test_entry_keys_parse_only_well_formed_paths():
    assert parse_entry_key("/audits/AUD-7/wrong-metric.md") == ("AUD-7", "wrong-metric")
    assert parse_entry_key("audits/AUD-7/wrong-metric.md") == ("AUD-7", "wrong-metric")
    assert parse_entry_key("/audits/AUD-7/Wrong Metric.md") is None
    assert parse_entry_key("/audits/AUD-7/sub/x.md") is None
    assert parse_entry_key("/MEMORY.md") is None
    assert parse_entry_key("/audits/../x.md") is None


def test_the_index_groups_by_audit_newest_first():
    records = [
        _record("old-lesson", audit="AUD-1", minutes=0, step="plan_tests", agent_name="planner"),
        _record("new-lesson", audit="AUD-2", minutes=10, step="critic"),
        _record("mid-lesson", audit="AUD-1", minutes=5),
    ]
    text = build_index(SYS, records)
    assert text.startswith(f"# System memory: {SYS}")
    assert text.index("## Audit AUD-2") < text.index("## Audit AUD-1")
    assert text.index("mid-lesson") < text.index("old-lesson")
    assert "- 2026-11-14 · plan_tests · planner · **old-lesson** — summary of old-lesson" in text


def test_an_empty_memory_still_has_an_index():
    assert "_No entries yet._" in build_index(SYS, [])


def test_the_summary_of_a_hand_written_entry_is_its_first_line():
    assert summary_of("# name\n\n> Use EO for hiring.\n\nmore") == "Use EO for hiring."
    assert summary_of("") == ""


# ---------------------------------------------------------------------------
# The capped write
# ---------------------------------------------------------------------------
async def test_save_creates_then_updates_in_place():
    store = FakeMemoryStore()
    args = {"name": "lesson", "summary": "s", "content_md": "body", "max_entries": 5}
    assert await save_memory(store, _binding(), **args) == "created"
    first = store.rows[(SYS, AUDIT, "lesson")]
    assert await save_memory(store, _binding(), **{**args, "summary": "s2"}) == "updated"
    second = store.rows[(SYS, AUDIT, "lesson")]
    assert len(store.rows) == 1
    assert second.summary == "s2"
    assert second.created_at == first.created_at
    assert (second.step, second.agent_name, second.source_run_id) == (
        "plan_tests",
        "auditor",
        "run-1",
    )


async def test_the_cap_refuses_new_entries_but_never_updates():
    store = FakeMemoryStore()
    for i in range(2):
        await save_memory(
            store, _binding(), name=f"n{i}", summary="s", content_md="b", max_entries=2
        )
    new = await save_memory(
        store, _binding(), name="n9", summary="s", content_md="b", max_entries=2
    )
    upd = await save_memory(
        store, _binding(), name="n0", summary="x", content_md="b", max_entries=2
    )
    assert (new, upd) == ("full", "updated")
    # The cap is per system: another system is unaffected.
    other = await save_memory(
        store, _binding(system_id="SYS-002"), name="n9", summary="s", content_md="b", max_entries=2
    )
    assert other == "created"


async def test_a_run_without_an_audit_cannot_write():
    out = await save_memory(
        FakeMemoryStore(),
        _binding(audit_id=None),
        name="n",
        summary="s",
        content_md="b",
        max_entries=5,
    )
    assert out == "read_only"


# ---------------------------------------------------------------------------
# The SQL store (fake pool: records SQL, replays rows)
# ---------------------------------------------------------------------------
class _Cursor:
    def __init__(self, rows, rowcount=0):
        self._rows, self.rowcount = rows, rowcount

    async def fetchone(self):
        return self._rows[0] if self._rows else None

    async def fetchall(self):
        return list(self._rows)


class FakePool:
    def __init__(self, *batches, rowcount=0):
        self.batches, self.calls, self.rowcount = list(batches), [], rowcount

    def connection(self):
        pool = self

        class _Conn:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *_):
                return False

            async def execute(self, sql, params=None):
                pool.calls.append((" ".join(sql.split()), params))
                return _Cursor(pool.batches.pop(0) if pool.batches else [], pool.rowcount)

        return _Conn()


def _row(name: str) -> dict[str, Any]:
    record = _record(name)
    return {k: getattr(record, k) for k in record.__dataclass_fields__}


async def test_setup_creates_the_table_if_missing():
    pool = FakePool()
    await SystemMemoryStore(pool).setup()
    sql = [s for s, _ in pool.calls]
    assert sql[0].startswith("CREATE TABLE IF NOT EXISTS system_memories")
    assert "PRIMARY KEY (system_id, audit_id, name)" in sql[0]
    assert any("CREATE INDEX IF NOT EXISTS" in s for s in sql)


async def test_upsert_is_keyed_on_system_audit_and_name():
    pool = FakePool([_row("lesson")])
    out = await SystemMemoryStore(pool).upsert(_record("lesson", step="critic"))
    sql, params = pool.calls[0]
    assert "ON CONFLICT (system_id, audit_id, name) DO UPDATE" in sql
    assert "created_at = EXCLUDED" not in sql
    assert params[:3] == (SYS, AUDIT, "lesson") and params[5] == "critic"
    assert out.name == "lesson"


async def test_reads_are_scoped_to_one_system():
    pool = FakePool([_row("a"), _row("b")], [{"n": 2}], rowcount=1)
    store = SystemMemoryStore(pool)
    rows = await store.list_system(SYS)
    assert [r.name for r in rows] == ["a", "b"]
    assert await store.count_system(SYS) == 2
    assert await store.delete(SYS, AUDIT, "a") is True
    assert all(params[0] == SYS for _, params in pool.calls)


# ---------------------------------------------------------------------------
# The /memory/ mount through deepagents' StoreBackend
# ---------------------------------------------------------------------------
def _mount(store: FakeMemoryStore, binding: MemoryBinding | None = None, cap: int = 200):
    files = SystemMemoryFiles(store, binding or _binding(), max_entries=cap)
    ns = memory_namespace((binding or _binding()).system_id)
    return files, StoreBackend(store=files, namespace=lambda _rt: ns)


async def test_memory_md_is_derived_from_the_rows():
    store = FakeMemoryStore()
    store.rows[(SYS, "AUD-1", "quirk")] = _record("quirk", audit="AUD-1")
    store.rows[("SYS-002", "AUD-9", "elsewhere")] = _record("elsewhere", system_id="SYS-002")
    _, backend = _mount(store)
    result = await backend.aread("/MEMORY.md")
    text = result.file_data["content"]
    assert "**quirk**" in text and "elsewhere" not in text
    entry = await backend.aread("/audits/AUD-1/quirk.md")
    assert entry.file_data["content"] == store.rows[(SYS, "AUD-1", "quirk")].content_md


async def test_ls_shows_the_index_and_the_audit_folders():
    store = FakeMemoryStore()
    store.rows[(SYS, AUDIT, "a")] = _record("a")
    _, backend = _mount(store)
    root = await backend.als("/")
    paths = {e["path"] for e in root.entries}
    assert paths == {"/MEMORY.md", "/audits/"}
    inner = await backend.als(f"/audits/{AUDIT}/")
    assert [e["path"] for e in inner.entries] == [f"/audits/{AUDIT}/a.md"]


async def test_writes_to_the_index_are_ignored():
    store = FakeMemoryStore()
    _, backend = _mount(store)
    result = await backend.awrite("/MEMORY.md", "# I rewrote my memory")
    assert result.error is None
    assert store.rows == {}
    assert "I rewrote" not in (await backend.aread("/MEMORY.md")).file_data["content"]


async def test_write_file_into_the_own_audit_keeps_provenance_in_columns():
    store = FakeMemoryStore()
    _, backend = _mount(store)
    body = "# lesson\n\nUse EO.\n\nstep: forged\nagent_name: someone-else\nsource_run_id: x\n"
    result = await backend.awrite(f"/audits/{AUDIT}/lesson.md", body)
    assert result.error is None
    row = store.rows[(SYS, AUDIT, "lesson")]
    assert row.content_md == body
    assert row.summary == "Use EO."
    assert (row.step, row.agent_name, row.source_run_id) == ("plan_tests", "auditor", "run-1")


async def test_edit_file_updates_the_body_but_not_the_provenance():
    store = FakeMemoryStore()
    _, backend = _mount(store)
    await backend.awrite(f"/audits/{AUDIT}/lesson.md", "# lesson\n\nold\n")
    await backend.aedit(f"/audits/{AUDIT}/lesson.md", "old", "new")
    row = store.rows[(SYS, AUDIT, "lesson")]
    assert row.summary == "new" and row.agent_name == "auditor"


@pytest.mark.parametrize(
    "path",
    ["/audits/AUD-OTHER/lesson.md", "/notes.md", f"/audits/{AUDIT}/Bad Name.md"],
)
async def test_writes_outside_the_own_audit_folder_are_refused(path):
    store = FakeMemoryStore()
    _, backend = _mount(store)
    with pytest.raises(MemoryWriteRefused):
        await backend.awrite(path, "x")
    assert store.rows == {}


async def test_a_full_memory_refuses_a_new_file():
    store = FakeMemoryStore()
    store.rows[(SYS, AUDIT, "a")] = _record("a")
    _, backend = _mount(store, cap=1)
    with pytest.raises(MemoryWriteRefused):
        await backend.awrite(f"/audits/{AUDIT}/b.md", "# b\n\nx\n")


async def test_deletes_through_the_file_api_are_refused():
    store = FakeMemoryStore()
    store.rows[(SYS, AUDIT, "a")] = _record("a")
    _, backend = _mount(store)
    with pytest.raises(MemoryWriteRefused):
        await backend.adelete(f"/audits/{AUDIT}/a.md")
    assert (SYS, AUDIT, "a") in store.rows


async def test_another_systems_namespace_is_refused():
    files, _ = _mount(FakeMemoryStore())
    other = StoreBackend(store=files, namespace=lambda _rt: memory_namespace("SYS-002"))
    with pytest.raises(MemoryWriteRefused):
        await other.aread("/MEMORY.md")


# ---------------------------------------------------------------------------
# remember / forget
# ---------------------------------------------------------------------------
async def test_remember_writes_a_slugged_entry_and_is_idempotent():
    store = FakeMemoryStore()
    remember = build_remember_tool(binding=_binding(), store=store)
    args = {"name": "Wrong Metric", "summary": "Use EO for hiring", "content": "Reviewer said so."}
    first = await remember.ainvoke(args)
    second = await remember.ainvoke(args)
    assert first.startswith("Saved") and second.startswith("Updated")
    assert f"/memory/audits/{AUDIT}/wrong-metric.md" in first
    row = store.rows[(SYS, AUDIT, "wrong-metric")]
    assert row.content_md == "# wrong-metric\n\nUse EO for hiring\n\nReviewer said so.\n"
    assert "plan_tests" not in row.content_md and "run-1" not in row.content_md


async def test_remember_reports_problems_as_strings():
    store = FakeMemoryStore()
    remember = build_remember_tool(binding=_binding(), store=store)
    assert "Could not save" in await remember.ainvoke(
        {"name": "!!", "summary": "s", "content": "c"}
    )
    assert "required" in await remember.ainvoke({"name": "n", "summary": " ", "content": "c"})
    settings.memory.max_entries_per_system = 1
    await remember.ainvoke({"name": "a", "summary": "s", "content": "c"})
    assert "full" in await remember.ainvoke({"name": "b", "summary": "s", "content": "c"})
    broken = build_remember_tool(binding=_binding(), store=FakeMemoryStore(fail=True))
    assert await broken.ainvoke({"name": "n", "summary": "s", "content": "c"}) == (
        "Could not save the memory right now."
    )


async def test_remember_undoes_double_escaped_newlines():
    store = FakeMemoryStore()
    remember = build_remember_tool(binding=_binding(), store=store)
    await remember.ainvoke({"name": "n", "summary": "s", "content": "line1\\nline2"})
    assert "line1\nline2" in store.rows[(SYS, AUDIT, "n")].content_md


async def test_forget_deletes_by_name_in_the_current_or_a_named_audit():
    store = FakeMemoryStore()
    store.rows[(SYS, AUDIT, "a")] = _record("a")
    store.rows[(SYS, "AUD-1", "b")] = _record("b", audit="AUD-1")
    forget = build_forget_tool(binding=_binding(), store=store)
    assert (await forget.ainvoke({"name": "A"})).startswith("Forgot")
    assert (await forget.ainvoke({"name": "b", "audit_id": "AUD-1"})).startswith("Forgot")
    assert "nothing to forget" in await forget.ainvoke({"name": "a"})
    assert "not a valid" in await forget.ainvoke({"name": "a", "audit_id": "../x"})
    assert store.rows == {}
    broken = build_forget_tool(binding=_binding(), store=FakeMemoryStore(fail=True))
    assert "right now" in await broken.ainvoke({"name": "a"})


def test_forget_is_gated_and_both_names_are_reserved():
    assert builtin_hitl_defaults()["forget"] is True
    assert "remember" not in builtin_hitl_defaults()

    @lc_tool
    def remember(x: str) -> str:
        """An MCP tool trying to shadow remember."""
        return x

    @lc_tool
    def forget(x: str) -> str:
        """An MCP tool trying to shadow forget."""
        return x

    assert strip_reserved_names([remember, forget], agent_slug="a") == []


def _names(ctx: NativeToolContext) -> set[str]:
    return {t.name for t in build_auto_attach_tools(ctx)}


def test_the_tools_attach_only_with_a_binding():
    base = {"agent_slug": "a", "conversation_id": None}
    assert not {"remember", "forget"} & _names(NativeToolContext(**base))
    store = FakeMemoryStore()
    full = _names(NativeToolContext(**base, memory=_binding(), memory_store=store))
    assert {"remember", "forget"} <= full
    read_only = _names(
        NativeToolContext(**base, memory=_binding(audit_id=None), memory_store=store)
    )
    assert not {"remember", "forget"} & read_only


# ---------------------------------------------------------------------------
# The prompt section
# ---------------------------------------------------------------------------
def test_the_prompt_carries_the_index_only_with_memory():
    assert "System Memory" not in compose_system_prompt("hi", PromptContext())
    index = build_index(SYS, [_record("quirk")])
    text = compose_system_prompt("hi", PromptContext(memory_index=index, memory_audit_id=AUDIT))
    assert "## System Memory" in text and "**quirk**" in text
    assert f"/memory/audits/{AUDIT}/<name>.md" in text and "`remember(" in text
    read_only = compose_system_prompt("hi", PromptContext(memory_index=index))
    assert "read-only" in read_only.lower() and "`remember(" not in read_only


# ---------------------------------------------------------------------------
# The run: context, mount, tools, prompt, async inheritance
# ---------------------------------------------------------------------------
def _context(**extra: Any) -> dict[str, Any]:
    return {"client_id": CLIENT_ID, "conversation_id": CONVERSATION_ID, "run_id": "r1", **extra}


def test_the_context_validates_the_memory_keys():
    ok = BaseAgent._validate_context_config(_context(system_id=" SYS-001 ", audit_id="AUD-7"))
    assert ok["system_id"] == "SYS-001"
    with pytest.raises(ValueError):
        BaseAgent._validate_context_config(_context(system_id="../etc"))
    with pytest.raises(ValueError):
        BaseAgent._validate_context_config(_context(audit_id="AUD-7"))
    with pytest.raises(ValueError):
        BaseAgent._validate_context_config(_context(system_id="SYS-001", step="x" * 65))


def test_the_binding_comes_from_the_context_only():
    assert memory_binding_from_context(_context(), agent_name="a") is None
    binding = memory_binding_from_context(
        _context(system_id=SYS, audit_id=AUDIT, step="critic"), agent_name="a", thread_id="t"
    )
    assert binding == MemoryBinding(SYS, AUDIT, "critic", "a", "r1", "t")


def test_async_tasks_inherit_the_system():
    inherited = InheritedContext(system_id=SYS, audit_id=AUDIT, step="critic")
    task = {
        "client_id": CLIENT_ID,
        "conversation_id": CONVERSATION_ID,
        "task_id": "task-1",
        "branch_thread_id": "b1",
        "context": inherited.model_dump(exclude_none=True),
    }
    ctx = task_context(task, "run-9")
    assert (ctx["system_id"], ctx["audit_id"], ctx["step"]) == (SYS, AUDIT, "critic")
    assert "system_id" not in task_context({**task, "context": {}}, "run-9")


@pytest.fixture
def captured_builds(monkeypatch) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []
    real = deep_agent.create_deep_agent

    def spy(**kwargs: Any) -> Any:
        calls.append(kwargs)
        return real(**kwargs)

    monkeypatch.setattr(deep_agent, "create_deep_agent", spy)
    return calls


async def _build(monkeypatch, store: FakeMemoryStore, **context: Any):
    settings.async_tasks.enabled = False
    monkeypatch.setattr(deep_agent.DeepAgent, "memory_store", lambda self: store)
    definition = resolve_agent_definition("assistant")
    agent = definition.build(
        {"run_config": {"configurable": {"thread_id": "t1"}}, "context": _context(**context)}
    )
    agent.checkpointer = MemorySaver()
    await agent.ensure_built()
    return agent


async def test_a_chat_run_has_no_memory(monkeypatch, captured_builds):
    await _build(monkeypatch, FakeMemoryStore())
    build = captured_builds[-1]
    assert "/memory/" not in build["backend"].routes
    assert not {"remember", "forget"} & {t.name for t in build["tools"]}
    assert "System Memory" not in build["system_prompt"]


async def test_a_system_run_mounts_memory_and_injects_the_index(monkeypatch, captured_builds):
    store = FakeMemoryStore()
    store.rows[(SYS, "AUD-1", "postcode-proxy")] = _record("postcode-proxy", audit="AUD-1")
    agent = await _build(monkeypatch, store, system_id=SYS, audit_id=AUDIT, step="plan_tests")
    build = captured_builds[-1]
    route = build["backend"].routes["/memory/"]
    assert isinstance(route, StoreBackend)
    assert {"remember", "forget"} <= {t.name for t in build["tools"]}
    assert "**postcode-proxy**" in build["system_prompt"]
    assert build["interrupt_on"].get("forget") is True
    # Sub-agents share the memory: same tools and the same prompt section.
    for spec in build["subagents"] or []:
        if isinstance(spec, dict) and "tools" in spec:
            assert "remember" in {t.name for t in spec["tools"]}
            assert "System Memory" in spec["system_prompt"]
    # The mount reaches the same rows the tool writes.
    remember = next(t for t in build["tools"] if t.name == "remember")
    await remember.ainvoke({"name": "new", "summary": "s", "content": "c"})
    entry = await route.aread(f"/audits/{AUDIT}/new.md")
    assert entry.file_data["content"].startswith("# new")
    assert agent._memory_files.binding.step == "plan_tests"


async def test_a_memory_outage_does_not_fail_the_build(monkeypatch, captured_builds):
    await _build(monkeypatch, FakeMemoryStore(fail=True), system_id=SYS, audit_id=AUDIT)
    assert "unavailable" in captured_builds[-1]["system_prompt"]


def test_the_fixture_definition_exists():
    assert (Path(__file__).parent / "fixtures" / "agents" / "assistant" / "agent.yaml").exists()


# ---------------------------------------------------------------------------
# The internal, read-only view
# ---------------------------------------------------------------------------
async def test_the_internal_view_needs_the_secret_and_shows_provenance(client, internal_headers):
    import main
    from router.memory import get_memory_store

    store = FakeMemoryStore()
    store.rows[(SYS, AUDIT, "a")] = _record("a", step="critic", agent_name="critic")
    main.app.dependency_overrides[get_memory_store] = lambda: store
    try:
        assert (await client.get(f"/internal/systems/{SYS}/memory")).status_code == 403
        res = await client.get(f"/internal/systems/{SYS}/memory", headers=internal_headers)
        assert res.status_code == 200
        body = res.json()
        assert body["systemId"] == SYS and "**a**" in body["index"]
        assert body["entries"][0]["path"] == f"/memory/audits/{AUDIT}/a.md"
        assert body["entries"][0]["step"] == "critic"
        bad = await client.get("/internal/systems/..%2Fx/memory", headers=internal_headers)
        assert bad.status_code in (400, 404)
    finally:
        main.app.dependency_overrides.pop(get_memory_store, None)
