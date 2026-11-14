"""Approval gates reaching ``interrupt_on``.

Three layers feed it, lowest priority first::

    builtin_hitl_defaults()  <-  the agent's own gates (aliased)  <-  locked_gates()

The agent's layer is a **map**, not a set: a prebuilt tool can default to gated,
so ``False`` has to mean "clear that default" and not merely "no opinion".
``locked_gates()`` is applied last so nothing beneath it can clear a mandated
gate, and ``execute`` is forced once more by name. ``ask_user`` (itself the
pause for the user) can never be gated.

``task`` and ``start_async_task`` are one delegation gate under two names: a run
has only one of the two tools, so whichever spelling a definition uses must
gate whichever tool the run has.

The merge is pinned twice: on ``resolve_interrupt_on`` directly, and through
the real ``build_deep_agent`` (asserting on a re-implementation would pass while
the runtime disarmed every gate).
"""

from __future__ import annotations

from typing import Any

import pytest

from core.settings import settings
from harness.abstractions import deep_agent as deep_agent_module
from harness.prompt_engineering import PromptContext
from harness.tools import builtins, gates


class FakeTool:
    """A live MCP tool: only its name matters to the gates."""

    def __init__(self, name: str):
        self.name = name


# ---------------------------------------------------------------------------
# The roster
# ---------------------------------------------------------------------------
def test_the_baseline_gates_the_write_tools_delegation_and_execute():
    assert builtins.builtin_hitl_defaults() == {
        "write_file": True,
        "edit_file": True,
        "execute": True,
        "task": True,
        "start_async_task": True,
        "forget": True,
        "propose_system_note": True,
        "start_audit": True,
    }


def test_only_execute_is_locked_and_only_ask_user_is_ungateable():
    assert builtins.locked_gates() == {"execute": True}
    assert builtins.ungateable_tools() == frozenset({"ask_user"})


def test_the_roster_names_every_native_tool():
    names = {tool.name for tool in builtins.BUILTIN_TOOLS}
    assert {"render_chart", "view_image", "present_artifact", "ask_user"} <= names
    assert len(names) == len(builtins.BUILTIN_TOOLS)  # no duplicates
    assert builtins.BUILTIN_BY_NAME["execute"].locked is True


# ---------------------------------------------------------------------------
# Aliases
# ---------------------------------------------------------------------------
def test_an_alias_copies_its_value_onto_the_other_name():
    assert gates.with_gate_aliases({"task": False}) == {"task": False, "start_async_task": False}
    assert gates.with_gate_aliases({"start_async_task": True}) == {
        "start_async_task": True,
        "task": True,
    }


def test_a_gate_stated_under_both_names_keeps_each_value():
    stated = {"task": True, "start_async_task": False}
    assert gates.with_gate_aliases(stated) == stated


def test_no_gates_alias_to_nothing():
    assert gates.with_gate_aliases(None) == {}
    assert gates.with_gate_aliases({"search": True}) == {"search": True}


# ---------------------------------------------------------------------------
# The merge
# ---------------------------------------------------------------------------
def test_no_own_gates_is_the_baseline():
    assert gates.resolve_interrupt_on(None) == builtins.builtin_hitl_defaults()
    assert gates.resolve_interrupt_on({}) == builtins.builtin_hitl_defaults()


def test_an_agent_can_add_a_gate_and_clear_a_default():
    resolved = gates.resolve_interrupt_on({"search": True, "write_file": False})
    assert resolved["search"] is True
    assert resolved["write_file"] is False
    assert resolved["edit_file"] is True  # an untouched default survives


def test_clearing_task_clears_the_async_spelling_too():
    resolved = gates.resolve_interrupt_on({"task": False})
    assert resolved["task"] is False
    assert resolved["start_async_task"] is False


def test_clearing_start_async_task_clears_the_blocking_spelling_too():
    resolved = gates.resolve_interrupt_on({"start_async_task": False})
    assert resolved["start_async_task"] is False
    assert resolved["task"] is False


def test_a_locked_gate_cannot_be_cleared():
    assert gates.resolve_interrupt_on({"execute": False})["execute"] is True


def test_execute_is_forced_even_when_the_locked_set_forgets_it(monkeypatch):
    # The by-name force is the belt to the locked set's braces: a roster edit
    # that drops `locked=True` must still never run code unapproved.
    monkeypatch.setattr(gates, "locked_gates", dict)
    assert gates.resolve_interrupt_on({"execute": False})["execute"] is True


def test_ask_user_can_never_be_gated():
    # The call is itself the pause for the user: a gate in front of it would
    # ask for approval to ask.
    resolved = gates.resolve_interrupt_on({"ask_user": True})
    assert "ask_user" not in resolved
    assert resolved["execute"] is True  # the strip touches nothing else


