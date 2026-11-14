"""Composing a deep agent's system prompt.

The rule every case here defends: **a section may only describe something the
run actually has.** An agent told about a mount it lacks tries it, fails, and
then distrusts the rest of its prompt. The flags that build the mounts are the
flags that build the text.

The second rule is that the agent's own instructions lead and are never
rewritten: a thin prompt with every mount and file tool, told about none of
them, spends turns insisting it cannot browse a filesystem.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from conftest import run_config

from core.settings import settings
from harness import prompt_engineering as pe
from harness.abstractions.deep_agent import DeepAgent
from harness.prompt_engineering.prompts.capabilities_prompt import (
    DELEGATING_ASYNC_SUBAGENT_PROMPT,
    DELEGATING_SUBAGENT_PROMPT,
    delegating_subagent_prompt,
)


@pytest.fixture
def full() -> pe.PromptContext:
    """A run with everything switched on."""
    return pe.PromptContext(
        has_conversation=True,
        has_reference=True,
        sandbox_enabled=True,
        has_subagents=True,
        has_ask_user=True,
        async_subagents=True,
        narrate_progress=True,
        now=datetime(2026, 9, 15, 17, 23, tzinfo=UTC),
    )


# ---------------------------------------------------------------------------
# The agent's instructions lead
# ---------------------------------------------------------------------------
def test_the_instructions_come_first_and_are_untouched(full):
    instructions = "You are a good friend that helps me with whatever I want"
    out = pe.compose_system_prompt(instructions, full)

    assert out.startswith(instructions)


def test_an_empty_run_composes_to_exactly_the_instructions():
    # Nothing enabled: the prompt is byte-identical to what was authored.
    assert pe.compose_system_prompt("Be helpful.", pe.PromptContext()) == "Be helpful."


def test_no_instructions_yields_the_platform_sections_alone(full):
    out = pe.compose_system_prompt(None, full)
    assert out.startswith("## Your Workspace")


def test_surrounding_whitespace_in_instructions_is_trimmed():
    assert pe.compose_system_prompt("  Be helpful.\n\n", pe.PromptContext()) == "Be helpful."


# ---------------------------------------------------------------------------
# A section appears only when its feature does
# ---------------------------------------------------------------------------
def test_the_workspace_is_described_only_with_a_conversation():
    with_conv = pe.compose_system_prompt("x", pe.PromptContext(has_conversation=True))
    without = pe.compose_system_prompt("x", pe.PromptContext())

    assert "/conversation/input/" in with_conv
    assert "/conversation/" not in without


def test_reference_is_described_only_when_mounted():
    # A code-defined agent has no definition folder; its package is source and
    # is never mounted, so the section must not appear.
    with_ref = pe.compose_system_prompt(
        "x", pe.PromptContext(has_conversation=True, has_reference=True)
    )
    without = pe.compose_system_prompt("x", pe.PromptContext(has_conversation=True))

    assert "/reference/" in with_ref
    assert "/reference/" not in without


def test_reference_alone_still_gets_a_workspace_section_without_the_conversation_outro():
    out = pe.compose_system_prompt("x", pe.PromptContext(has_reference=True))
    assert "/reference/" in out
    assert "/conversation/" not in out


def test_execute_is_described_only_when_the_sandbox_is_on():
    on = pe.compose_system_prompt(
        "x", pe.PromptContext(has_conversation=True, sandbox_enabled=True)
    )
    off = pe.compose_system_prompt("x", pe.PromptContext(has_conversation=True))

    assert "`execute`" in on
    assert "`execute`" not in off


def test_the_orchestrator_rule_appears_only_for_a_delegating_agent():
    # The rule is platform-wide (the normalizer drops a sub-agent's call for
    # every deep agent), but an agent with no sub-agents cannot be in that
    # situation, so telling it describes a state it cannot reach.
    with_subs = pe.compose_system_prompt(
        "x", pe.PromptContext(has_conversation=True, has_subagents=True)
    )
    without = pe.compose_system_prompt("x", pe.PromptContext(has_conversation=True))

    # The workspace section names sub-agents for every run (they share the
    # files); the orchestrator rule is the one that leads with it.
    rule = "When a **sub-agent** produces a document, you present it."
    assert rule in with_subs
    assert rule not in without


def test_background_delegation_is_described_only_with_async_sub_agents():
    blocking = pe.compose_system_prompt(
        "x", pe.PromptContext(has_conversation=True, has_subagents=True)
    )
    background = pe.compose_system_prompt(
        "x", pe.PromptContext(has_conversation=True, has_subagents=True, async_subagents=True)
    )
    # Without sub-agents the async flag alone describes nothing.
    no_subs = pe.compose_system_prompt(
        "x", pe.PromptContext(has_conversation=True, async_subagents=True)
    )

    assert "`start_async_task`" in background
    assert "`start_async_task`" not in blocking
    assert "start_async_task" not in no_subs


def test_the_ask_user_rule_appears_only_when_the_tool_is_attached():
    # A background task's run has no `ask_user`; telling it to ask would have
    # it end the run with questions nobody reads.
    with_tool = pe.compose_system_prompt(
        "x", pe.PromptContext(has_conversation=True, has_ask_user=True)
    )
    without = pe.compose_system_prompt("x", pe.PromptContext(has_conversation=True))

    assert "`ask_user`" in with_tool
    assert "Other" in with_tool  # never an "Other" option: the user can always write their own
    assert "ask_user" not in without


def test_the_platform_verbs_need_a_conversation():
    # All three point into the conversation mounts and are not attached without
    # one, so describing them would be describing tools the run does not have.
    with_conv = pe.compose_system_prompt("x", pe.PromptContext(has_conversation=True))
    without = pe.compose_system_prompt("x", pe.PromptContext())

    for verb in ("view_image", "present_artifact", "render_chart"):
        assert verb in with_conv
        assert verb not in without


# ---------------------------------------------------------------------------
# Order
# ---------------------------------------------------------------------------
def test_the_sections_are_ordered_stable_first_volatile_last(full):
    # The clock changes every minute; everything above it is fixed for the run.
    # Putting it earlier would invalidate the provider's prompt-prefix cache on
    # every request.
    assert pe.describe_sections(full) == [
        "filesystem",
        "capabilities",
        "efficiency",
        "progress",
        "temporal",
    ]

    out = pe.compose_system_prompt("x", full)
    assert out.index("## Your Workspace") < out.index("## What You Can Do Beyond Text")
    assert out.index("## Work Efficiently With Files") < out.index("## Right Now")


def test_an_inactive_section_is_absent_from_the_description():
    assert pe.describe_sections(pe.PromptContext()) == []


def test_platform_sections_pair_each_name_with_its_text(full):
    sections = pe.platform_sections(full)
    assert [name for name, _ in sections] == pe.describe_sections(full)
    assert all(text for _, text in sections)


# ---------------------------------------------------------------------------
# Working out loud
# ---------------------------------------------------------------------------
def test_the_agent_the_user_talks_to_narrates_between_tool_calls(full):
    out = pe.compose_system_prompt("x", full)
    assert "## Keep the User in the Loop While You Work" in out
    assert "Before you delegate" in out
    # Stable: it sits in the cached prefix, above the clock.
    assert out.index("## Keep the User in the Loop While You Work") < out.index("## Right Now")


def test_a_run_without_narration_gets_no_progress_section():
    out = pe.compose_system_prompt("x", pe.PromptContext(has_conversation=True))
    assert "Keep the User in the Loop" not in out


def test_file_work_is_write_then_measure_then_edit_and_a_target_is_approximate():
    on = pe.compose_system_prompt(
        "x", pe.PromptContext(has_conversation=True, sandbox_enabled=True)
    )
    assert "## Work Efficiently With Files" in on
    assert "Never build\n  a file's content inside a shell command" in on
    assert "within about 10%" in on
    assert "`wc -w" in on
    no_sandbox = pe.compose_system_prompt("x", pe.PromptContext(has_conversation=True))
    assert "## Work Efficiently With Files" in no_sandbox
    assert "`execute`" not in no_sandbox


def test_a_path_is_not_a_file_the_user_can_open():
    out = pe.compose_system_prompt("x", pe.PromptContext(has_conversation=True, has_subagents=True))
    assert "never answer with a path alone" in out
    assert (
        "in the same turn you report\n  that result, review the file and call `present_artifact`"
        in out
    )


def test_a_background_task_prompt_gets_only_its_own_sections():
    # A task (``narrate_as_subagent``) gets its instructions, then how to work
    # with the shared files and how to narrate for its panel: not the main
    # agent's workspace or platform verbs.
    task = pe.PromptContext(
        has_conversation=True,
        narrate_progress=True,
        narrate_as_subagent=True,
        sandbox_enabled=True,
    )
    out = pe.compose_task_prompt("You write briefs.", task)
    assert out.startswith("You write briefs.\n\n## Work Efficiently With Files")
    assert "## Narrate Your Work as You Go" in out
    for absent in (
        "## Your Workspace",
        "## What You Can Do Beyond Text",
        "Keep the User in the Loop",
        "## Right Now",
    ):
        assert absent not in out
    assert [name for name, _ in pe.task_sections(task)] == ["efficiency", "progress"]


def test_a_task_prompt_without_instructions_is_its_sections_alone():
    task = pe.PromptContext(has_conversation=True)
    assert pe.compose_task_prompt(None, task).startswith("## Work Efficiently With Files")


def test_a_background_task_narrates_for_its_panel_and_returns_a_standalone_result():
    out = pe.compose_system_prompt(
        "x",
        pe.PromptContext(has_conversation=True, narrate_progress=True, narrate_as_subagent=True),
    )
    assert "## Narrate Your Work as You Go" in out
    assert "Keep the User in the Loop" not in out
    assert "**Your final message is your result**" in out
    assert "Before you delegate" in out


# ---------------------------------------------------------------------------
# A delegating sub-agent's own section
# ---------------------------------------------------------------------------
def test_a_delegating_sub_agent_gets_the_wording_of_its_delegation_kind():
    assert delegating_subagent_prompt("You check facts.") == (
        f"You check facts.\n\n{DELEGATING_SUBAGENT_PROMPT}"
    )
    assert delegating_subagent_prompt("You check facts.", async_subagents=True).endswith(
        DELEGATING_ASYNC_SUBAGENT_PROMPT
    )
    assert delegating_subagent_prompt(None) == DELEGATING_SUBAGENT_PROMPT
    assert "`task`" in DELEGATING_SUBAGENT_PROMPT
    assert "`start_async_task`" in DELEGATING_ASYNC_SUBAGENT_PROMPT


# ---------------------------------------------------------------------------
# What a deep agent tells the composer
# ---------------------------------------------------------------------------
class _Probe(DeepAgent):
    name = "probe-agent"
    agent_id = "probe-agent"
    label = "Probe"
    version = "1.0.0"

    def register_agent(self):  # pragma: no cover - never built here
        raise NotImplementedError


def test_every_conversation_run_narrates_and_a_task_narrates_as_a_sub_agent():
    main = _Probe(config=run_config()).prompt_context()
    task_config = run_config()
    task_config["context"]["async_task_id"] = "task-1"
    task = _Probe(config=task_config).prompt_context()

    assert (main.narrate_progress, main.narrate_as_subagent) == (True, False)
    assert (task.narrate_progress, task.narrate_as_subagent) == (True, True)
    assert _Probe().prompt_context().narrate_progress is False


def test_the_prompt_context_mirrors_the_build_flags(monkeypatch):
    agent = _Probe(config=run_config())
    # `execute` exists only with the switch on and a runner configured.
    monkeypatch.setattr(settings.filesystem, "sandbox_execution_enabled", True)
    monkeypatch.setattr(settings.filesystem, "sandbox_runner_url", "http://sandbox-runner:8080")
    ctx = agent.prompt_context(has_subagents=True, async_subagents=True)

    assert ctx.has_conversation is True
    assert ctx.has_subagents is True
    assert ctx.async_subagents is True
    # A code agent mounts no /reference/.
    assert ctx.has_reference is False
    assert ctx.sandbox_enabled is True
    assert ctx.now is not None
    assert ctx.now.tzinfo is not None


# ---------------------------------------------------------------------------
# The clock
# ---------------------------------------------------------------------------
def test_the_current_date_is_stated(full):
    out = pe.compose_system_prompt("x", full)
    assert "15 September 2026, 17:23 UTC" in out


def test_a_naive_datetime_is_read_as_utc():
    out = pe.compose_system_prompt("x", pe.PromptContext(now=datetime(2026, 9, 15, 17, 23)))
    assert "17:23 UTC" in out


def test_a_run_without_a_clock_says_nothing_about_time():
    assert "## Right Now" not in pe.compose_system_prompt("x", pe.PromptContext())


def test_the_stamp_has_no_seconds():
    # Seconds would change the prompt on every call for no gain, defeating the
    # prefix cache the ordering above exists to protect.
    out = pe.compose_system_prompt(
        "x", pe.PromptContext(now=datetime(2026, 9, 15, 17, 23, 45, tzinfo=UTC))
    )
    assert "17:23 UTC" in out
    assert "17:23:45" not in out
