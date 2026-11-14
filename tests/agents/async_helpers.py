"""Shared helpers of the async sub-agent tests: an in-memory task store, a scripted agent, an app.

* :class:`FakeTaskStore` — ``AsyncTaskStore`` with dicts, same methods and
  semantics (the SQL itself needs Postgres and is not exercised here);
* :class:`ScriptedAgent` — what ``TaskRunner.build_agent`` returns, driven by a
  test's ``behaviour`` coroutine instead of a model, so runner rules are tested
  without building a deep agent;
* :func:`protocol_app` — a bare FastAPI app with only ``/ap`` and ``/tasks``,
  registered as the in-process Agent Protocol app;
* small builders for launch tokens and ``langgraph_sdk`` clients.

No network, no Postgres, no model: Redis is fakeredis.
"""

from __future__ import annotations

import asyncio
import copy
import itertools
import json
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import fakeredis.aioredis
from fastapi import FastAPI
from langchain_core.messages import AIMessage
from langgraph_sdk.client import LangGraphClient

from core.security.internal_trust import internal_service_headers
from harness.async_tasks import client as client_mod
from harness.async_tasks.events import TaskStreamPublisher
from harness.async_tasks.runner import TaskRunner, set_task_runner
from harness.async_tasks.specs import graph_id_for, protocol_url
from harness.async_tasks.token import LAUNCH_TOKEN_HEADER, InheritedContext, mint_launch_token
from router.agent_protocol import router as agent_protocol_router
from router.tasks import router as tasks_router

CLIENT = "6f1c2f9e-0000-4000-8000-000000000001"
OTHER_CLIENT = "6f1c2f9e-0000-4000-8000-000000000002"
CONVERSATION = "c-1"
BRANCH = "branch-1"
SLUG = "async-test"
VERSION = "0123456789abcdef"
ACTIVE = ("pending", "running", "waiting_children")


