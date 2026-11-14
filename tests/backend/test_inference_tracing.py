"""Langfuse traceability of runs (``utils/tracing.py``): off by default, the
trace context handed to the agents service when on, and fail-open — a Langfuse
that cannot be built or that raises never fails or blocks a run."""

from __future__ import annotations

import json
from typing import Any

import pytest
from conftest import CLIENT_ID
from langfuse import Langfuse
from pydantic import SecretStr
from run_helpers import STREAM_PATH, answer, finished, sse_reply

import utils.inference_runs as ir
from core.settings import settings
from utils import tracing


class FakeSpan:
    def __init__(self, *, fail_update: bool = False) -> None:
        self.trace_id = "a" * 32
        self.id = "b" * 16
        self.updates: list[dict[str, Any]] = []
        self.ended = False
        self.fail_update = fail_update

    def update(self, **kwargs: Any) -> None:
        if self.fail_update:
            raise RuntimeError("langfuse exploded")
        self.updates.append(kwargs)

    def end(self) -> None:
        self.ended = True


class FakeLangfuse:
    """Records what the run did with the client."""

    instances: list[FakeLangfuse] = []
    span_factory: Any = FakeSpan
    create_trace_id = staticmethod(Langfuse.create_trace_id)

    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs
        self.observations: list[dict[str, Any]] = []
        self.spans: list[FakeSpan] = []
        FakeLangfuse.instances.append(self)

    def start_observation(self, **kwargs: Any) -> FakeSpan:
        self.observations.append(kwargs)
        span = FakeLangfuse.span_factory()
        self.spans.append(span)
        return span


@pytest.fixture
def fresh_tracing(monkeypatch, session_factory):
    monkeypatch.setattr(ir, "SessionLocal", session_factory)
    monkeypatch.setattr(tracing, "_client", None)
    monkeypatch.setattr(tracing, "_client_failed", False)
    FakeLangfuse.instances = []
    FakeLangfuse.span_factory = FakeSpan
    return session_factory


@pytest.fixture
def langfuse_on(monkeypatch, fresh_tracing):
    monkeypatch.setattr(settings.langfuse, "public_key", "pk-lf-test")
    monkeypatch.setattr(settings.langfuse, "secret_key", SecretStr("sk-lf-test"))
    return fresh_tracing


async def _run(client, agents_service, session_factory) -> tuple[Any, dict]:
    agents_service.on("POST", STREAM_PATH, sse_reply(*answer("Hello world")))
    response = await client.post(
        "/v1/inference/runs/start",
        json={
            "mode": "new",
            "agentSlug": "test-agent",
            "message": {"sender": "user", "content": "Hi"},
        },
    )
    assert response.status_code == 201, response.text
    run = await finished(response.json()["run"]["id"], session_factory)
    body = json.loads(agents_service.called("POST", STREAM_PATH)[-1].content)
    return run, body


async def test_disabled_tracing_never_builds_a_client(
    client, agents_service, fresh_tracing, monkeypatch
):
    def refuse(**_kwargs):
        raise AssertionError("Langfuse must not be constructed while tracing is off")

    monkeypatch.setattr(tracing, "Langfuse", refuse)
    run, body = await _run(client, agents_service, fresh_tracing)
    assert run.streaming_status == "completed"
    assert "trace" not in body["config"]


async def test_enabled_tracing_nests_the_agents_service_under_the_run(
    client, agents_service, langfuse_on, monkeypatch
):
    monkeypatch.setattr(tracing, "Langfuse", FakeLangfuse)
    run, body = await _run(client, agents_service, langfuse_on)
    assert run.streaming_status == "completed"

    (langfuse,) = FakeLangfuse.instances
    assert langfuse.kwargs["public_key"] == "pk-lf-test"
    observation = langfuse.observations[0]
    assert observation["name"] == tracing.RUN_TRACE_NAME
    assert observation["input"] == "Hi"
    assert observation["trace_context"]["trace_id"] == Langfuse.create_trace_id(seed=run.id)
    metadata = observation["metadata"]
    assert (metadata["run_id"], metadata["agent_slug"]) == (run.id, "test-agent")
    # The client id scopes a browser's data: only its keyed pseudonym is traced.
    assert metadata["user_id"].startswith("h:") and CLIENT_ID not in json.dumps(metadata)

    trace = body["config"]["trace"]
    assert trace["trace_id"] == "a" * 32 and trace["parent_observation_id"] == "b" * 16
    assert trace["traceparent"] == f"00-{'a' * 32}-{'b' * 16}-01"
    assert trace["session_id"] == run.conversation_id

    (span,) = langfuse.spans
    assert span.ended
    assert span.updates[-1]["output"] == "Hello world"
    assert span.updates[-1]["metadata"]["status"] == "completed"


async def test_a_client_that_cannot_be_built_leaves_the_run_untraced(
    client, agents_service, langfuse_on, monkeypatch
):
    def broken(**_kwargs):
        raise ValueError("bad host")

    monkeypatch.setattr(tracing, "Langfuse", broken)
    run, body = await _run(client, agents_service, langfuse_on)
    assert run.streaming_status == "completed"
    assert "trace" not in body["config"]


async def test_an_sdk_that_raises_mid_run_never_fails_the_run(
    client, agents_service, langfuse_on, monkeypatch
):
    monkeypatch.setattr(tracing, "Langfuse", FakeLangfuse)
    FakeLangfuse.span_factory = lambda: FakeSpan(fail_update=True)
    run, body = await _run(client, agents_service, langfuse_on)
    assert run.streaming_status == "completed"
    assert run.content == "Hello world"


async def test_a_failing_start_observation_leaves_the_run_untraced(
    client, agents_service, langfuse_on, monkeypatch
):
    class Exploding(FakeLangfuse):
        def start_observation(self, **kwargs: Any) -> FakeSpan:
            raise RuntimeError("exporter down")

    monkeypatch.setattr(tracing, "Langfuse", Exploding)
    run, body = await _run(client, agents_service, langfuse_on)
    assert run.streaming_status == "completed"
    assert "trace" not in body["config"]


def test_a_noop_trace_is_inert():
    trace = tracing.RunTrace()
    assert trace.upstream_context() is None
    trace.finish(status="completed", output="x")  # nothing to end, nothing raised
