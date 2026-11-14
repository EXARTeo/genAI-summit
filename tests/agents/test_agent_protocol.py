"""``/ap`` through the real ``langgraph_sdk`` client, served in process as in production.

Pinned: every call deepagents' middleware makes round-trips; a client-chosen
thread id, a ``command`` and a ``webhook`` are refused; the authorisation
matrix (no token, forged, expired, another client, conversation or branch, a
sibling task, no internal secret); a child task answers only to its parent
task; a task waiting on its children reads busy and hides a failed run; a
parent reading a settled task records the delivery.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
from async_helpers import (
    BRANCH,
    OTHER_CLIENT,
    SLUG,
    ScriptedAgent,
    graph_id,
    mint,
    sdk,
    task_env,
    until,
)
from pydantic import SecretStr

from core.settings import settings
from utils.async_tasks import run_view, thread_status

pytestmark = pytest.mark.asyncio


async def test_sdk_round_trip_of_every_call_deepagents_makes():
    async with task_env() as env:
        gate = asyncio.Event()

        async def hold(agent: ScriptedAgent, payload: dict, command: Any) -> str:
            await gate.wait()
            return "researcher done"

        env.script.behaviours["researcher"] = hold
        client = sdk(mint())
        thread = await client.threads.create(
            metadata={"subagent_name": "researcher", "parent_thread_id": BRANCH}
        )
        assert thread["status"] == "busy"
        assert set(thread) >= {"thread_id", "status", "metadata", "values", "interrupts"}
        run = await client.runs.create(
            thread_id=thread["thread_id"],
            assistant_id=graph_id("researcher"),
            input={"messages": [{"role": "user", "content": "please research"}]},
        )
        assert run["thread_id"] == thread["thread_id"]
        assert run["status"] in ("pending", "running")
        got = await client.runs.get(thread_id=thread["thread_id"], run_id=run["run_id"])
        assert got["run_id"] == run["run_id"]
        listed = await client.runs.list(thread_id=thread["thread_id"], limit=1)
        assert [r["run_id"] for r in listed] == [run["run_id"]]

        await until(lambda: env.store.tasks[thread["thread_id"]]["status"] == "running")
        gate.set()
        await env.runner.idle()
        done = await client.threads.get(thread_id=thread["thread_id"])
        assert done["status"] == "idle"
        assert done["values"]["messages"][-1]["content"] == "researcher done"
        # Reading the settled task as its parent is a delivery: no wake-up follows.
        assert env.store.tasks[thread["thread_id"]]["parent_notified_at"] is not None
        finished = await client.runs.get(thread_id=thread["thread_id"], run_id=run["run_id"])
        assert finished["status"] == "success"
        cancelled = await client.runs.cancel(thread_id=thread["thread_id"], run_id=run["run_id"])
        assert cancelled["status"] == "success"  # an ended run is left alone


async def test_command_webhook_and_client_thread_ids_are_refused():
    async with task_env():
        client = sdk(mint())
        thread = await client.threads.create(metadata={"subagent_name": "researcher"})
        body = {
            "thread_id": thread["thread_id"],
            "input": {"messages": [{"role": "user", "content": "x"}]},
        }
        for extra in ({"command": {"resume": "yes"}}, {"webhook": "https://evil.example/hook"}):
            with pytest.raises(httpx.HTTPStatusError) as exc:
                await client.runs.create(assistant_id=graph_id("researcher"), **body, **extra)
            assert exc.value.response.status_code == 400
        with pytest.raises(httpx.HTTPStatusError) as exc:
            await client.runs.create(assistant_id=graph_id("helper"), **body)
        assert exc.value.response.status_code == 400  # not this task's sub-agent
        with pytest.raises(httpx.HTTPStatusError) as exc:
            await client.threads.create(
                thread_id=str(uuid.uuid4()), metadata={"subagent_name": "researcher"}
            )
        assert exc.value.response.status_code == 422


async def test_authorisation_matrix(monkeypatch):
    monkeypatch.setattr(settings.proxy, "internal_service_secret", SecretStr("s3cret"))
    async with task_env():
        owner = sdk(mint())
        thread = await owner.threads.create(metadata={"subagent_name": "researcher"})
        task_id = thread["thread_id"]
        assert (await owner.threads.get(thread_id=task_id))["thread_id"] == task_id

        sibling = mint(caller_task_id=str(uuid.uuid4()), caller_depth=1, caller_path=["researcher"])
        refusals = {
            "no token": (sdk(None), 401),
            "forged": (sdk(mint()[:-4] + "AAAA"), 401),
            "expired": (sdk(mint(ttl_seconds=-10)), 401),
            "other client": (sdk(mint(client_id=OTHER_CLIENT)), 404),
            "other conversation": (sdk(mint(conversation_id="c-2")), 404),
            "other branch": (sdk(mint(branch_thread_id="branch-2")), 404),
            "other agent version": (sdk(mint(definition_version="fedcba9876543210")), 404),
            "a sibling task": (sdk(sibling), 404),
            "no internal secret": (sdk(mint(), internal=False), 403),
        }
        for label, (client, code) in refusals.items():
            with pytest.raises(httpx.HTTPStatusError) as exc:
                await client.threads.get(thread_id=task_id)
            assert exc.value.response.status_code == code, label


async def test_a_child_task_answers_only_to_its_parent_task():
    async with task_env() as env:
        owner = sdk(mint())
        parent = await owner.threads.create(metadata={"subagent_name": "researcher"})
        as_parent = sdk(
            mint(caller_task_id=parent["thread_id"], caller_depth=1, caller_path=["researcher"])
        )
        child = await as_parent.threads.create(metadata={"subagent_name": "helper"})
        row = env.store.tasks[child["thread_id"]]
        assert row["parent_task_id"] == parent["thread_id"] and row["depth"] == 2
        assert row["subagent_path"] == "researcher/helper"
        with pytest.raises(httpx.HTTPStatusError) as exc:
            await owner.threads.get(thread_id=child["thread_id"])
        assert exc.value.response.status_code == 404
        got = await as_parent.threads.get(thread_id=child["thread_id"])
        assert got["thread_id"] == child["thread_id"]


async def test_waiting_children_reads_busy_and_hides_a_failed_run():
    task = {
        "task_id": "t",
        "status": "waiting_children",
        "agent_slug": SLUG,
        "definition_version": "v",
        "subagent_path": "researcher",
    }
    run = {"run_id": "r", "status": "error", "error": "boom", "created_at": datetime.now(UTC)}
    assert thread_status(task) == "busy"
    view = run_view(task, run, "r")
    assert view.status == "success" and view.error is None
    task["status"] = "error"
    assert run_view(task, run, "r").status == "error"
    assert thread_status(task) == "error"
    assert thread_status({**task, "status": "waiting"}) == "interrupted"
    assert thread_status({**task, "status": "cancelled"}) == "idle"
