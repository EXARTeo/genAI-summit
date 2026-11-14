"""MCP tool selection: one pass over the live gateway tools, builtins out of reach.

``BaseAgent._filter_live_tools`` decides which live gateway tools a run
attaches: the ones the agent declares (``config_tool_names``, cache keys), or
every one of them when the agent sets ``all_mcp_tools``. There is no per-client
tool configuration any more. Pinned:

* nothing declared and ``all_mcp_tools`` off attaches nothing, never the whole
  gateway;
* with MCP off (no ``MCP_GATEWAY_URL``) nothing attaches, whatever is declared;
* each tool attaches once; a declared key no live tool has attaches nothing;
* a deep agent drops a live tool named like a prebuilt one (``write_file``), so
  a gateway tool can never shadow a gated builtin.
"""

from __future__ import annotations

import pytest
from conftest import run_config

from core.settings import settings
from harness.abstractions import AgentSpec, YamlDeepAgent
from harness.abstractions import base_agent as base_agent_module
from harness.abstractions.base_agent import BaseAgent

KEYS = {
    "tavily-search": "tavily/tavily-search",
    "download_paper": "arxiv/download_paper",
    "sql_query": "rag/sql_query",
}
LIVE = ("tavily-search", "download_paper", "sql_query")


class FakeTool:
    def __init__(self, name: str):
        self.name = name


@pytest.fixture
def mcp_on():
    # The autouse fixture restores settings after the test.
    settings.mcp.mcp_gateway_url = "http://gateway.test/sse"


@pytest.fixture
def resolve(monkeypatch):
    """Run the real ``_filter_live_tools`` over a stub carrying just its inputs."""
    monkeypatch.setattr(
        base_agent_module, "get_tool_cache_key", lambda tool: KEYS.get(tool.name, tool.name)
    )

    def _resolve(*, declared=(), all_mcp_tools=False, live=LIVE):
        agent = BaseAgent.__new__(BaseAgent)
        agent.name = "stub"
        agent.config_tool_names = list(declared)
        agent.all_mcp_tools = all_mcp_tools
        return [t.name for t in agent._filter_live_tools([FakeTool(n) for n in live])]

    return _resolve


# ---------------------------------------------------------------------------
# Selection
# ---------------------------------------------------------------------------
def test_declared_tools_attach(resolve, mcp_on):
    assert sorted(resolve(declared=["arxiv/download_paper", "rag/sql_query"])) == [
        "download_paper",
        "sql_query",
    ]


def test_nothing_declared_attaches_nothing(resolve, mcp_on):
    assert resolve() == []


def test_all_mcp_tools_attaches_every_live_tool(resolve, mcp_on):
    assert resolve(all_mcp_tools=True) == list(LIVE)


def test_all_mcp_tools_with_declared_tools_still_attaches_every_one(resolve, mcp_on):
    assert resolve(declared=["arxiv/download_paper"], all_mcp_tools=True) == list(LIVE)


def test_a_live_duplicate_attaches_once(resolve, mcp_on):
    live = ("download_paper", "download_paper", "tavily-search")
    assert resolve(declared=["arxiv/download_paper"], live=live) == ["download_paper"]
    assert resolve(all_mcp_tools=True, live=live) == ["download_paper", "tavily-search"]


def test_a_key_matching_no_live_tool_attaches_nothing(resolve, mcp_on):
    assert resolve(declared=["gone/vanished"]) == []


def test_mcp_off_attaches_nothing(resolve):
    assert settings.mcp.enabled is False
    assert resolve(declared=["arxiv/download_paper"]) == []
    assert resolve(all_mcp_tools=True) == []


# ---------------------------------------------------------------------------
# attach_tools on a real agent
# ---------------------------------------------------------------------------
def test_attach_tools_records_the_names(mcp_on):
    agent = BaseAgent()
    agent.config_tool_names = ["fetch"]
    wanted, duplicate, other = FakeTool("fetch"), FakeTool("fetch"), FakeTool("other")

    agent.attach_tools([wanted, duplicate, other])

    assert agent.tools == [wanted]
    assert agent.tools_names == ["fetch"]


def _spec(**overrides) -> AgentSpec:
    return AgentSpec.model_validate(
        {
            "id": "probe",
            "slug": "probe",
            "name": "Probe",
            "version": "1.0.0",
            "type": "deep_agent",
            "prompt": "You are a probe.",
            "model": {"main": "openai:gpt-4o"},
            **overrides,
        }
    )


def test_a_yaml_agent_seeds_its_declared_keys(tmp_path):
    spec = _spec(
        tools=[
            {"server_id": "arxiv", "tool_name": "download_paper"},
            {"native": "render_chart"},
        ]
    )
    agent = YamlDeepAgent(spec, tmp_path, config=run_config())
    # Native refs are resolved at build, never matched against the gateway.
    assert agent.config_tool_names == ["arxiv/download_paper"]
    assert agent.all_mcp_tools is False


def test_a_gateway_tool_named_like_a_builtin_is_dropped(tmp_path, mcp_on):
    agent = YamlDeepAgent(_spec(all_mcp_tools=True), tmp_path, config=run_config())
    shadow, wanted = FakeTool("write_file"), FakeTool("download_paper")

    agent.attach_tools([shadow, wanted])

    assert agent.tools == [wanted]
    assert agent.tools_names == ["download_paper"]


def test_the_reserved_name_check_ignores_case(tmp_path, mcp_on):
    agent = YamlDeepAgent(_spec(all_mcp_tools=True), tmp_path, config=run_config())
    agent.attach_tools([FakeTool("Execute"), FakeTool(" ask_user ")])
    assert agent.tools == []
