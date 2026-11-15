"""The TaskRunner's rules, with scripted agents in place of built deep agents.

Pinned: a task runs, settles and rings the outbox with the backend's shapes
(``client_id``, never ``user_id``); the run context and the Langfuse trace a
task run is built with; the client id is hashed in the log context; the
pending guard, interrupting follow-ups and reopening; the caps; a user stop of
a subtree; a nested child waking its idle parent; an approval pause and its
resume; the watchdog; startup recovery.
"""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from typing import Any

import fakeredis.aioredis
import pytest
from async_helpers import (
    CLIENT,
    CONVERSATION,
    VERSION,
    FakeTaskStore,
    ScriptedAgent,
    echo,
    graph_id,
    mint,
    stream_entries,
    task_env,
    until,
)
from langchain_core.messages import HumanMessage

from core.logging import get_context
from core.settings import settings
from harness.async_tasks import runner as runner_mod
from harness.async_tasks.events import (
    OUTBOX_STREAM,
    STATUS_STREAM,
    TaskStreamPublisher,
    task_events_key,
)
from harness.async_tasks.runner import (
    RUN_RESTARTED,
    RUN_TIMED_OUT,
    DefinitionUnavailable,
    TaskRefused,
    TaskRunner,
    task_context,
)
from harness.async_tasks.token import InheritedContext, trace_carrier, verify_launch_token
from schema.async_tasks import OutboxItem, TaskOut

pytestmark = pytest.mark.asyncio

TRACE = {
    "trace_id": "a" * 32,
    "parent_observation_id": "b" * 16,
    "traceparent": f"00-{'a' * 32}-{'b' * 16}-01",
    "user_id": "h:0123456789abcdef",
    "session_id": CONVERSATION,
}


async def _start(env: Any, name: str = "researcher", text: str = "find apples", **claims: Any):
    task = await env.runner.create_task(verify_launch_token(mint(**claims)), name)
    path = [*claims.get("caller_path", []), name]
    await env.runner.create_run(
        task, assistant_id=graph_id(*path), messages=[{"content": text}], strategy="interrupt"
    )
    return task["task_id"]


async def test_a_task_runs_settles_and_rings_the_outbox():
    async with task_env() as env:
        task_id = await _start(env)
        await env.runner.idle()

        row = env.store.tasks[task_id]
        assert row["status"] == "success"
        assert row["client_id"] == CLIENT
        assert "find apples" in row["result_preview"]
        assert row["model"] == "gpt-test"

        status = await stream_entries(env.redis, STATUS_STREAM)
        assert status[0]["event"] == "TASK_STARTED"
        assert status[-1]["event"] == "TASK_SETTLED"
        settled = TaskOut.model_validate(status[-1]["task"])
        assert settled.client_id == CLIENT and "user_id" not in status[-1]["task"]
        assert settled.usage.input_tokens == 10 and settled.usage.calls == 1

        outbox = await stream_entries(env.redis, OUTBOX_STREAM)
        item = OutboxItem.model_validate(outbox[0])
        assert item.client_id == CLIENT and item.status == "success"
        assert not item.cancelled_by_user
        assert item.notification.additional_kwargs["lc_source"] == "async_subagent"
        assert item.notification.additional_kwargs["lc_data"]["task_id"] == task_id

        events = await stream_entries(env.redis, f"task:{task_id}:events")
        assert [e["type"] for e in events] == ["RUN_STARTED", "CUSTOM", "RUN_FINISHED"]
        assert await env.redis.ttl(f"task:{task_id}:events") > 0


async def test_a_task_run_context_is_rebuilt_from_its_row():
    task = {
        "task_id": "t-1",
        "client_id": CLIENT,
        "conversation_id": CONVERSATION,
        "branch_thread_id": "branch-root",
        "context": {"interactive": False},
    }
    assert task_context(task, "run-9") == {
        "client_id": CLIENT,
        "conversation_id": CONVERSATION,
        "run_id": "run-9",
        "thread_id": "t-1",
        "branch_thread_id": "branch-root",
        "async_task_id": "t-1",
        "interactive": False,
    }


class _FakeDeep:
    """Stands in for ``DeepAgent`` in ``build_agent``'s isinstance check."""

    def __init__(self, config: dict[str, Any], version: str) -> None:
        self.config = config
        self.version = version
        self.async_task_node = None

    def definition_fingerprint(self) -> str:
        return self.version