class FakeTaskStore:
    """``AsyncTaskStore`` with dicts — same methods, same semantics."""

    def __init__(self) -> None:
        self.tasks: dict[str, dict[str, Any]] = {}
        self.runs: dict[str, dict[str, Any]] = {}
        self._seq = itertools.count()

    @staticmethod
    def _now() -> datetime:
        return datetime.now(UTC)

    def _out(self, row: dict[str, Any] | None) -> dict[str, Any] | None:
        return None if row is None else {k: v for k, v in copy.deepcopy(row).items() if k != "_seq"}

    def _sorted(self, rows: Any) -> list[dict[str, Any]]:
        return sorted(rows, key=lambda r: r["_seq"])

    async def setup(self) -> None:
        return None

    async def insert_task(self, task: dict[str, Any]) -> None:
        row = copy.deepcopy(dict(task))
        row.setdefault("parent_task_id", None)
        for key in (
            "result",
            "description",
            "model",
            "result_preview",
            "error",
            "cancel_reason",
            "settled_at",
            "parent_notified_at",
        ):
            row.setdefault(key, None)
        row["created_at"] = row["updated_at"] = self._now()
        row["_seq"] = next(self._seq)
        self.tasks[row["task_id"]] = row

    async def get_task(self, task_id: str) -> dict[str, Any] | None:
        return self._out(self.tasks.get(task_id))

    async def update_task(self, task_id: str, fields: dict[str, Any]) -> None:
        if task_id in self.tasks:
            self.tasks[task_id].update(copy.deepcopy(dict(fields)))
            self.tasks[task_id]["updated_at"] = self._now()

    async def mark_notified(self, task_id: str, when: datetime | None = None) -> bool:
        row = self.tasks.get(task_id)
        if row is None or row["parent_notified_at"] is not None or row["settled_at"] is None:
            return False
        row["parent_notified_at"] = when or self._now()
        return True

    async def clear_notified(self, task_id: str) -> None:
        row = self.tasks.get(task_id)
        if row is not None:
            row["parent_notified_at"] = None

    async def list_tasks(self, client_id: str, conversation_id: str, limit: int) -> list[dict]:
        rows = [
            r
            for r in self.tasks.values()
            if r["client_id"] == client_id and r["conversation_id"] == conversation_id
        ]
        return [self._out(r) for r in self._sorted(rows)[:limit]]

    async def children(self, task_id: str) -> list[dict[str, Any]]:
        rows = (r for r in self.tasks.values() if r["parent_task_id"] == task_id)
        return [self._out(r) for r in self._sorted(rows)]

    async def subtree_ids(self, task_id: str) -> list[str]:
        if task_id not in self.tasks:
            return []
        out, frontier = [task_id], [task_id]
        while frontier:
            frontier = [
                r["task_id"]
                for r in self._sorted(self.tasks.values())
                if r["parent_task_id"] in frontier
            ]
            out.extend(frontier)
        return out

    async def count_active_for_client(self, client_id: str) -> int:
        return sum(
            1 for r in self.tasks.values() if r["client_id"] == client_id and r["status"] in ACTIVE
        )

    async def count_active_children(
        self, *, parent_task_id: str | None, conversation_id: str, branch_thread_id: str
    ) -> int:
        open_ = (*ACTIVE, "waiting")
        if parent_task_id is not None:
            return sum(
                1
                for r in self.tasks.values()
                if r["parent_task_id"] == parent_task_id and r["status"] in open_
            )
        return sum(
            1
            for r in self.tasks.values()
            if r["parent_task_id"] is None
            and r["conversation_id"] == conversation_id
            and r["branch_thread_id"] == branch_thread_id
            and r["status"] in open_
        )

    async def unnotified(
        self, limit: int, *, client_id: str | None = None, conversation_id: str | None = None
    ) -> list[dict[str, Any]]:
        rows = [
            r
            for r in self.tasks.values()
            if r["parent_task_id"] is None
            and r["settled_at"] is not None
            and r["parent_notified_at"] is None
            and (not client_id or r["client_id"] == client_id)
            and (not conversation_id or r["conversation_id"] == conversation_id)
        ]
        return [self._out(r) for r in self._sorted(rows)[:limit]]

    async def scope_task_ids(
        self, client_id: str, *, conversation_id: str | None = None, root_run_id: str | None = None
    ) -> list[str]:
        return [
            r["task_id"]
            for r in self._sorted(self.tasks.values())
            if r["client_id"] == client_id
            and r["parent_task_id"] is None
            and (not conversation_id or r["conversation_id"] == conversation_id)
            and (not root_run_id or r["root_run_id"] == root_run_id)
        ]

    async def unsettled_task_ids(self) -> list[str]:
        rows = [r for r in self.tasks.values() if r["status"] in ACTIVE]
        return [r["task_id"] for r in sorted(rows, key=lambda r: (-r["depth"], r["_seq"]))]

    async def insert_run(self, run: dict[str, Any]) -> None:
        row = {
            "error": None,
            "usage": {},
            "waiting": False,
            "started_at": None,
            "ended_at": None,
            "multitask_strategy": None,
            **copy.deepcopy(dict(run)),
        }
        row["created_at"] = self._now()
        row["_seq"] = next(self._seq)
        self.runs[row["run_id"]] = row

    async def get_run(self, run_id: str) -> dict[str, Any] | None:
        return self._out(self.runs.get(run_id))

    async def update_run(self, run_id: str, fields: dict[str, Any]) -> None:
        if run_id in self.runs:
            self.runs[run_id].update(copy.deepcopy(dict(fields)))

    async def list_runs(self, task_id: str, *, limit: int, offset: int = 0) -> list[dict]:
        rows = sorted(
            (r for r in self.runs.values() if r["task_id"] == task_id), key=lambda r: -r["_seq"]
        )
        return [self._out(r) for r in rows[offset : offset + limit]]

    async def count_runs(self, task_id: str) -> int:
        return sum(1 for r in self.runs.values() if r["task_id"] == task_id)

    async def usage_totals(self, task_ids: Any) -> dict[str, dict[str, int]]:
        ids = set(task_ids)
        totals: dict[str, dict[str, int]] = {}
        for r in self.runs.values():
            if r["task_id"] in ids:
                bucket = totals.setdefault(r["task_id"], {})
                for key, value in (r.get("usage") or {}).items():
                    bucket[key] = bucket.get(key, 0) + value
        return totals

    async def fail_unfinished_runs(self, error: str) -> list[str]:
        cut = set()
        for r in self.runs.values():
            if r["status"] in ("pending", "running"):
                r.update(status="error", error=error, ended_at=self._now())
                cut.add(r["task_id"])
        return sorted(cut)


# ---------------------------------------------------------------------------
# A scripted agent: what TaskRunner.build_agent returns in these tests
# ---------------------------------------------------------------------------
#: ``behaviour(agent, payload, command) -> reply`` — awaited inside the run;
#: may block on events, raise, or set ``agent.interrupts`` to pause the run.
Behaviour = Callable[["ScriptedAgent", dict[str, Any], Any], Awaitable[str]]


def sse(event: dict[str, Any]) -> bytes:
    """One AG-UI event as the SSE frame ``BaseAgent.astream`` yields."""
    return f"data: {json.dumps(event)}\n\n".encode()


