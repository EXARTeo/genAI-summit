"""Regressions found while porting: each pins one fixed contract or boundary rule."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import pytest
from conftest import CLIENT_ID, run_config
from route_fakes import FakeAgent, install, sse_events

from harness.filesystem.sandbox_backend import RemoteSandboxBackend
from utils import inference


class ErrorFrameAgent(FakeAgent):
    """A real agent's failure: ``astream`` encodes RUN_ERROR itself and returns."""

    async def astream(self, payload: Any, *, command: Any = None) -> AsyncIterator[bytes]:
        yield self._encode_run_error(RuntimeError("model failed"))


async def test_nothing_follows_a_run_error_frame(
    client, internal_headers, monkeypatch, memory_file_store
):
    # The contract: RUN_ERROR fails the run and nothing is sent after it, not
    # even CHECKPOINT_COMMITTED.
    install(monkeypatch, ErrorFrameAgent, slug="fake")
    monkeypatch.setattr(inference, "ConversationFileStore", lambda _pool: memory_file_store)

    response = await client.post(
        "/agents/fake/stream",
        json={"messages": [{"id": "m1", "role": "user", "content": "hi"}], "config": run_config()},
        headers=internal_headers,
    )

    assert [event["type"] for event in sse_events(response.text)] == ["RUN_ERROR"]


@pytest.mark.parametrize("slug", ["Assistant", "my_agent", "-x", "a" * 65])
def test_the_sandbox_refuses_a_slug_the_runner_would_reject(slug):
    # The runner accepts lowercase-hyphen slugs only; refusing here means a
    # malformed slug never becomes a confusing 422 from the runner.
    with pytest.raises(ValueError, match="agent slug"):
        RemoteSandboxBackend(
            client_id=CLIENT_ID, agent_slug=slug, conversation_id="c1", runner_url="http://runner"
        )


def test_the_sandbox_refuses_a_conversation_id_with_a_dot():
    with pytest.raises(ValueError, match="conversation id"):
        RemoteSandboxBackend(
            client_id=CLIENT_ID,
            agent_slug="assistant",
            conversation_id="c.1",
            runner_url="http://r",
        )