async def test_a_task_run_is_built_with_the_spawning_runs_trace(monkeypatch):
    versions = ["stale-version", VERSION]

    async def candidates(slug: str):
        for version in versions:
            yield SimpleNamespace(build=lambda config, v=version: _FakeDeep(config, v))

    monkeypatch.setattr(runner_mod, "DeepAgent", _FakeDeep)
    monkeypatch.setattr(runner_mod, "definition_candidates", candidates)
    runner = TaskRunner(FakeTaskStore(), TaskStreamPublisher(client=fakeredis.aioredis.FakeRedis()))
    claims = verify_launch_token(mint(context=InheritedContext(trace=trace_carrier(TRACE))))
    task = await runner.create_task(claims, "researcher")

    agent = await runner.build_agent(task, "run-x")
    assert agent.version == VERSION  # the pinned definition, not the first candidate
    assert agent.config["trace"] == TRACE
    assert agent.config["context"]["client_id"] == CLIENT
    assert agent.config["run_config"] == {"configurable": {"thread_id": task["task_id"]}}
    node = agent.async_task_node
    assert node.client_id == CLIENT and node.path == ("researcher",) and node.depth == 1

    versions[:] = ["edited"]
    with pytest.raises(DefinitionUnavailable):
        await runner.build_agent(task, "run-y")


async def test_a_task_without_a_trace_builds_without_one(monkeypatch):
    async def candidates(slug: str):
        yield SimpleNamespace(build=lambda config: _FakeDeep(config, VERSION))

    monkeypatch.setattr(runner_mod, "DeepAgent", _FakeDeep)
    monkeypatch.setattr(runner_mod, "definition_candidates", candidates)
    runner = TaskRunner(FakeTaskStore(), TaskStreamPublisher(client=fakeredis.aioredis.FakeRedis()))
    malformed = trace_carrier({"trace_id": "not-hex", "parent_observation_id": "x"})
    assert malformed is None
    task = await runner.create_task(verify_launch_token(mint()), "researcher")
    assert "trace" not in (await runner.build_agent(task, "r")).config


async def test_the_client_id_is_hashed_in_the_run_log_context():
    seen: dict[str, Any] = {}

    async def capture(agent: ScriptedAgent, payload: dict, command: Any) -> str:
        seen.update(get_context())
        return "ok"

    async with task_env() as env:
        env.script.behaviours["researcher"] = capture
        await _start(env)
        await env.runner.idle()
    assert seen["client_id"].startswith("h:") and seen["client_id"] != CLIENT
    assert "user_id" not in seen


async def test_the_pending_guard_folds_a_follow_up_into_a_run_that_has_not_started():
    async with task_env() as env:
        gate = asyncio.Event()
        build = env.script.build

        async def slow_build(task: dict, run_id: str) -> ScriptedAgent:
            await gate.wait()
            return await build(task, run_id)

        env.runner.build_agent = slow_build
        task = await env.runner.create_task(verify_launch_token(mint()), "researcher")
        kwargs = {"assistant_id": graph_id("researcher"), "strategy": "interrupt"}
        first = await env.runner.create_run(task, messages=[{"content": "find apples"}], **kwargs)
        second = await env.runner.create_run(task, messages=[{"content": "also pears"}], **kwargs)
        assert second["run_id"] == first["run_id"]
        gate.set()
        await env.runner.idle()
        assert await env.store.count_runs(task["task_id"]) == 1
        result = env.store.tasks[task["task_id"]]["result"]["content"]
        assert "find apples" in result and "also pears" in result
        # The folded follow-up still shows apart in the task's own stream (its drill-down).
        entries = await env.redis.xrange(task_events_key(task["task_id"]))
        inputs = [
            json.loads(fields["data"])
            for _id, fields in entries
            if json.loads(fields["data"]).get("name") == "TASK_INPUT"
        ]
        assert [event["value"]["text"] for event in inputs] == ["also pears"]


async def test_a_follow_up_interrupts_the_active_run_and_a_settled_task_reopens():
    async with task_env() as env:
        gate = asyncio.Event()
        calls: list[str] = []

        async def hold_first(agent: ScriptedAgent, payload: dict, command: Any) -> str:
            calls.append(agent.run_id)
            if len(calls) == 1:
                await gate.wait()
            return await echo(agent, payload, command)

        env.script.behaviours["researcher"] = hold_first
        task_id = await _start(env)
        await until(lambda: bool(calls))
        task = await env.store.get_task(task_id)
        kwargs = {"assistant_id": graph_id("researcher"), "strategy": "interrupt"}
        await env.runner.create_run(task, messages=[{"content": "pears instead"}], **kwargs)
        await env.runner.idle()
        first, second = sorted(env.store.runs.values(), key=lambda r: r["_seq"])
        assert first["status"] == "interrupted" and second["status"] == "success"
        assert "pears instead" in env.store.tasks[task_id]["result"]["content"]
        assert env.store.tasks[task_id]["status"] == "success"

        # A settled task is reopened by a follow-up: same thread, settle cleared.
        settled = await env.store.get_task(task_id)
        await env.runner.create_run(settled, messages=[{"content": "and plums"}], **kwargs)
        await env.runner.idle()
        assert env.store.tasks[task_id]["status"] == "success"
        assert await env.store.count_runs(task_id) == 3
        assert await env.redis.ttl(f"task:{task_id}:events") > 0
        statuses = [e["task"]["status"] for e in await stream_entries(env.redis, STATUS_STREAM)]
        assert statuses.count("success") == 2  # settled twice, so the backend wakes twice