class ScriptedAgent:
    """Enough of a built ``DeepAgent`` for the runner: ``astream`` and its state."""

    def __init__(self, task: dict[str, Any], run_id: str, behaviour: Behaviour) -> None:
        self.task = task
        self.run_id = run_id
        self.behaviour = behaviour
        self.run_config = {"configurable": {"thread_id": task["task_id"]}}
        self.interrupts: list[Any] = []
        self.reply = ""
        self.inputs: list[Any] = []
        self.command: Any = None
        self.seen_tasks: dict[str, dict[str, Any]] = {}
        self.compiled = SimpleNamespace(aget_state=self._state)

    def attach_tools(self, tools: list[Any]) -> None:
        return None

    async def ensure_built(self) -> None:
        return None

    async def astream(self, payload: dict[str, Any], command: Any = None) -> AsyncIterator[bytes]:
        self.inputs = list(payload.get("messages") or [])
        self.command = command
        # What deepagents' middleware records from a notification input.
        for message in self.inputs:
            data = getattr(message, "additional_kwargs", {}).get("lc_data")
            if isinstance(data, dict):
                self.seen_tasks[data["task_id"]] = {"status": data["status"]}
        yield sse({"type": "RUN_STARTED", "threadId": self.task["task_id"], "runId": self.run_id})
        self.reply = await self.behaviour(self, payload, command)
        yield sse(
            {
                "type": "CUSTOM",
                "name": "TOKEN_USAGE",
                "value": {"model": "gpt-test", "input_tokens": 10, "output_tokens": 2},
            }
        )
        yield sse({"type": "RUN_FINISHED", "threadId": self.task["task_id"]})

    async def _state(self, _config: Any) -> SimpleNamespace:
        messages = [AIMessage(content=self.reply)] if self.reply else []
        return SimpleNamespace(
            values={"messages": messages, "async_tasks": self.seen_tasks},
            interrupts=self.interrupts,
        )


async def echo(agent: ScriptedAgent, payload: dict[str, Any], command: Any) -> str:
    """The default behaviour: answer with the input text."""
    texts = []
    for message in payload.get("messages") or []:
        content = message.get("content") if isinstance(message, dict) else message.content
        texts.append(content if isinstance(content, str) else json.dumps(content))
    return "done: " + " | ".join(texts)


class Script:
    """Per-task-name behaviours, and every agent the runner built."""

    def __init__(self) -> None:
        self.behaviours: dict[str, Behaviour] = {}
        self.built: list[ScriptedAgent] = []

    async def build(self, task: dict[str, Any], run_id: str) -> ScriptedAgent:
        agent = ScriptedAgent(task, run_id, self.behaviours.get(task["name"], echo))
        self.built.append(agent)
        return agent


@asynccontextmanager
async def no_mcp() -> AsyncIterator[None]:
    """The MCP session factory of a run with no gateway."""
    yield None


async def until(predicate: Callable[[], bool], timeout: float = 5.0) -> None:
    """Wait until ``predicate()`` holds."""

    async def poll() -> None:
        while not predicate():
            await asyncio.sleep(0.005)

    await asyncio.wait_for(poll(), timeout)


# ---------------------------------------------------------------------------
# The app, tokens and clients
# ---------------------------------------------------------------------------
def protocol_app() -> FastAPI:
    """A bare app serving ``/ap`` and ``/tasks``, registered for the in-process client."""
    app = FastAPI()
    app.include_router(agent_protocol_router)
    app.include_router(tasks_router)
    client_mod.set_protocol_app(app)
    return app


def mint(**overrides: Any) -> str:
    """A launch token for the orchestrator of ``CLIENT``/``CONVERSATION``/``BRANCH``."""
    claims: dict[str, Any] = {
        "client_id": CLIENT,
        "conversation_id": CONVERSATION,
        "root_run_id": "run-0",
        "branch_thread_id": BRANCH,
        "caller_task_id": None,
        "caller_depth": 0,
        "caller_path": [],
        "agent_slug": SLUG,
        "definition_version": VERSION,
        "context": InheritedContext(),
    }
    claims.update(overrides)
    return mint_launch_token(**claims)


def sdk(token: str | None, *, internal: bool = True) -> LangGraphClient:
    """A ``langgraph_sdk`` client served in process, as the middleware builds it."""
    headers = dict(internal_service_headers()) if internal else {}
    if token is not None:
        headers[LAUNCH_TOKEN_HEADER] = token
    return client_mod.protocol_client(protocol_url(), headers)


def graph_id(*path: str) -> str:
    """The graph id of a node of the test agent's tree."""
    return graph_id_for(SLUG, VERSION, list(path))


async def stream_entries(redis: Any, key: str) -> list[dict[str, Any]]:
    """Every entry of a Redis stream, decoded."""
    return [json.loads(fields["data"]) for _id, fields in await redis.xrange(key)]


@asynccontextmanager
async def task_env() -> AsyncIterator[SimpleNamespace]:
    """A runner over :class:`FakeTaskStore` and fakeredis, with scripted agents, installed
    as the process runner, plus the bare ``/ap`` + ``/tasks`` app."""
    store = FakeTaskStore()
    redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    runner = TaskRunner(store, TaskStreamPublisher(client=redis), mcp_session=no_mcp)
    script = Script()
    runner.build_agent = script.build  # type: ignore[method-assign]
    set_task_runner(runner)
    app = protocol_app()
    try:
        yield SimpleNamespace(store=store, redis=redis, runner=runner, script=script, app=app)
    finally:
        await runner.shutdown()
        set_task_runner(None)
