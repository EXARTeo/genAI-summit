"""The native-tool registry: which of the service's own tools a run gets.

Native tools ship in the image and are built per run from a
``NativeToolContext``. Each builder is also its tool's gate: it returns
``None`` when the run lacks what the tool needs, so a tool is never handed to a
model that would fail on its first call. Pinned here:

* the roster and its order (the order auto-attach tools reach the agent);
* each tool's gate (``render_chart`` and ``ask_user`` need a conversation,
  ``view_image`` the files, ``present_artifact`` files and a presentation sink,
  and a background task's run never gets ``ask_user``);
* the registry fails closed on a duplicate name;
* a deep agent attaches them only for a run with a client.
"""

from __future__ import annotations

import pytest
from conftest import run_config

from harness.abstractions.deep_agent import DeepAgent
from harness.conversation_files import ConversationFiles
from harness.tools import registry
from harness.tools.present_artifact import PresentedFiles


class Bare(DeepAgent):
    """A deep agent with nothing of its own: only the platform's tools."""

    name = "tool-roster"

    def register_agent(self):  # pragma: no cover - never built here
        raise NotImplementedError


def _names(tools) -> list[str]:
    return [t.name for t in tools]


@pytest.fixture
def full_context(conversation_files: ConversationFiles) -> registry.NativeToolContext:
    return registry.NativeToolContext(
        agent_slug="assistant",
        conversation_id="c1",
        files=conversation_files,
        presented=PresentedFiles(),
    )


def test_the_roster_is_the_four_native_tools_in_order():
    assert list(registry.NATIVE_TOOLS) == [
        "render_chart",
        "view_image",
        "present_artifact",
        "ask_user",
    ]
    assert all(defn.auto_attach for defn in registry.NATIVE_TOOLS.values())


def test_known_names_are_recognised_for_spec_validation():
    assert registry.is_known_native_tool("render_chart")
    assert not registry.is_known_native_tool("not_a_tool")


def test_a_full_run_context_attaches_every_native_tool(full_context):
    assert _names(registry.build_auto_attach_tools(full_context)) == [
        "render_chart",
        "view_image",
        "present_artifact",
        "ask_user",
    ]


def test_without_a_conversation_nothing_is_attached():
    ctx = registry.NativeToolContext(agent_slug="assistant", conversation_id=None)
    assert registry.build_auto_attach_tools(ctx) == []


def test_a_conversation_without_files_gets_only_chart_and_ask_user():
    ctx = registry.NativeToolContext(agent_slug="assistant", conversation_id="c1")
    assert _names(registry.build_auto_attach_tools(ctx)) == ["render_chart", "ask_user"]


def test_present_artifact_needs_a_presentation_sink(conversation_files):
    ctx = registry.NativeToolContext(
        agent_slug="assistant", conversation_id="c1", files=conversation_files
    )
    assert "present_artifact" not in _names(registry.build_auto_attach_tools(ctx))
    assert registry.resolve_native_tool("present_artifact", ctx) is None


def test_a_background_task_never_gets_ask_user(conversation_files):
    # Nobody is watching a task's run: only the orchestrator may pause on a question.
    ctx = registry.NativeToolContext(
        agent_slug="assistant",
        conversation_id="c1",
        files=conversation_files,
        presented=PresentedFiles(),
        async_task_id="task-1",
    )
    assert "ask_user" not in _names(registry.build_auto_attach_tools(ctx))


def test_resolving_an_unknown_name_yields_nothing(full_context):
    assert registry.resolve_native_tool("not_a_tool", full_context) is None
    assert registry.resolve_native_tool("view_image", full_context).name == "view_image"


def test_a_duplicate_registration_is_refused():
    defn = registry.NativeToolDef(name="render_chart", builder=lambda ctx: None)
    with pytest.raises(ValueError, match="already registered"):
        registry.register_native_tool(defn)


def test_a_deep_agent_without_a_client_attaches_no_native_tool():
    # A registry warmup builds agents with no run context: nothing is bound.
    assert Bare()._builtin_tools() == []


def test_a_deep_agent_run_attaches_every_native_tool():
    assert _names(Bare(config=run_config())._builtin_tools()) == [
        "render_chart",
        "view_image",
        "present_artifact",
        "ask_user",
    ]


def test_a_deep_agent_task_run_has_no_ask_user():
    config = run_config()
    config["context"]["async_task_id"] = "task-1"
    agent = Bare(config=config)
    assert agent.async_task_id == "task-1"
    assert "ask_user" not in _names(agent._builtin_tools())
