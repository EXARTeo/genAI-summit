"""``ask_user``: clarifying questions as a human-in-the-loop pause.

What is pinned here:

* the interrupt value is the contract with the UI (``{"type": "ask_user",
  "questions": [{"id": "q1", ...}]}``) and the resume value comes back as the
  tool's result text, through a real deep agent and checkpointer;
* a sub-agent's call is refused instead of pausing (deepagents hands the
  general-purpose sub-agent the parent's whole tool list), and so is an async
  task's, recognised by the ``async_task_id`` marker in its context;
* the tool exists only for a conversation's own run, is never approval-gated,
  and is never listed for an explicit sub-agent tool subset;
* the resume value is validated (unknown ids, malformed answers).
"""

from __future__ import annotations

from pathlib import Path
from typing import ClassVar

import pytest
from conftest import CLIENT_ID, CONVERSATION_ID, run_config
from deepagents import create_deep_agent
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command
from pydantic import ValidationError

from harness.abstractions.agent_spec import AgentSpec
from harness.abstractions.deep_agent import DeepAgent
from harness.abstractions.yaml_agent import YamlDeepAgent
from harness.tools import builtins as builtins_mod
from harness.tools import registry
from harness.tools.ask_user import schema as ask_schema
from harness.tools.ask_user import tool as ask_user
from harness.tools.gates import resolve_interrupt_on

QUESTIONS = [
    {"question": "Which period?", "options": ["Q3 2025", "Q4 2025"]},
    {"question": "Which regions?", "options": ["North", "South", "East"], "multiple": True},
    {"question": "Anything to leave out?"},
]


class _Scripted(FakeMessagesListChatModel):
    """Replays scripted replies and records what the model was shown."""

    seen: ClassVar[list] = []

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, *args, **kwargs):
        type(self).seen.append(list(messages))
        return super()._generate(messages, *args, **kwargs)


def _call(call_id: str, name: str, args: dict) -> AIMessage:
    return AIMessage(content="", tool_calls=[{"id": call_id, "name": name, "args": args}])


def _agent(responses):
    _Scripted.seen = []
    return create_deep_agent(
        model=_Scripted(responses=responses),
        tools=[ask_user.build_ask_user_tool()],
        checkpointer=MemorySaver(),
    )


async def _run(agent, payload, config):
    async for _ in agent.astream(payload, config, stream_mode=["updates"], subgraphs=True):
        pass
    return await agent.aget_state(config)


def _tool_result(call_id: str) -> str | None:
    for messages in _Scripted.seen:
        for message in messages:
            if message.type == "tool" and message.tool_call_id == call_id:
                return message.content
    return None


# ---------------------------------------------------------------------------
# Through a real deep agent: pause, resume, result
# ---------------------------------------------------------------------------
async def test_the_call_pauses_with_numbered_questions_and_the_answers_come_back():
    agent = _agent(
        [_call("ask-1", "ask_user", {"questions": QUESTIONS}), AIMessage(content="done")]
    )
    config = {"configurable": {"thread_id": "ask-1"}}

    paused = await _run(agent, {"messages": [{"role": "user", "content": "make a report"}]}, config)
    assert len(paused.interrupts) == 1
    assert paused.interrupts[0].value == {
        "type": "ask_user",
        "questions": [
            {
                "id": "q1",
                "question": "Which period?",
                "options": ["Q3 2025", "Q4 2025"],
                "multiple": False,
            },
            {
                "id": "q2",
                "question": "Which regions?",
                "options": ["North", "South", "East"],
                "multiple": True,
            },
            {"id": "q3", "question": "Anything to leave out?", "options": [], "multiple": False},
        ],
    }

    resume = ask_user.resume_value(
        paused.interrupts[0].value,
        decision="approve",
        value={
            "answers": [
                {"id": "q1", "selected": ["Q4 2025"], "text": ""},
                {"id": "q3", "selected": [], "text": "drafts"},
            ]
        },
    )
    finished = await _run(agent, Command(resume=resume), config)

    assert finished.interrupts == ()
    assert _tool_result("ask-1") == (
        "The user answered your questions:\n"
        "1. Which period?\n"
        "   → Q4 2025\n"
        "2. Which regions?\n"
        "   → (no answer)\n"
        "3. Anything to leave out?\n"
        "   → drafts\n"
        "Now do the work with these answers. Do not ask again: state any "
        "assumption you still need to make."
    )
    assert finished.values["messages"][-1].content == "done"


async def test_a_skip_tells_the_model_to_carry_on_with_assumptions():
    agent = _agent(
        [_call("ask-2", "ask_user", {"questions": QUESTIONS[:1]}), AIMessage(content="done")]
    )
    config = {"configurable": {"thread_id": "ask-2"}}
    paused = await _run(agent, {"messages": [{"role": "user", "content": "go"}]}, config)

    resume = ask_user.resume_value(
        paused.interrupts[0].value, decision="reject", value={"answers": "ignored"}
    )
    await _run(agent, Command(resume=resume), config)

    assert _tool_result("ask-2") == ask_user.SKIPPED_REPLY


