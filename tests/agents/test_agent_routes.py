"""The run routes around the agent: lookup, build, uploads, MCP, fork, stream.

``router/inference.py`` only translates HTTP; ``utils.inference`` does the work.
These tests drive the routes with a stand-in agent (``route_fakes``) and pin
each step ``stream_run`` takes before and after the agent's own stream:

* ``GET /agents`` lists the registry's manifests by name;
* the agent's frames reach the backend byte for byte, then the checkpoint;
* a definition that cannot be built is a 400, not a stream;
* uploads are ingested for the run's client and conversation;
* the MCP session's tools are attached (none when MCP is off);
* ``fork_from`` seeds the new branch thread from the parent's checkpoint,
  after the agent is built, and only on ``/stream``.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any

import pytest
import route_fakes
from conftest import CLIENT_ID, CONVERSATION_ID, run_config

from schema.catalog import AgentDefinition
from utils import agents as agents_module
from utils import inference

_MESSAGES = [{"id": "m1", "role": "user", "content": "Hello"}]


@pytest.fixture(autouse=True)
def _no_uploads(monkeypatch, memory_file_store):
    """The uploads step writes to an in-memory store, never ``agent_runtime``."""
    monkeypatch.setattr(inference, "ConversationFileStore", lambda _pool: memory_file_store)


def _stream(client, headers, config=None, messages=None, slug="fake"):
    return client.post(
        f"/agents/{slug}/stream",
        headers=headers,
        json={
            "messages": _MESSAGES if messages is None else messages,
            "config": run_config() if config is None else config,
        },
    )


def _manifest(slug: str, name: str) -> dict[str, Any]:
    return {
        "id": slug,
        "slug": slug,
        "name": name,
        "type": "deep agent",
        "description": name,
        "icon": "bot",
    }


async def test_agents_route_returns_manifests_sorted_by_name(client, internal_headers, monkeypatch):
    registry = {
        slug: AgentDefinition(slug=slug, manifest=_manifest(slug, name), factory=lambda _c: None)
        for slug, name in (("z-agent", "Z Agent"), ("a-agent", "A Agent"))
    }
    monkeypatch.setattr(agents_module, "AGENT_REGISTRY", registry)
    response = await client.get("/agents", headers=internal_headers)
    assert response.status_code == 200
    assert [item["name"] for item in response.json()] == ["A Agent", "Z Agent"]
    assert not any(item["default"] for item in response.json())


async def test_stream_forwards_the_agent_frames_unchanged(client, internal_headers, monkeypatch):
    class _Raw(route_fakes.FakeAgent):
        async def astream(self, payload, *, command=None):
            yield b'data: {"type": "RUN_STARTED"}\n\n'
            yield b'data: {"type": "RUN_FINISHED"}\n\n'

    route_fakes.install(monkeypatch, _Raw)
    response = await _stream(client, internal_headers)
    assert response.status_code == 200
    prefix = 'data: {"type": "RUN_STARTED"}\n\ndata: {"type": "RUN_FINISHED"}\n\n'
    assert response.text.startswith(prefix)
    (committed,) = route_fakes.sse_events(response.text[len(prefix) :])
    assert (committed["type"], committed["name"]) == ("CUSTOM", "CHECKPOINT_COMMITTED")
    assert committed["value"] == {"thread_id": "t1", "checkpoint_id": "cp-1"}


@pytest.mark.parametrize("error", [TypeError("bad config"), ValueError("bad config")])
async def test_stream_answers_400_when_the_agent_cannot_be_built(
    client, internal_headers, monkeypatch, error
):
    def factory(_config):
        raise error

    definition = AgentDefinition(slug="bad", manifest={}, factory=factory)
    monkeypatch.setattr(inference, "resolve_agent_definition", lambda _slug: definition)
    response = await _stream(client, internal_headers, slug="bad")
    assert response.status_code == 400
    assert response.json() == {"detail": "Failed to initialise the requested agent."}


async def test_stream_hands_the_agent_its_messages_and_config(
    client, internal_headers, monkeypatch
):
    built = route_fakes.install(monkeypatch)
    config = run_config(thread_id="branch-2", run_id="run-9")
    response = await _stream(client, internal_headers, config=config)
    assert response.status_code == 200
    (agent,) = built
    assert agent.context == config["context"]
    assert agent.run_config == {"configurable": {"thread_id": "branch-2"}}
    assert agent.payloads == [{"messages": _MESSAGES}]
    assert agent.commands == [None]


async def test_stream_ingests_uploads_for_the_runs_client_and_conversation(
    client, internal_headers, monkeypatch
):
    route_fakes.install(monkeypatch)
    calls: list[dict[str, Any]] = []

    async def fake_ingest(store, **kwargs):
        calls.append(kwargs)
        return []

    monkeypatch.setattr(inference, "ingest_uploads", fake_ingest)
    response = await _stream(client, internal_headers)
    assert response.status_code == 200
    assert calls == [
        {"client_id": CLIENT_ID, "conversation_id": CONVERSATION_ID, "messages": _MESSAGES}
    ]


class _FakeSession:
    """Stands for an initialized MCP session (never touched: tools are loaded by a fake)."""


async def test_stream_attaches_the_mcp_sessions_tools(client, internal_headers, monkeypatch):
    built = route_fakes.install(monkeypatch)
    session = _FakeSession()
    loaded: list[Any] = []

    @asynccontextmanager
    async def fake_session():
        yield session

    async def fake_load(received):
        loaded.append(received)
        return [SimpleNamespace(name="tavily-search")]

    monkeypatch.setattr(inference, "optional_mcp_session", fake_session)
    monkeypatch.setattr(inference, "load_mcp_tools", fake_load)
    response = await _stream(client, internal_headers)
    assert response.status_code == 200
    assert loaded == [session]
    assert built[0].tools_names == ["tavily-search"]


async def test_stream_without_mcp_attaches_no_tools_and_loads_none(
    client, internal_headers, monkeypatch
):
    built = route_fakes.install(monkeypatch)

    async def must_not_load(_session):
        raise AssertionError("no MCP session, so no tools are loaded")

    monkeypatch.setattr(inference, "load_mcp_tools", must_not_load)
    response = await _stream(client, internal_headers)
    assert response.status_code == 200
    assert built[0].attached == []


@pytest.fixture
def seeds(monkeypatch) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []

    async def fake_seed(**kwargs):
        calls.append(kwargs)
        return True

    monkeypatch.setattr(inference, "seed_thread_from_checkpoint", fake_seed)
    return calls


async def test_fork_from_seeds_the_new_branch_from_the_parent_checkpoint(
    client, internal_headers, monkeypatch, seeds
):
    built = route_fakes.install(monkeypatch)
    config = run_config(
        thread_id="branch-new", fork_from={"thread_id": "branch-old", "checkpoint_id": "cp-7"}
    )
    response = await _stream(client, internal_headers, config=config)
    assert response.status_code == 200
    (agent,) = built
    assert agent.built, "the graph is compiled before the seed reads it"
    assert seeds == [
        {
            "graph": agent.compiled,
            "source_thread_id": "branch-old",
            "source_checkpoint_id": "cp-7",
            "target_thread_id": "branch-new",
        }
    ]
    # Delta fork: only the new message goes in, on top of the seeded state.
    assert agent.payloads == [{"messages": _MESSAGES}]


async def test_no_fork_from_means_no_seed(client, internal_headers, monkeypatch, seeds):
    route_fakes.install(monkeypatch)
    response = await _stream(client, internal_headers)
    assert response.status_code == 200
    assert seeds == []


async def test_a_malformed_fork_from_is_ignored(client, internal_headers, monkeypatch, seeds):
    route_fakes.install(monkeypatch)
    response = await _stream(client, internal_headers, config=run_config(fork_from="branch-old"))
    assert response.status_code == 200
    assert seeds == []


async def test_a_failing_seed_ends_the_stream_with_a_run_error(
    client, internal_headers, monkeypatch
):
    built = route_fakes.install(monkeypatch)

    async def broken_seed(**_kwargs):
        raise RuntimeError("seed failed")

    monkeypatch.setattr(inference, "seed_thread_from_checkpoint", broken_seed)
    config = run_config(fork_from={"thread_id": "old", "checkpoint_id": "cp"})
    response = await _stream(client, internal_headers, config=config)
    assert response.status_code == 200
    assert [event["type"] for event in route_fakes.sse_events(response.text)] == ["RUN_ERROR"]
    assert built[0].payloads == []
