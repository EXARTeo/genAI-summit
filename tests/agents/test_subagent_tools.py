"""Sub-agents carry their own model and a tool subset, and never exceed the parent.

Three properties are worth pinning:

* **An empty tool list means "inherit".** The ``tools`` key is left off the
  ``SubAgent`` so deepagents hands the sub-agent the parent's full tool list; a
  sub-agent that named no tools must not end up with none.
* **A non-empty list is a restriction, resolved from the parent's filtered
  tools.** A tool the gateway does not serve this run is absent for the
  sub-agent too, and a restriction whose tools are all unavailable stays empty
  instead of widening back to "inherit everything".
* **The spec refuses a sub-agent tool the agent does not declare**, so delegating
  can never be a way to reach a tool the agent itself was not given, unless the
  agent takes every gateway tool (``all_mcp_tools``), and then only MCP tools.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from conftest import run_config
from pydantic import ValidationError

from harness.abstractions import yaml_agent as yaml_module
from harness.abstractions.agent_spec import AgentSpec


def _spec(*, tools=(), subagents=(), all_mcp_tools=False) -> AgentSpec:
    return AgentSpec.model_validate(
        {
            "id": "research-bot-v1",
            "slug": "research-bot",
            "name": "Research Bot",
            "version": "1.0.0",
            "type": "deep_agent",
            "prompt": "You research things.",
            "model": {"main": "openai:gpt-4o"},
            "tools": list(tools),
            "all_mcp_tools": all_mcp_tools,
            "subagents": list(subagents),
        }
    )


def _mcp(server: str, tool: str) -> dict:
    return {"server_id": server, "tool_name": tool}


class FakeTool:
    def __init__(self, name: str):
        self.name = name


KEYS = {"search": "tavily/search", "papers": "arxiv/search_papers", "sql": "rag/sql_query"}


@pytest.fixture
def build(monkeypatch, tmp_path: Path):
    """Run the real ``register_subagents`` over an agent whose parent tools are given.

    ``parent`` is the parent's MCP tools *after* the run's filtering, i.e. what
    ``attach_tools`` left in ``self.tools``.
    """
    monkeypatch.setattr(yaml_module, "get_tool_cache_key", lambda tool: KEYS[tool.name])

    def _build(*, tools, subagents, parent=("search", "papers", "sql"), config=None):
        agent = yaml_module.YamlDeepAgent(
            _spec(tools=tools, subagents=subagents), tmp_path, config=config
        )
        agent.tools = [FakeTool(n) for n in parent]
        return {sa["name"]: sa for sa in agent.register_subagents()}

    return _build


DECLARED = [_mcp("tavily", "search"), _mcp("arxiv", "search_papers"), _mcp("rag", "sql_query")]


def _researcher(*refs: dict) -> dict:
    return {
        "name": "researcher",
        "description": "Finds sources",
        "prompt": "Research.",
        "tools": list(refs),
    }


# ---------------------------------------------------------------------------
# Runtime
# ---------------------------------------------------------------------------
def test_a_subagent_naming_no_tools_inherits_the_parents(build):
    subs = build(
        tools=DECLARED,
        subagents=[{"name": "writer", "description": "Writes", "prompt": "Write."}],
    )
    # No `tools` key at all: deepagents then passes the parent's tool list down.
    assert "tools" not in subs["writer"]


def test_an_explicit_subset_gets_exactly_those_tools(build):
    subs = build(tools=DECLARED, subagents=[_researcher(_mcp("arxiv", "search_papers"))])
    assert [t.name for t in subs["researcher"]["tools"]] == ["papers"]


def test_a_tool_missing_from_the_run_is_absent_for_the_subagent_too(build):
    # The gateway does not serve arXiv this run, so the parent's filtered tools
    # no longer carry it, and the sub-agent must not get it back.
    subs = build(
        tools=DECLARED,
        parent=("search", "sql"),
        subagents=[_researcher(_mcp("arxiv", "search_papers"), _mcp("tavily", "search"))],
    )
    assert [t.name for t in subs["researcher"]["tools"]] == ["search"]


def test_a_restriction_with_nothing_available_stays_empty_rather_than_inheriting(build):
    subs = build(tools=DECLARED, parent=(), subagents=[_researcher(_mcp("arxiv", "search_papers"))])
    assert subs["researcher"]["tools"] == []


def test_a_subagent_model_overrides_the_main_one_and_falls_back_to_it(build):
    subs = build(
        tools=DECLARED,
        subagents=[
            {
                "name": "fast",
                "description": "Quick",
                "prompt": "Go.",
                "model": "openai:gpt-4o-mini",
            },
            {"name": "default", "description": "Same", "prompt": "Go."},
        ],
    )
    assert subs["fast"]["model"] == "openai:gpt-4o-mini"
    assert subs["default"]["model"] == "openai:gpt-4o"


def test_gates_are_never_set_per_subagent(build):
    # Leaving `interrupt_on` off is what makes a sub-agent inherit the parent's
    # resolved approval gates; setting it here would let a tool skip its gate.
    subs = build(tools=DECLARED, subagents=[_researcher(_mcp("tavily", "search"))])
    assert "interrupt_on" not in subs["researcher"]


def test_native_tools_need_a_client_to_be_built(build):
    # Without a run context (a registry warmup) no native tool is bound.
    subs = build(
        tools=[{"native": "render_chart"}],
        subagents=[_researcher({"native": "render_chart"})],
    )
    assert subs["researcher"]["tools"] == []


def test_a_listed_native_tool_is_bound_for_a_run(build):
    subs = build(
        tools=[{"native": "render_chart"}],
        subagents=[_researcher({"native": "render_chart"})],
        config=run_config(),
    )
    assert [t.name for t in subs["researcher"]["tools"]] == ["render_chart"]


def test_ask_user_is_never_given_to_a_subagent_even_when_listed(build):
    subs = build(
        tools=[{"native": "ask_user"}, {"native": "render_chart"}],
        subagents=[_researcher({"native": "ask_user"}, {"native": "render_chart"})],
        config=run_config(),
    )
    assert [t.name for t in subs["researcher"]["tools"]] == ["render_chart"]


# ---------------------------------------------------------------------------
# Spec validation
# ---------------------------------------------------------------------------
def test_the_spec_accepts_a_subset_and_an_empty_list():
    spec = _spec(
        tools=DECLARED,
        subagents=[
            {"name": "a", "description": "A", "prompt": "A.", "tools": [_mcp("tavily", "search")]},
            {"name": "b", "description": "B", "prompt": "B."},
        ],
    )
    assert [len(sa.tools) for sa in spec.subagents] == [1, 0]


def test_the_spec_refuses_a_subagent_tool_the_agent_does_not_declare():
    with pytest.raises(ValidationError, match="does not declare: github/create_issue"):
        _spec(
            tools=[_mcp("tavily", "search")],
            subagents=[
                {
                    "name": "a",
                    "description": "A",
                    "prompt": "A.",
                    "tools": [_mcp("github", "create_issue")],
                }
            ],
        )


def test_the_rule_covers_native_tools_as_well():
    with pytest.raises(ValidationError, match="does not declare: render_chart"):
        _spec(
            tools=[],
            subagents=[
                {
                    "name": "a",
                    "description": "A",
                    "prompt": "A.",
                    "tools": [{"native": "render_chart"}],
                }
            ],
        )


def test_all_mcp_tools_lets_a_subagent_list_any_mcp_tool():
    spec = _spec(
        all_mcp_tools=True,
        subagents=[
            {
                "name": "a",
                "description": "A",
                "prompt": "A.",
                "tools": [_mcp("github", "create_issue")],
            }
        ],
    )
    assert spec.subagents[0].tools[0].key() == "github::create_issue"


def test_all_mcp_tools_does_not_open_native_tools():
    # Every gateway tool is the agent's to hand down; a native tool still has
    # to be declared by the agent first.
    with pytest.raises(ValidationError, match="does not declare: render_chart"):
        _spec(
            all_mcp_tools=True,
            subagents=[
                {
                    "name": "a",
                    "description": "A",
                    "prompt": "A.",
                    "tools": [{"native": "render_chart"}],
                }
            ],
        )
