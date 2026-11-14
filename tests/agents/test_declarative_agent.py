"""A declarative (YAML) agent end to end: it loads, builds, and gates as declared.

The service ships no agent, so this runs on the test-only definition in
``tests/agents/fixtures/agents/assistant/`` (``AGENTS_DIR`` in conftest). Pinned:

* it is in the registry under its folder name and is the default in the list
  when ``DEFAULT_AGENT_SLUG`` names it;
* it builds offline with async sub-agents off (blocking ``task``) and on
  (``start_async_task`` and the other async task tools instead);
* the approval gates it runs with are those of its ``agent.yaml``: writes and
  delegation unapproved, ``execute`` always approved (locked), whichever
  spelling of the delegation gate the run has.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml
from conftest import run_config
from langgraph.checkpoint.memory import MemorySaver

from core.settings import settings
from harness.abstractions import YamlDeepAgent, deep_agent
from harness.tools.builtins import locked_gates
from harness.tools.gates import resolve_interrupt_on
from utils.agents import AGENT_REGISTRY, list_agent_manifests, resolve_agent_definition

SLUG = "assistant"
SEED_DIR = Path(__file__).resolve().parent / "fixtures" / "agents" / SLUG


def _declared_hitl() -> dict[str, bool]:
    raw = yaml.safe_load((SEED_DIR / "agent.yaml").read_text(encoding="utf-8"))
    return dict(raw["hitl"])


@pytest.fixture
def captured_builds(monkeypatch) -> list[dict[str, Any]]:
    """Every ``create_deep_agent`` call's keyword arguments, the real build still run."""
    calls: list[dict[str, Any]] = []
    real = deep_agent.create_deep_agent

    def spy(**kwargs: Any) -> Any:
        calls.append(kwargs)
        return real(**kwargs)

    monkeypatch.setattr(deep_agent, "create_deep_agent", spy)
    return calls


async def _built(*, async_on: bool) -> YamlDeepAgent:
    settings.async_tasks.enabled = async_on
    definition = resolve_agent_definition(SLUG)
    assert definition is not None
    agent = definition.build(run_config())
    # No durable saver is wired in unit tests.
    agent.checkpointer = MemorySaver()
    await agent.ensure_built()
    return agent


def _tool_names(build: dict[str, Any]) -> set[str]:
    return {getattr(tool, "name", "") for tool in build["tools"]}


def _graph_tool_names(agent: YamlDeepAgent) -> set[str]:
    """What the compiled graph's tool node can run (middleware tools included)."""
    return set(agent.compiled.nodes["tools"].bound.tools_by_name)


ASYNC_TASK_TOOLS = {
    "start_async_task",
    "check_async_task",
    "update_async_task",
    "cancel_async_task",
    "list_async_tasks",
}


def test_the_assistant_is_registered_under_its_folder_name():
    definition = AGENT_REGISTRY.get(SLUG)
    assert definition is not None
    assert definition.slug == definition.spec.slug == SEED_DIR.name
    assert definition.manifest["type"] == "deep agent"
    assert definition.spec.all_mcp_tools is True
    assert [sa.name for sa in definition.spec.subagents] == ["researcher", "writer"]


def test_the_assistant_is_the_default_agent():
    manifests = {m.slug: m for m in list_agent_manifests()}
    assert manifests[SLUG].default is True
    assert [m.slug for m in manifests.values() if m.default] == [SLUG]


def test_its_spec_passes_the_loader_checks():
    spec = AGENT_REGISTRY[SLUG].spec
    errors = spec.reference_errors(
        is_known_model=lambda model_id: ":" in model_id,
        is_known_native_tool=lambda name: True,
    )
    assert errors == []


def test_its_resolved_gates_are_those_of_its_agent_yaml():
    declared = _declared_hitl()
    assert AGENT_REGISTRY[SLUG].spec.hitl == declared

    gates = resolve_interrupt_on(declared)
    assert gates["write_file"] is False
    assert gates["edit_file"] is False
    assert gates["start_async_task"] is False
    # One delegation gate under two names: the blocking spelling follows.
    assert gates["task"] is False
    assert gates["execute"] is True
    assert "execute" in locked_gates()
    # ask_user is itself the pause, so it is never gated.
    assert "ask_user" not in gates


async def test_it_builds_with_blocking_subagents(captured_builds):
    agent = await _built(async_on=False)

    assert agent.compiled is not None
    main = captured_builds[-1]
    assert main["name"] == SLUG
    assert main["interrupt_on"] == resolve_interrupt_on(_declared_hitl())
    assert main["interrupt_on"]["execute"] is True
    sub_names = [spec["name"] for spec in main["subagents"]]
    assert {"researcher", "writer"} <= set(sub_names)
    # No sub-agent, general-purpose included, may ask the user anything.
    for spec in main["subagents"]:
        assert "ask_user" not in {getattr(t, "name", "") for t in spec["tools"]}
    graph_tools = _graph_tool_names(agent)
    assert "task" in graph_tools
    assert not ASYNC_TASK_TOOLS & graph_tools


async def test_it_builds_with_async_subagents(captured_builds):
    agent = await _built(async_on=True)

    assert agent.compiled is not None
    main = captured_builds[-1]
    # The async task tools replace the blocking `task`: no sub-agent specs go
    # to deepagents, and the gates still come from agent.yaml.
    assert main["subagents"] is None
    assert main["interrupt_on"] == resolve_interrupt_on(_declared_hitl())
    assert main["interrupt_on"]["execute"] is True
    assert main["interrupt_on"]["start_async_task"] is False
    graph_tools = _graph_tool_names(agent)
    assert graph_tools >= ASYNC_TASK_TOOLS
    assert "task" not in graph_tools


async def test_the_main_agent_gets_the_native_builtins(captured_builds):
    await _built(async_on=False)

    names = _tool_names(captured_builds[-1])
    assert {"render_chart", "view_image", "present_artifact", "ask_user"} <= names