async def test_caps_fail_closed(monkeypatch):
    async with task_env() as env:
        claims = verify_launch_token(mint())
        monkeypatch.setattr(settings.async_tasks, "max_children_per_task", 1)
        await env.runner.create_task(claims, "researcher")
        with pytest.raises(TaskRefused) as exc:
            await env.runner.create_task(claims, "researcher")
        assert exc.value.status_code == 429
        monkeypatch.setattr(settings.async_tasks, "max_children_per_task", 8)
        monkeypatch.setattr(settings.async_tasks, "max_active_per_user", 1)
        with pytest.raises(TaskRefused) as exc:
            await env.runner.create_task(claims, "researcher")
        assert exc.value.status_code == 429
        monkeypatch.setattr(settings.async_tasks, "max_active_per_user", 16)
        too_deep = verify_launch_token(mint(caller_depth=3, caller_path=["a", "b", "c"]))
        with pytest.raises(TaskRefused) as exc:
            await env.runner.create_task(too_deep, "d")
        assert exc.value.status_code == 400

        monkeypatch.setattr(settings.async_tasks, "max_runs_per_task", 1)
        task_id = await _start(env, "helper")
        await env.runner.idle()
        task = await env.store.get_task(task_id)
        with pytest.raises(TaskRefused) as exc:
            await env.runner.create_run(
                task,
                assistant_id=graph_id("helper"),
                messages=[{"content": "again"}],
                strategy="interrupt",
            )
        assert exc.value.status_code == 429
        with pytest.raises(TaskRefused) as exc:
            await env.runner.create_run(
                task, assistant_id=graph_id("other"), messages=[], strategy="interrupt"
            )
        assert exc.value.status_code == 400


async def test_a_user_stop_cancels_the_subtree_and_is_marked_as_the_users():
    async with task_env() as env:
        gate = asyncio.Event()

        async def hold(agent: ScriptedAgent, payload: dict, command: Any) -> str:
            await gate.wait()
            return "never"

        env.script.behaviours["researcher"] = hold
        env.script.behaviours["helper"] = hold
        parent_id = await _start(env)
        child_id = await _start(
            env, "helper", caller_task_id=parent_id, caller_depth=1, caller_path=["researcher"]
        )
        await until(lambda: len(env.runner._active) == 2)
        assert await env.runner.cancel(parent_id, "user") == 2
        await env.runner.idle()

        parent, child = env.store.tasks[parent_id], env.store.tasks[child_id]
        assert parent["status"] == child["status"] == "cancelled"
        assert parent["cancel_reason"] == "user" and child["cancel_reason"] == "cascade"
        assert parent["parent_notified_at"] is None  # the backend skips it (cancelled_by_user)
        outbox = await stream_entries(env.redis, OUTBOX_STREAM)
        assert [(o["task_id"], o["cancelled_by_user"]) for o in outbox] == [(parent_id, True)]


async def test_a_settled_child_wakes_its_idle_parent_with_the_notification():
    async with task_env() as env:
        child_gate = asyncio.Event()
        child_ids: list[str] = []

        async def parent(agent: ScriptedAgent, payload: dict, command: Any) -> str:
            first = payload["messages"][0]
            if isinstance(first, HumanMessage) and first.additional_kwargs.get("lc_source"):
                return "parent reports: " + first.additional_kwargs["lc_data"]["status"]
            child_ids.append(
                await _start(
                    env,
                    "helper",
                    "dig",
                    caller_task_id=agent.task["task_id"],
                    caller_depth=1,
                    caller_path=["researcher"],
                )
            )
            return "delegated"

        async def child(agent: ScriptedAgent, payload: dict, command: Any) -> str:
            await child_gate.wait()
            return "child found it"

        env.script.behaviours["researcher"] = parent
        env.script.behaviours["helper"] = child
        parent_id = await _start(env)
        await until(lambda: env.store.tasks[parent_id]["status"] == "waiting_children")
        assert await stream_entries(env.redis, OUTBOX_STREAM) == []
        child_gate.set()
        await until(lambda: env.store.tasks[parent_id]["status"] == "success")
        await env.runner.idle()

        kinds = [r["kind"] for r in sorted(env.store.runs.values(), key=lambda r: r["_seq"])]
        assert kinds.count("wake") == 1
        assert env.store.tasks[child_ids[0]]["parent_notified_at"] is not None
        assert env.store.tasks[parent_id]["result"]["content"] == "parent reports: success"
        outbox = await stream_entries(env.redis, OUTBOX_STREAM)
        assert [o["task_id"] for o in outbox] == [parent_id]  # depth 2 never reaches it


