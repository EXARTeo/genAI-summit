"""``/tasks`` — the backend's internal task API, keyed by the anonymous ``client_id``.

Pinned: every route answers the shapes of ``docs/contracts/agents-contract.md``; another
client's task is a 404 on every route; the internal secret is required; with
async sub-agents off, ``/unnotified`` and ``/cancel-scope`` are no-ops and the
others 503.
"""

from __future__ import annotations

import asyncio
from typing import Any

import httpx
import pytest
from async_helpers import (
    CLIENT,
    CONVERSATION,
    OTHER_CLIENT,
    ScriptedAgent,
    graph_id,
    mint,
    protocol_app,
    task_env,
    until,
)
from pydantic import SecretStr

from core.security.internal_trust import INTERNAL_SECRET_HEADER, internal_service_headers
from core.settings import settings
from harness.async_tasks.runner import set_task_runner
from harness.async_tasks.token import verify_launch_token

pytestmark = pytest.mark.asyncio


def _http(app: Any, *, internal: bool = True) -> httpx.AsyncClient:
    """An HTTP client on ``app``, sending the internal secret as the backend does."""
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://agents",
        headers=internal_service_headers() if internal else {},
    )


async def _settled_task(env: Any) -> str:
    task = await env.runner.create_task(verify_launch_token(mint()), "researcher")
    await env.runner.create_run(
        task,
        assistant_id=graph_id("researcher"),
        messages=[{"content": "go"}],
        strategy="interrupt",
    )
    await env.runner.idle()
    return task["task_id"]


async def test_get_list_unnotified_and_notified():
    async with task_env() as env, _http(env.app) as http:
        task_id = await _settled_task(env)

        got = await http.get(f"/tasks/{task_id}", params={"client_id": CLIENT})
        assert got.status_code == 200
        assert got.json()["client_id"] == CLIENT and got.json()["status"] == "success"
        listed = await http.get(
            "/tasks", params={"client_id": CLIENT, "conversation_id": CONVERSATION}
        )
        assert [t["task_id"] for t in listed.json()] == [task_id]

        unnotified = await http.get("/tasks/unnotified", params={"client_id": CLIENT})
        assert [o["task_id"] for o in unnotified.json()] == [task_id]
        assert unnotified.json()[0]["notification"]["additional_kwargs"]["lc_source"]

        done = await http.post(f"/tasks/{task_id}/notified", json={"client_id": CLIENT})
        assert done.status_code == 204
        assert (await http.get("/tasks/unnotified")).json() == []


async def test_another_clients_task_is_not_found_everywhere():
    async with task_env() as env, _http(env.app) as http:
        task_id = await _settled_task(env)
        other = {"client_id": OTHER_CLIENT}
        answers = [
            await http.get(f"/tasks/{task_id}", params=other),
            await http.post(f"/tasks/{task_id}/notified", json=other),
            await http.post(f"/tasks/{task_id}/cancel", json={**other, "reason": "user"}),
            await http.post(
                f"/tasks/{task_id}/resume",
                json={**other, "decisions": {"i": {"decision": "approve"}}},
            ),
        ]
        assert [a.status_code for a in answers] == [404, 404, 404, 404]
        listed = await http.get(
            "/tasks", params={"client_id": OTHER_CLIENT, "conversation_id": CONVERSATION}
        )
        assert listed.json() == []
        assert env.store.tasks[task_id]["parent_notified_at"] is None


async def test_cancel_resume_and_cancel_scope():
    async with task_env() as env, _http(env.app) as http:
        gate = asyncio.Event()

        async def hold(agent: ScriptedAgent, payload: dict, command: Any) -> str:
            await gate.wait()
            return "never"

        env.script.behaviours["researcher"] = hold
        claims = verify_launch_token(mint())
        first = await env.runner.create_task(claims, "researcher")
        second = await env.runner.create_task(claims, "researcher")
        for task in (first, second):
            await env.runner.create_run(
                task,
                assistant_id=graph_id("researcher"),
                messages=[{"content": "go"}],
                strategy="interrupt",
            )
        await until(lambda: len(env.runner._active) == 2)

        stopped = await http.post(
            f"/tasks/{first['task_id']}/cancel", json={"client_id": CLIENT, "reason": "user"}
        )
        assert stopped.status_code == 200 and stopped.json()["status"] == "cancelled"
        resumed = await http.post(
            f"/tasks/{second['task_id']}/resume",
            json={"client_id": CLIENT, "decisions": {"i": {"decision": "approve"}}},
        )
        assert resumed.status_code == 409  # not waiting for an approval

        scope = await http.post(
            "/tasks/cancel-scope", json={"client_id": CLIENT, "conversation_id": CONVERSATION}
        )
        assert scope.json() == {"cancelled": 1}
        assert env.store.tasks[second["task_id"]]["cancel_reason"] == "scope"
        await env.runner.idle()


async def test_the_internal_secret_is_required(monkeypatch):
    monkeypatch.setattr(settings.proxy, "internal_service_secret", SecretStr("s3cret"))
    async with task_env() as env, _http(env.app, internal=False) as http:
        assert (await http.get("/tasks/unnotified")).status_code == 403
        ok = await http.get("/tasks/unnotified", headers={INTERNAL_SECRET_HEADER: "s3cret"})
        assert ok.status_code == 200


async def test_with_async_subagents_off_the_api_is_inert():
    set_task_runner(None)
    async with _http(protocol_app()) as http:
        assert (await http.get("/tasks/unnotified")).json() == []
        scope = await http.post("/tasks/cancel-scope", json={"client_id": CLIENT})
        assert scope.json() == {"cancelled": 0}
        assert (await http.get("/tasks/t", params={"client_id": CLIENT})).status_code == 503
