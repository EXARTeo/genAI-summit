"""Stand-in agents for the run-route tests (``/stream``, ``/resume``).

The routes only need an agent's run surface: its context, ``attach_tools``,
``astream`` and the compiled graph's ``aget_state``. These fakes implement
exactly that, so a route test pins what ``utils.inference`` does around a run
(validation, uploads, MCP, the resume command, the terminal frames) without
building a deep agent or calling a model.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Sequence
from types import SimpleNamespace
from typing import Any, ClassVar

from core.error_handling import agent_stream_error_handler
from core.logging import get_logger
from harness.agui.emitter import AGUIEmitter, encode
from schema.catalog import AgentDefinition
from utils import inference

logger = get_logger("tests.route_fakes")

#: What a fake run streams: a run start, one text delta, a run end.
DEFAULT_FRAMES: tuple[dict[str, Any], ...] = (
    {"type": "RUN_STARTED", "threadId": "t1", "runId": "r1"},
    {"type": "TEXT_MESSAGE_CONTENT", "messageId": "m1", "delta": "hello"},
    {"type": "RUN_FINISHED", "threadId": "t1", "runId": "r1"},
)


def interrupt(interrupt_id: str, actions: int = 1) -> SimpleNamespace:
    """A pending HITL interrupt as LangGraph exposes it: an id and the gate's request."""
    return SimpleNamespace(
        id=interrupt_id,
        value={"action_requests": [{"name": f"tool_{n}", "args": {}} for n in range(actions)]},
    )


class FakeCompiled:
    """The compiled graph's state reads: the pause and the checkpoint head."""

    def __init__(self, interrupts: Sequence[Any], checkpoint_id: str = "cp-1") -> None:
        self.interrupts = list(interrupts)
        self.checkpoint_id = checkpoint_id

    async def aget_state(self, config: Any) -> SimpleNamespace:
        return SimpleNamespace(
            interrupts=self.interrupts,
            values={"messages": []},
            config={"configurable": {"checkpoint_id": self.checkpoint_id}},
        )


class FakeAgent:
    """A built agent: streams ``frames`` and records what the route handed it."""

    frames: ClassVar[Sequence[dict[str, Any]]] = DEFAULT_FRAMES
    interrupts: ClassVar[Sequence[Any]] = ()

    def __init__(self, config: dict[str, Any] | None) -> None:
        self.config = dict(config or {})
        self.context = dict(self.config.get("context") or {})
        self.run_config = self.config.get("run_config") or {}
        self.compiled = FakeCompiled(type(self).interrupts)
        self.agui_emitter = AGUIEmitter()
        self.agui_normalizer = SimpleNamespace(seed_pending_tasks=lambda _messages: None)
        self.attached: list[Any] = []
        self.tools_names: list[str] = []
        self.payloads: list[Any] = []
        self.commands: list[Any] = []
        self.built = False

    @property
    def client_id(self) -> str:
        return str(self.context.get("client_id") or "")

    async def ensure_built(self) -> None:
        self.built = True

    def attach_tools(self, tools: Sequence[Any]) -> None:
        self.attached = list(tools)
        self.tools_names = [getattr(tool, "name", "") for tool in tools]

    async def astream(self, payload: Any, *, command: Any = None) -> AsyncIterator[bytes]:
        self.payloads.append(payload)
        self.commands.append(command)
        for frame in type(self).frames:
            yield encode(frame)

    def _encode_run_error(self, exc: BaseException) -> bytes:
        # The real encoding: a public message, never the exception's text.
        return agent_stream_error_handler.encode_run_error(logger, exc, agent_slug="fake")


class FailingAgent(FakeAgent):
    """Streams one frame, then the run breaks."""

    async def astream(self, payload: Any, *, command: Any = None) -> AsyncIterator[bytes]:
        self.payloads.append(payload)
        yield encode(DEFAULT_FRAMES[0])
        raise RuntimeError("internal failure: db password=hunter2")


def install(monkeypatch: Any, agent_cls: type = FakeAgent, slug: str = "fake") -> list[Any]:
    """Serve ``agent_cls`` under ``slug``; returns every agent the routes built."""
    built: list[Any] = []

    def factory(config: dict[str, Any] | None) -> Any:
        agent = agent_cls(config)
        built.append(agent)
        return agent

    definition = AgentDefinition(slug=slug, manifest={}, factory=factory)
    real = inference.resolve_agent_definition

    def resolve(requested: str) -> Any:
        return definition if requested == slug else real(requested)

    monkeypatch.setattr(inference, "resolve_agent_definition", resolve)
    return built


def sse_events(body: str) -> list[dict[str, Any]]:
    """The JSON events of an SSE body (comment frames skipped), asserting the framing."""
    assert body.endswith("\n\n"), "every frame ends with a blank line"
    events: list[dict[str, Any]] = []
    for frame in body.split("\n\n")[:-1]:
        if frame.startswith(":"):
            continue
        assert frame.startswith("data: "), frame
        events.append(json.loads(frame[len("data: ") :]))
    return events