async def test_a_sub_agent_is_refused_instead_of_pausing_the_run():
    # The general-purpose sub-agent inherits the parent's tools, ask_user among them.
    agent = _agent(
        [
            _call("task-1", "task", {"subagent_type": "general-purpose", "description": "look"}),
            _call("ask-sub", "ask_user", {"questions": QUESTIONS[:1]}),
            AIMessage(content="sub done"),
            AIMessage(content="final"),
        ]
    )
    config = {"configurable": {"thread_id": "ask-sub"}}
    state = await _run(agent, {"messages": [{"role": "user", "content": "go"}]}, config)

    assert state.interrupts == ()
    assert _tool_result("ask-sub") == ask_user.SUBAGENT_REFUSAL
    assert state.values["messages"][-1].content == "final"


# ---------------------------------------------------------------------------
# The pieces
# ---------------------------------------------------------------------------
def test_the_result_joins_choices_and_free_text():
    questions = ask_user.ask_user_payload(QUESTIONS)["questions"]
    reply = {
        "answers": [
            {"id": "q2", "selected": ["North", "East"], "text": "and the islands"},
            {"id": "q1", "selected": [], "text": ""},
        ],
        "skipped": False,
    }
    assert ask_user.format_reply(questions, reply).splitlines() == [
        "The user answered your questions:",
        "1. Which period?",
        "   → (no answer)",
        "2. Which regions?",
        "   → North, East; and the islands",
        "3. Anything to leave out?",
        "   → (no answer)",
        "Now do the work with these answers. Do not ask again: state any "
        "assumption you still need to make.",
    ]


@pytest.mark.parametrize(
    ("namespace", "nested"),
    [
        ("tools:7f1c", False),  # a main-agent tool runs one `tools:` task deep
        ("tools:7f1c|tools:a90e", True),  # a sub-agent's, inside the `task` tool
        ("tools:7f1c|tools:a90e|tools:0b2d", True),  # a nested sub-agent's
        ("", False),
    ],
)
def test_a_sub_agent_is_recognised_from_the_checkpoint_namespace(namespace, nested):
    assert ask_user.in_subagent({"configurable": {"checkpoint_ns": namespace}}) is nested
    assert ask_user.in_subagent({"metadata": {"langgraph_checkpoint_ns": namespace}}) is nested


def test_without_a_namespace_the_call_is_the_main_agents():
    assert ask_user.in_subagent(None) is False
    assert ask_user.in_subagent({}) is False


def test_an_async_task_context_counts_as_a_sub_agent():
    # A background task runs top-level on its own thread, so its namespace
    # looks like a main agent's; the runner's marker is what gives it away.
    top_level = {"configurable": {"checkpoint_ns": "tools:7f1c"}}
    assert ask_user.in_subagent(top_level, context={"async_task_id": "task-1"}) is True
    assert ask_user.in_subagent(top_level, context={"async_task_id": "  "}) is False
    assert ask_user.is_async_task_context({"async_task_id": "task-1"}) is True
    assert ask_user.is_async_task_context({}) is False


async def test_the_tool_refuses_when_invoked_inside_a_sub_agent():
    tool = ask_user.build_ask_user_tool()
    result = await tool.ainvoke(
        {"questions": QUESTIONS[:1]},
        config={"configurable": {"checkpoint_ns": "tools:a|tools:b"}},
    )
    assert result == ask_user.SUBAGENT_REFUSAL


async def test_the_tool_built_for_a_task_run_refuses():
    tool = ask_user.build_ask_user_tool(context={"async_task_id": "task-1"})
    result = await tool.ainvoke({"questions": QUESTIONS[:1]}, config={})
    assert result == ask_user.SUBAGENT_REFUSAL


@pytest.mark.parametrize(
    "args",
    [
        {"questions": []},
        {"questions": [*QUESTIONS, {"question": "A fourth?"}]},
        {"questions": [{"question": "x" * 301}]},
        {"questions": [{"question": "Pick", "options": [str(i) for i in range(7)]}]},
    ],
)
def test_the_schema_bounds_the_questions(args):
    with pytest.raises(ValidationError):
        ask_schema.AskUserInput.model_validate(args)


def test_an_ask_user_interrupt_is_recognised_by_its_type():
    assert ask_user.is_ask_user_interrupt(ask_user.ask_user_payload(QUESTIONS)) is True
    assert ask_user.is_ask_user_interrupt({"action_requests": []}) is False
    assert ask_user.is_ask_user_interrupt(None) is False


# ---------------------------------------------------------------------------
# The resume value
# ---------------------------------------------------------------------------
@pytest.fixture
def panel():
    return ask_user.ask_user_payload(QUESTIONS)


