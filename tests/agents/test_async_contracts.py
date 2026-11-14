"""The pure parts of async sub-agents: the launch token, graph ids and specs, the notification
message, the in-process middleware, and the Redis publisher.

Pinned: the token is tamper-proof, expires, carries the client id and the
Langfuse trace (pattern-checked, fail-open) and refuses unknown inherited
fields; graph ids round-trip any sub-agent name and name only declared nodes;
the specs carry the internal secret and the token and nothing else; the
notification is exactly what the real middleware records (and a replayed
notice row keeps only its three metadata keys); our middleware keeps
upstream's tools and never leaves the process; a Redis failure never raises.
"""

from __future__ import annotations

import httpx
import pytest
from async_helpers import CLIENT, mint
from deepagents.middleware.async_subagents import AsyncSubAgentMiddleware, _notification_event
from langchain_core.messages import HumanMessage
from pydantic import SecretStr, ValidationError
from redis.exceptions import ConnectionError as RedisConnectionError

from core.security.internal_trust import INTERNAL_SECRET_HEADER
from core.settings import settings
from harness.async_tasks.client import AsyncTaskMiddleware
from harness.async_tasks.events import TaskStreamPublisher
from harness.async_tasks.notification import (
    build_notification,
    normalize_payload_messages,
    notification_payload,
    to_human_message,
)
from harness.async_tasks.specs import (
    GENERAL_PURPOSE_NAME,
    UnknownTaskNode,
    async_subagent_specs,
    graph_id_for,
    parse_graph_id,
    resolve_chain,
    supports_async,
    top_level,
)
from harness.async_tasks.token import (
    LAUNCH_TOKEN_HEADER,
    InheritedContext,
    LaunchTokenError,
    trace_carrier,
    verify_launch_token,
)

pytestmark = pytest.mark.asyncio

TRACE = {"trace_id": "a" * 32, "parent_observation_id": "b" * 16, "user_id": "h:0123456789abcdef"}


async def test_the_launch_token_is_tamper_proof_and_expires():
    token = mint(context=InheritedContext(interactive=False, trace=trace_carrier(TRACE)))
    claims = verify_launch_token(token)
    assert claims.client_id == CLIENT and claims.caller_task_id is None
    assert claims.context.interactive is False
    assert claims.context.trace is not None and claims.context.trace.trace_id == "a" * 32
    body, sig = token.split(".")
    for bad in (f"{body}x.{sig}", f"{body}.{sig[:-2]}xx", "", "a.b.c", None):
        with pytest.raises(LaunchTokenError):
            verify_launch_token(bad)
    with pytest.raises(LaunchTokenError):
        verify_launch_token(mint(ttl_seconds=-1))


async def test_the_launch_key_follows_the_secrets(monkeypatch):
    token = mint()
    monkeypatch.setattr(settings.proxy, "internal_service_secret", SecretStr("rotated"))
    with pytest.raises(LaunchTokenError):
        verify_launch_token(token)  # derived key changed with the service secret
    monkeypatch.setattr(settings.async_tasks, "launch_secret", SecretStr("explicit"))
    assert verify_launch_token(mint()).client_id == CLIENT


async def test_inherited_context_refuses_unknown_fields_and_bad_traces():
    with pytest.raises(ValidationError):
        InheritedContext.model_validate({"interactive": True, "tool_config": {}})
    assert trace_carrier(None) is None
    assert trace_carrier({"trace_id": "A" * 32, "parent_observation_id": "b" * 16}) is None
    assert trace_carrier({**TRACE, "user_id": CLIENT}) is None  # never the raw client id
    assert trace_carrier({**TRACE, "extra": 1}).model_dump(exclude_none=True) == TRACE


async def test_graph_ids_round_trip_and_name_only_declared_nodes():
    graph_id = graph_id_for("slug", "v1", ["re/search", "helper one"])
    assert parse_graph_id(graph_id) == ("slug", "v1", ["re/search", "helper one"])
    assert parse_graph_id("no-version:path") is None
    tree = [{"name": "researcher", "subagents": [{"name": "helper"}]}]
    assert top_level(tree, None)[0]["name"] == GENERAL_PURPOSE_NAME
    assert [s["name"] for s in resolve_chain(tree, None, ["researcher", "helper"])] == [
        "researcher",
        "helper",
    ]
    with pytest.raises(UnknownTaskNode):
        resolve_chain(tree, None, ["researcher", "nobody"])
    assert supports_async(tree) and supports_async(None)
    assert not supports_async([{"name": "x", "runnable": object()}])