# ---------------------------------------------------------------------------
# Reserved names
# ---------------------------------------------------------------------------
def test_a_gateway_tool_cannot_shadow_a_prebuilt_one():
    tools = [
        FakeTool("write_file"),
        FakeTool("search"),
        FakeTool(" Execute "),
        FakeTool("ASK_USER"),
    ]
    kept = gates.strip_reserved_names(tools, agent_slug="stub")
    assert [t.name for t in kept] == ["search"]


def test_a_tool_without_a_name_is_kept_rather_than_raising():
    # A malformed tool object must not raise inside the build, which would fail
    # the run outright; it cannot shadow anything either.
    tool = FakeTool("")
    assert gates.strip_reserved_names([tool], agent_slug="stub") == [tool]


# ---------------------------------------------------------------------------
# The full merge, through the real build_deep_agent
# ---------------------------------------------------------------------------
@pytest.fixture
def built(monkeypatch):
    """Run the real ``build_deep_agent`` and return the ``interrupt_on`` it built.

    The workspace, filesystem and model plumbing are stubbed; the gate
    resolution is the real code path.
    """
    captured: dict[str, Any] = {}

    def fake_create(**kwargs):
        captured.update(kwargs)
        return object()

    settings.async_tasks.enabled = False
    monkeypatch.setattr(deep_agent_module, "create_deep_agent", fake_create)
    monkeypatch.setattr(deep_agent_module, "exclude_stock_summarization", lambda _m: None)
    monkeypatch.setattr(deep_agent_module, "workspace_write_deny", lambda **_k: [])
    monkeypatch.setattr(
        deep_agent_module, "ensure_planning_and_filesystem", lambda stack, *_a: list(stack)
    )

    def _build(*, class_gates=None, interrupt_on=None, tool_names=()):
        class Agent(deep_agent_module.DeepAgent):
            name = "stub-agent"
            hitl_gates = class_gates or {}

            def register_agent(self):  # pragma: no cover - never built here
                raise NotImplementedError

        agent = Agent()
        agent._apply_live_tools([FakeTool(n) for n in tool_names])
        monkeypatch.setattr(Agent, "_build_composite_backend", lambda self: object())
        monkeypatch.setattr(Agent, "default_middleware", lambda self, m, b: [])
        monkeypatch.setattr(Agent, "_builtin_tools", lambda self: [])
        # An empty context composes to no platform sections.
        monkeypatch.setattr(Agent, "prompt_context", lambda self, **_k: PromptContext())
        agent.build_deep_agent(model="stub-model", interrupt_on=interrupt_on)
        return captured

    return _build


def test_a_locked_gate_survives_an_attempt_to_clear_it(built):
    assert built()["interrupt_on"]["execute"] is True
    assert built(class_gates={"execute": False})["interrupt_on"]["execute"] is True
    assert built(interrupt_on={"execute": False})["interrupt_on"]["execute"] is True


def test_the_class_attribute_gates_when_no_argument_is_passed(built):
    # Dropping `interrupt_on=` from a register_agent() must not disarm.
    assert built(class_gates={"search": True})["interrupt_on"]["search"] is True


def test_an_explicit_map_wins_over_the_class_attribute(built):
    gated = built(class_gates={"search": True}, interrupt_on={"lookup": True})["interrupt_on"]
    assert "search" not in gated
    assert gated["lookup"] is True


def test_an_explicit_empty_map_does_not_fall_back_to_the_class_attribute(built):
    # `is not None`, not truthiness: a spec declaring no gates passes {}.
    gated = built(class_gates={"search": True}, interrupt_on={})["interrupt_on"]
    assert "search" not in gated
    assert gated == builtins.builtin_hitl_defaults()


def test_a_cleared_default_reaches_the_build(built):
    gated = built(interrupt_on={"write_file": False, "task": False})["interrupt_on"]
    assert gated["write_file"] is False
    assert gated["start_async_task"] is False


def test_ask_user_is_stripped_from_every_layer(built):
    assert "ask_user" not in built(class_gates={"ask_user": True})["interrupt_on"]
    assert "ask_user" not in built(interrupt_on={"ask_user": True})["interrupt_on"]


def test_a_gateway_tool_named_like_a_builtin_never_reaches_the_agent(built):
    captured = built(tool_names=("write_file", "search"))
    assert [t.name for t in captured["tools"]] == ["search"]


def test_a_subagent_gate_layer_adds_but_never_clears_a_locked_gate():
    gated = deep_agent_module.DeepAgent._subagent_gates(
        {"lookup": True, "execute": False, "ask_user": True}, {"search": True}
    )
    assert gated["lookup"] is True
    assert gated["search"] is True
    assert gated["execute"] is True
    assert "ask_user" not in gated


def test_a_subagent_spec_overrides_the_agents_own_gate():
    gated = deep_agent_module.DeepAgent._subagent_gates({"search": False}, {"search": True})
    assert gated["search"] is False
    assert deep_agent_module.DeepAgent._subagent_gates(None, None) == (
        builtins.builtin_hitl_defaults()
    )
