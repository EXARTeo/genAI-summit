"""MCP is optional: a run never fails because the MCP gateway is absent.

Pinned:

* no gateway URL configured -> no session and no network call;
* a gateway that refuses the connection, or accepts it but never finishes the
  handshake, -> no session within the connect timeout, and the run goes ahead;
* once a session is up, anything the caller's own work raises propagates
  unchanged: it is never swallowed as if it were a gateway outage;
* a live tool is keyed ``server_id/tool_name``, the form an ``agent.yaml``
  names it in, with the server inferred for the names the gateway serves bare;
* with MCP off a run does not warn that its declared MCP tools are "missing",
  and a run paused on an MCP tool's approval resumes into an error result the
  model can read.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest
from langchain.agents import create_agent
from langchain.agents.middleware import HumanInTheLoopMiddleware
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.tools import tool
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from core.settings import settings
from harness.abstractions import base_agent
from harness.abstractions.deep_agent import DeepAgent
from utils import mcp_tools
from utils.mcp_tools import build_tool_cache_key, get_tool_cache_key, optional_mcp_session

_GATEWAY = "http://mcp-gateway.test:8005/sse"


@pytest.fixture
def mcp_url(monkeypatch):
    def configure(url: str, timeout: float = 0.2) -> None:
        monkeypatch.setattr(settings.mcp, "mcp_gateway_url", url)
        monkeypatch.setattr(settings.mcp, "connect_timeout_seconds", timeout)

    return configure


async def _session() -> object:
    async with optional_mcp_session() as session:
        return session


async def test_no_gateway_configured_means_no_session_and_no_call(mcp_url, monkeypatch):
    mcp_url("")

    def must_not_connect(*_args, **_kwargs):
        raise AssertionError("must not contact a gateway when MCP is off")

    monkeypatch.setattr(mcp_tools, "sse_client", must_not_connect)
    assert settings.mcp.enabled is False
    assert await _session() is None


async def test_a_blank_url_counts_as_no_gateway(mcp_url):
    mcp_url("   ")
    assert settings.mcp.enabled is False
    assert await _session() is None


async def test_a_gateway_that_refuses_the_connection_gives_no_session(mcp_url, monkeypatch):
    mcp_url(_GATEWAY)

    @asynccontextmanager
    async def refused(**_kwargs):
        raise ConnectionError("Name or service not known")
        yield  # pragma: no cover

    monkeypatch.setattr(mcp_tools, "sse_client", refused)
    assert await _session() is None


async def test_a_gateway_that_never_finishes_its_handshake_times_out(mcp_url, monkeypatch):
    mcp_url(_GATEWAY, timeout=0.1)

    @asynccontextmanager
    async def hangs(**_kwargs):
        await asyncio.sleep(3600)  # accepts the connection, never sends its endpoint
        yield None, None  # pragma: no cover

    monkeypatch.setattr(mcp_tools, "sse_client", hangs)
    loop = asyncio.get_running_loop()
    started = loop.time()
    assert await _session() is None
    assert loop.time() - started < 2


class _FakeSession:
    def __init__(self, *_args):
        self.initialized = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc):
        return False

    async def initialize(self):
        self.initialized = True


class _HangingInitSession(_FakeSession):
    async def initialize(self):
        await asyncio.sleep(3600)  # connected, but the MCP handshake never completes


def _working_gateway(monkeypatch, session_cls=_FakeSession) -> list[dict]:
    calls: list[dict] = []

    @asynccontextmanager
    async def ok(**kwargs):
        calls.append(kwargs)
        yield "read", "write"

    monkeypatch.setattr(mcp_tools, "sse_client", ok)
    monkeypatch.setattr(mcp_tools.mcp, "ClientSession", session_cls)
    return calls


async def test_a_reachable_gateway_yields_an_initialized_session(mcp_url, monkeypatch):
    mcp_url(_GATEWAY, timeout=0.5)
    calls = _working_gateway(monkeypatch)
    session = await _session()
    assert isinstance(session, _FakeSession) and session.initialized
    assert calls == [{"url": _GATEWAY, "timeout": 0.5}]


async def test_a_handshake_that_never_completes_times_out(mcp_url, monkeypatch):
    mcp_url(_GATEWAY, timeout=0.1)
    _working_gateway(monkeypatch, _HangingInitSession)
    loop = asyncio.get_running_loop()
    started = loop.time()
    assert await _session() is None
    assert loop.time() - started < 2


async def test_the_callers_own_error_is_never_swallowed(mcp_url, monkeypatch):
    mcp_url(_GATEWAY, timeout=0.1)
    _working_gateway(monkeypatch)
    with pytest.raises(ValueError, match="the agent run failed"):
        async with optional_mcp_session() as session:
            assert session is not None
            await asyncio.sleep(0.3)  # longer than the connect timeout: it must not fire
            raise ValueError("the agent run failed")


# ---------------------------------------------------------------------------
# Tool keys
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("server", "name", "key"),
    [
        ("tavily", "tavily-search", "tavily/tavily-search"),
        (" arxiv ", " search_papers ", "arxiv/search_papers"),
        ("", "plain_tool", "plain_tool"),
        (None, "plain_tool", "plain_tool"),
    ],
)
def test_build_tool_cache_key(server, name, key):
    assert build_tool_cache_key(server, name) == key


@pytest.mark.parametrize(
    ("name", "key"),
    [
        ("tavily-search", "tavily/tavily-search"),
        ("Tavily-Extract", "tavily/Tavily-Extract"),
        ("search_papers", "arxiv/search_papers"),
        ("some_other_tool", "some_other_tool"),
        ("", ""),
    ],
)
def test_a_live_tools_key_infers_its_server(name, key):
    assert get_tool_cache_key(SimpleNamespace(name=name)) == key


def test_a_tool_without_a_name_has_an_empty_key():
    assert get_tool_cache_key(object()) == ""


# ---------------------------------------------------------------------------
# A run with MCP off: declared MCP tools are expected absent, not "missing"
# ---------------------------------------------------------------------------
class _RecordingLogger:
    def __init__(self):
        self.events: list[tuple[str, str]] = []

    def info(self, event, *_args, **_kwargs):
        self.events.append(("info", event))

    def warning(self, event, *_args, **_kwargs):
        self.events.append(("warning", event))


def _filter(monkeypatch, tools, *, declared=(), all_tools=False):
    recorder = _RecordingLogger()
    monkeypatch.setattr(base_agent, "logger", recorder)
    agent = base_agent.BaseAgent()
    agent.config_tool_names = list(declared)
    agent.all_mcp_tools = all_tools
    return agent._filter_live_tools(tools), recorder.events


_SEARCH = SimpleNamespace(name="tavily-search")
_PAPERS = SimpleNamespace(name="search_papers")


def test_no_missing_tools_warning_when_mcp_is_off(mcp_url, monkeypatch):
    mcp_url("")
    tools, events = _filter(monkeypatch, [], declared=["tavily/tavily-search"])
    assert tools == []
    assert events == [("info", "agent_tools_mcp_disabled")]


def test_a_gateway_that_lacks_declared_tools_still_warns(mcp_url, monkeypatch):
    # MCP on: an absent declared tool is a real gap worth a warning.
    mcp_url(_GATEWAY)
    _tools, events = _filter(monkeypatch, [_PAPERS], declared=["tavily/tavily-search"])
    assert ("warning", "agent_tools_missing") in events


def test_only_the_declared_live_tools_are_attached(mcp_url, monkeypatch):
    mcp_url(_GATEWAY)
    tools, events = _filter(monkeypatch, [_PAPERS, _SEARCH], declared=["tavily/tavily-search"])
    assert tools == [_SEARCH]
    assert ("warning", "agent_tools_missing") not in events


def test_all_mcp_tools_attaches_every_live_tool_once(mcp_url, monkeypatch):
    mcp_url(_GATEWAY)
    duplicate = SimpleNamespace(name="tavily-search")
    tools, _events = _filter(monkeypatch, [_SEARCH, _PAPERS, duplicate], all_tools=True)
    assert tools == [_SEARCH, _PAPERS]


def test_an_agent_declaring_no_mcp_tools_takes_none(mcp_url, monkeypatch):
    mcp_url(_GATEWAY)
    tools, events = _filter(monkeypatch, [_SEARCH])
    assert tools == []
    assert events == []


# ---------------------------------------------------------------------------
# Resume: a run paused on an MCP tool's approval, resumed with no MCP
# ---------------------------------------------------------------------------
class _ToolCallingFake(GenericFakeChatModel):
    def bind_tools(self, tools, **kwargs):
        return self


async def test_approving_an_mcp_tool_after_mcp_went_away_returns_an_error_to_the_model():
    """The approved call reaches a tool node that no longer has the tool (the
    resume attached no MCP tools): the model gets an error ToolMessage it can
    read and the run carries on; nothing crashes."""

    @tool
    def tavily_search(query: str) -> str:
        """Search the web."""
        return "results"

    @tool
    def write_todos(todos: str) -> str:
        """A builtin the agent always has."""
        return "ok"

    checkpointer = InMemorySaver()
    config = {"configurable": {"thread_id": "paused-on-mcp"}}

    def build(tools, replies):
        middleware = [
            HumanInTheLoopMiddleware(interrupt_on={"tavily_search": True}),
            *DeepAgent._ensure_platform_middleware([]),
        ]
        model = _ToolCallingFake(messages=iter(replies))
        return create_agent(
            model=model, tools=tools, middleware=middleware, checkpointer=checkpointer
        )

    call = AIMessage(
        content="", tool_calls=[{"id": "call-1", "name": "tavily_search", "args": {"query": "x"}}]
    )
    paused = build([tavily_search, write_todos], [call])
    first = await paused.ainvoke({"messages": [HumanMessage(content="search")]}, config)
    assert first.get("__interrupt__"), "the MCP tool call must pause for approval"
    # Resumed on a deployment (or at a moment) without MCP: builtins only.
    resumed = build([write_todos], [AIMessage(content="search is unavailable right now")])
    result = await resumed.ainvoke(Command(resume={"decisions": [{"type": "approve"}]}), config)

    tool_messages = [m for m in result["messages"] if isinstance(m, ToolMessage)]
    assert len(tool_messages) == 1
    assert tool_messages[0].status == "error"
    assert "tavily_search" in tool_messages[0].content
    assert result["messages"][-1].content == "search is unavailable right now"