async def test_specs_carry_the_secret_and_the_token_only(monkeypatch):
    monkeypatch.setattr(settings.proxy, "internal_service_secret", SecretStr("s3cret"))
    specs = async_subagent_specs(
        [{"name": "researcher", "description": "Researches."}],
        agent_slug="slug",
        definition_version="v1",
        parent_path=[],
        launch_token="tok",  # noqa: S106 (a test value)
    )
    assert specs[0]["headers"] == {INTERNAL_SECRET_HEADER: "s3cret", LAUNCH_TOKEN_HEADER: "tok"}
    assert specs[0]["graph_id"] == "slug@v1:researcher"
    assert specs[0]["url"].endswith("/ap") and specs[0]["notify_parent"] is False


async def test_the_notification_is_what_the_middleware_records():
    message = build_notification(
        task_id="t-1",
        agent_name="researcher",
        status="success",
        run_id="r-1",
        result=[{"type": "text", "text": "the answer"}],
    )
    human = to_human_message(message)
    assert _notification_event(human) == {
        "task_id": "t-1",
        "agent_name": "researcher",
        "status": "success",
        "run_id": "r-1",
    }
    tracked = {
        "t-1": {
            "task_id": "t-1",
            "agent_name": "researcher",
            "thread_id": "t-1",
            "run_id": "r-0",
            "status": "running",
            "created_at": "",
            "last_checked_at": "",
            "last_updated_at": "",
        }
    }
    recorded = AsyncSubAgentMiddleware._record_notification(
        {"messages": [human], "async_tasks": tracked}
    )
    assert recorded["async_tasks"]["t-1"]["status"] == "success"
    assert "the answer" in "".join(b["text"] for b in human.content)

    payload = notification_payload(message)
    assert set(payload["additional_kwargs"]) == {"lc_source", "lc_data", "deepagents_notification"}
    replayed = normalize_payload_messages(
        [
            {"role": "user", "content": "hi"},
            {
                "role": "user",
                "kind": "task_notification",
                "content": payload["content"],
                "additional_kwargs": {**payload["additional_kwargs"], "evil": 1},
            },
        ]
    )
    assert replayed[0] == {"role": "user", "content": "hi"}
    assert isinstance(replayed[1], HumanMessage)
    assert _notification_event(replayed[1])["task_id"] == "t-1"
    assert "evil" not in replayed[1].additional_kwargs


async def test_an_error_notification_carries_no_internals():
    message = build_notification(task_id="t", agent_name="a", status="error", run_id=None)
    text = "".join(b["text"] for b in message["content"])
    assert "The subagent failed." in text and "Traceback" not in text


async def test_the_in_process_middleware_keeps_upstreams_tools():
    spec = {"name": "r", "description": "d", "graph_id": "g", "url": "http://x"}
    upstream = AsyncSubAgentMiddleware(async_subagents=[spec])
    ours = AsyncTaskMiddleware(async_subagents=[spec])
    assert [t.name for t in ours.tools] == [t.name for t in upstream.tools]
    assert [t.description for t in ours.tools] == [t.description for t in upstream.tools]
    client = ours._clients.get_async("r")
    assert isinstance(client.http.client._transport, httpx.ASGITransport)
    with pytest.raises(ValueError):
        ours._clients.get_sync("r")


class _DeadRedis:
    """A Redis whose every call fails, as when the server is down."""

    async def xadd(self, *args, **kwargs):
        raise RedisConnectionError("down")

    async def expire(self, *args, **kwargs):
        raise RedisConnectionError("down")

    async def persist(self, *args, **kwargs):
        raise RedisConnectionError("down")

    async def aclose(self):
        raise RedisConnectionError("down")


async def test_a_redis_failure_never_fails_a_run():
    publisher = TaskStreamPublisher(client=_DeadRedis())
    await publisher.task_event("t", {"type": "RUN_STARTED"})
    await publisher.status("TASK_STARTED", {"task_id": "t"})
    await publisher.outbox({"task_id": "t"})
    await publisher.expire_events("t")
    await publisher.persist_events("t")
    await publisher.aclose()