def test_answers_are_kept_as_the_users_strings(panel):
    value = {"answers": [{"id": "q2", "selected": [" North ", "Somewhere new"], "text": " ok "}]}
    assert ask_user.resume_value(panel, decision="approve", value=value) == {
        "answers": [{"id": "q2", "selected": ["North", "Somewhere new"], "text": "ok"}],
        "skipped": False,
    }


def test_missing_fields_read_as_empty(panel):
    value = {"answers": [{"id": "q1"}, {"id": "q3", "selected": None, "text": None}]}
    assert ask_user.resume_value(panel, decision="approve", value=value)["answers"] == [
        {"id": "q1", "selected": [], "text": ""},
        {"id": "q3", "selected": [], "text": ""},
    ]


def test_reject_is_a_skip_whatever_the_value(panel):
    assert ask_user.resume_value(panel, decision="reject", value=None) == {
        "answers": [],
        "skipped": True,
    }


@pytest.mark.parametrize(
    "value",
    [
        None,
        "free text",
        {"answers": "q1"},
        {"answers": ["q1"]},
        {"answers": [{"id": "q9", "selected": []}]},
        {"answers": [{"id": "q1"}, {"id": "q1"}]},
        {"answers": [{"id": "q1", "selected": "Q3 2025"}]},
        {"answers": [{"id": "q1", "selected": [3]}]},
        {"answers": [{"id": "q1", "text": ["x"]}]},
    ],
)
def test_a_malformed_reply_is_refused(panel, value):
    with pytest.raises(ValueError):
        ask_user.resume_value(panel, decision="approve", value=value)


# ---------------------------------------------------------------------------
# Who gets it
# ---------------------------------------------------------------------------
def _ctx(**overrides):
    fields = {"agent_slug": "helper-bot", "conversation_id": CONVERSATION_ID} | overrides
    return registry.NativeToolContext(**fields)


def test_a_conversation_run_gets_it():
    names = [tool.name for tool in registry.build_auto_attach_tools(_ctx())]
    assert "ask_user" in names


def test_a_background_task_run_does_not():
    # A task's run: only the orchestrator may pause on a question.
    assert registry.NATIVE_TOOLS["ask_user"].builder(_ctx(async_task_id="task-1")) is None
    names = [t.name for t in registry.build_auto_attach_tools(_ctx(async_task_id="task-1"))]
    assert "ask_user" not in names


def test_a_run_without_a_conversation_does_not():
    assert registry.NATIVE_TOOLS["ask_user"].builder(_ctx(conversation_id=None)) is None


def test_it_is_a_builtin_that_can_never_be_gated():
    entry = builtins_mod.BUILTIN_BY_NAME["ask_user"]
    assert entry.gateable is False
    assert entry.hitl_default is False
    assert entry.locked is False
    assert "ask_user" in builtins_mod.ungateable_tools()

    # The agent's own gates try to set it, and it does not stick.
    resolved = resolve_interrupt_on({"ask_user": True})
    assert "ask_user" not in resolved
    assert resolved["execute"] is True  # the locked gate is untouched


def test_an_explicit_sub_agent_subset_never_carries_it(tmp_path: Path):
    natives = [{"native": "ask_user"}, {"native": "render_chart"}]
    spec = AgentSpec.model_validate(
        {
            "id": "research-bot",
            "slug": "research-bot",
            "name": "Research Bot",
            "version": "1.0.0",
            "type": "deep_agent",
            "prompt": "You research things.",
            "model": {"main": "openai:gpt-4o"},
            "tools": natives,
            "subagents": [
                {"name": "writer", "description": "Writes", "prompt": "Write.", "tools": natives}
            ],
        }
    )
    agent = YamlDeepAgent(spec, tmp_path, config=run_config())

    subs = {sa["name"]: sa for sa in agent.register_subagents()}
    assert [tool.name for tool in subs["writer"]["tools"]] == ["render_chart"]


# ---------------------------------------------------------------------------
# The deep agent wires the gate from the run context
# ---------------------------------------------------------------------------
class _StubAgent(DeepAgent):
    name = "stub-agent"
    agent_id = "stub-agent"
    label = "Stub"
    version = "1.0.0"

    def register_agent(self):  # pragma: no cover - never built here
        raise NotImplementedError


@pytest.mark.parametrize(("async_task_id", "expected"), [(None, True), ("task-1", False)])
def test_the_deep_agent_attaches_and_describes_it_from_the_task_marker(async_task_id, expected):
    config = run_config()
    if async_task_id is not None:
        config["context"]["async_task_id"] = async_task_id
    agent = _StubAgent(config=config)

    assert agent.client_id == CLIENT_ID
    assert ("ask_user" in [tool.name for tool in agent._builtin_tools()]) is expected
    assert agent.prompt_context().has_ask_user is expected