async def test_an_approval_pauses_the_task_and_a_resume_finishes_it():
    interrupt_id = "c" * 32
    pending: dict[str, list[Any]] = {}

    async with task_env() as env:
        build = env.script.build

        async def build_with_checkpoint(task: dict, run_id: str) -> ScriptedAgent:
            agent = await build(task, run_id)
            agent.interrupts = list(pending.get(task["task_id"], []))
            return agent

        async def gated(agent: ScriptedAgent, payload: dict, command: Any) -> str:
            if command is None:
                value = {"action_requests": [{"name": "danger", "args": {}}]}
                pending[agent.task["task_id"]] = [SimpleNamespace(id=interrupt_id, value=value)]
                agent.interrupts = pending[agent.task["task_id"]]
                return ""
            pending.clear()
            agent.interrupts = []
            return f"approved: {command.resume[interrupt_id]['decisions'][0]['type']}"

        env.runner.build_agent = build_with_checkpoint
        env.script.behaviours["researcher"] = gated
        task_id = await _start(env)
        await env.runner.idle()
        assert env.store.tasks[task_id]["status"] == "waiting"

        task = await env.store.get_task(task_id)
        with pytest.raises(TaskRefused) as exc:
            await env.runner.create_run(
                task, assistant_id=graph_id("researcher"), messages=[], strategy="interrupt"
            )
        assert exc.value.status_code == 409  # only the user answers an approval
        with pytest.raises(TaskRefused) as exc:
            await env.runner.resume(task, {"d" * 32: {"decision": "approve"}})
        assert exc.value.status_code == 409  # a stale interrupt id

        await env.runner.resume(task, {interrupt_id: {"decision": "approve"}})
        await env.runner.idle()
        assert env.store.tasks[task_id]["status"] == "success"
        assert env.store.tasks[task_id]["result"]["content"] == "approved: approve"


async def test_the_watchdog_errors_a_run_that_runs_too_long(monkeypatch):
    monkeypatch.setattr(settings.async_tasks, "run_timeout_seconds", 0.05)

    async def forever(agent: ScriptedAgent, payload: dict, command: Any) -> str:
        await asyncio.Event().wait()
        return "never"

    async with task_env() as env:
        env.script.behaviours["researcher"] = forever
        task_id = await _start(env)
        await env.runner.idle()
        row = env.store.tasks[task_id]
        assert row["status"] == "error" and row["error"] == RUN_TIMED_OUT
        assert [r["status"] for r in env.store.runs.values()] == ["timeout"]


async def test_recovery_errors_cut_runs_and_settles_their_tasks():
    async with task_env() as env:
        claims = verify_launch_token(mint())
        task = await env.runner.create_task(claims, "researcher")
        await env.store.update_task(task["task_id"], {"status": "running"})
        await env.store.insert_run(
            {"run_id": "r-cut", "task_id": task["task_id"], "kind": "start", "status": "running"}
        )
        await env.runner.recover()
        assert env.store.runs["r-cut"]["status"] == "error"
        assert env.store.runs["r-cut"]["error"] == RUN_RESTARTED
        assert env.store.tasks[task["task_id"]]["status"] == "error"
        outbox = await stream_entries(env.redis, OUTBOX_STREAM)
        assert [o["status"] for o in outbox] == ["error"]
        assert env.runner._active == {}  # never woken: the parent decides


async def test_usage_events_are_summed_and_name_the_model():
    usage = runner_mod._Usage()
    for model, tokens in (("gpt-test", 10), ("other", 5)):
        usage.observe(
            {
                "type": "CUSTOM",
                "name": "TOKEN_USAGE",
                "value": {"model": model, "input_tokens": tokens, "output_tokens": 1},
            }
        )
    assert usage.model == "gpt-test"
    assert usage.totals == {"input_tokens": 15, "output_tokens": 2, "calls": 2}
