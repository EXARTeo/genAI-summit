"""A nested example agent, end to end through the real build and stream path.

The agent is a YAML definition written into a temporary folder (test-only):
main -> researcher -> fact-checker. It is built by ``YamlDeepAgent`` ->
``build_deep_agent`` and streamed through ``BaseAgent.astream`` and the AG-UI
normalizer, with one scripted model standing in for every level (no network).
Each approval resumes through a FRESH agent instance seeded the way the
``/resume`` route seeds it, so this is the run the chat would see:

* the ``task`` gate (a builtin default) pauses the main agent's delegation AND
  the researcher's own: the run's gates apply one level down;
* every level's model calls report their token usage;
* the fact-checker cannot call ``ask_user``: the tool is not in its tool set;
* each sub-agent's events, its nested ``task`` call and its completion are keyed
  to the right ``task`` call.

Blocking sub-agents only: async sub-agents (the default) replace this path, which
stays for ``ASYNC_SUBAGENTS_ENABLED=false``.
"""

from __future__ import annotations

import asyncio
import itertools
import json
from pathlib import Path
from typing import Any

import pytest
import yaml
from conftest import run_config
from deepagents import _models as deepagents_models
from deepagents.backends import StateBackend
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command
from pydantic import Field

from core.settings import settings
from harness.abstractions.agent_spec import AgentSpec
from harness.abstractions.yaml_agent import YamlDeepAgent
from harness.agui import normalizer

QUESTION = "How tall is the Eiffel Tower? Please verify it."

AGENT_YAML = {
    "id": "nested-research-demo",
    "slug": "nested-research-demo",
    "name": "Nested research demo",
    "version": "1.0.0",
    "type": "deep_agent",
    "description": "Answers a factual question by delegating research.",
    "prompt": "./AGENT.md",
    "model": {"main": "openai:gpt-4.1-mini"},
    "tools": [],
    "subagents": [
        {
            "name": "researcher",
            "description": "Researches a question and has its key fact checked.",
            "prompt": "./subagents/researcher.md",
            "subagents": [
                {
                    "name": "fact-checker",
                    "description": "Verifies one factual claim.",
                    "prompt": "./subagents/fact-checker.md",
                }
            ],
        }
    ],
}

PROMPTS = {
    "AGENT.md": "You are the demo orchestrator. Delegate research to `researcher`.",
    "subagents/researcher.md": "You are the demo researcher. Delegate the claim to `fact-checker`.",
    "subagents/fact-checker.md": "You are the demo fact-checker. Say TRUE or FALSE.",
}


def _task(call_id: str, subagent: str, description: str) -> dict:
    return {
        "id": call_id,
        "name": "task",
        "args": {"subagent_type": subagent, "description": description},
    }


# One model for every agent, answering by the role its system prompt opens with.
SCRIPTS: dict[str, list[tuple[str, list[dict]]]] = {
    "You are the demo orchestrator": [
        ("", [_task("call-research", "researcher", "How tall is the Eiffel Tower?")]),
        ("The Eiffel Tower is 330 m tall; the researcher's fact-checker confirmed it.", []),
    ],
    "You are the demo researcher": [
        ("", [{"id": "call-research-ls", "name": "ls", "args": {"path": "/"}}]),
        ("", [_task("call-check", "fact-checker", "Verify: the Eiffel Tower is 330 m tall.")]),
        ("Report: the Eiffel Tower is 330 m tall; the fact-checker confirmed it.", []),
    ],
    "You are the demo fact-checker": [
        # Not in its tool set: the tool node refuses the call.
        ("", [{"id": "call-check-ask", "name": "ask_user", "args": {"questions": []}}]),
        ("", [{"id": "call-check-ls", "name": "ls", "args": {"path": "/"}}]),
        ("TRUE: the Eiffel Tower is 330 m tall including its antennas.", []),
    ],
}

_ids = itertools.count(1)


class ScriptedModel(FakeMessagesListChatModel):
    """Every agent's model: the next scripted reply of the agent whose system
    prompt it is called with."""

    responses: list = Field(default_factory=list)
    model_name: str = "scripted-demo"
    cursor: dict = Field(default_factory=dict)

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        system = messages[0].text if messages else ""
        role = next((r for r in SCRIPTS if system.startswith(r)), None)
        if role is None:
            raise AssertionError(f"no script for system prompt: {system[:80]!r}")
        index = self.cursor.get(role, 0)
        self.cursor[role] = index + 1
        text, calls = SCRIPTS[role][index]
        n = next(_ids)
        message = AIMessage(
            id=f"msg-{role.rsplit(' ', 1)[-1]}-{n}",
            content=text,
            tool_calls=[{**call, "type": "tool_call"} for call in calls],
            usage_metadata={
                "input_tokens": 100 * n,
                "output_tokens": 10 * n,
                "total_tokens": 110 * n,
            },
            response_metadata={"model_name": "scripted-demo"},
        )
        return ChatResult(generations=[ChatGeneration(message=message)])

    async def _agenerate(self, *args, **kwargs):
        await asyncio.sleep(0.01)
        return self._generate(*args, **kwargs)


def _write_agent(root: Path) -> Path:
    folder = root / "nested-research-demo"
    (folder / "subagents").mkdir(parents=True)
    (folder / "agent.yaml").write_text(yaml.safe_dump(AGENT_YAML), encoding="utf-8")
    for name, text in PROMPTS.items():
        (folder / name).write_text(text, encoding="utf-8")
    return folder


def _make_agent(folder: Path, spec: AgentSpec, *, checkpointer, run_id: str, thread_id: str):
    """A fresh agent instance per stream, as each /stream and /resume request
    builds one. Only the workspace is swapped for in-memory state: the real one
    is database-backed."""
    config = run_config(run_id=run_id, thread_id=thread_id)
    config["run_config"]["recursion_limit"] = 200
    agent = YamlDeepAgent(spec, folder, config=config)
    agent.checkpointer = checkpointer
    agent._build_composite_backend = lambda: StateBackend()
    return agent


def _decode(frame: Any) -> dict:
    text = frame.decode("utf-8") if isinstance(frame, (bytes, bytearray)) else str(frame)
    for line in text.splitlines():
        if line.startswith("data:"):
            return json.loads(line[len("data:") :].lstrip())
    return {"type": "UNDECODABLE", "raw": text}


async def _run_legs(folder: Path, *, max_legs: int = 6) -> tuple[list[list[dict]], list[Any]]:
    """Stream the question, approving every pause on a new agent instance.

    Returns the AG-UI events of each stream and every raw chunk."""
    raw_yaml = yaml.safe_load((folder / "agent.yaml").read_text(encoding="utf-8"))
    spec = AgentSpec.model_validate(raw_yaml)
    checkpointer = MemorySaver()
    run_id, thread_id = "demo-run", "demo-thread"
    normalizer.release_namespace_bindings(run_id)
    legs: list[list[dict]] = []
    raw: list[Any] = []
    command: Command | None = None
    for _ in range(max_legs):
        agent = _make_agent(
            folder, spec, checkpointer=checkpointer, run_id=run_id, thread_id=thread_id
        )
        if command is not None:
            await agent.ensure_built()
            snapshot = await agent.compiled.aget_state(agent.run_config)
            agent.agui_normalizer.seed_pending_tasks(snapshot.values.get("messages"))
        handle = agent.agui_normalizer.handle_chunk

        def spy(chunk, handle=handle):
            raw.append(chunk)
            return handle(chunk)

        agent.agui_normalizer.handle_chunk = spy
        payload = {"messages": [{"role": "user", "content": QUESTION}]}
        events = [_decode(frame) async for frame in agent.astream(payload, command=command)]
        legs.append(events)
        snapshot = await agent.compiled.aget_state(agent.run_config)
        if not snapshot.interrupts:
            break
        requests = (snapshot.interrupts[0].value or {}).get("action_requests") or [None]
        command = Command(resume={"decisions": [{"type": "approve"}] * len(requests)})
    normalizer.release_namespace_bindings(run_id)
    return legs, raw


def _custom(event: dict, name: str) -> dict | None:
    if event.get("type") == "CUSTOM" and event.get("name") == name:
        return event.get("value")
    return None


def _envelopes(events: list[dict]) -> list[dict]:
    return [v for e in events if (v := _custom(e, "SUBAGENT_EVENT")) is not None]


@pytest.fixture
def run(monkeypatch, tmp_path: Path):
    """The whole example run, every model the build resolves being the scripted one."""
    settings.async_tasks.enabled = False
    model = ScriptedModel(responses=[], cursor={})
    monkeypatch.setattr(deepagents_models, "init_chat_model", lambda *a, **k: model)
    return asyncio.run(_run_legs(_write_agent(tmp_path)))


def test_the_task_gate_pauses_both_levels_of_delegation(run):
    legs, _ = run
    assert len(legs) == 3
    first = [v for e in legs[0] if (v := _custom(e, "HITL_INTERRUPT"))]
    assert [a["name"] for a in first[0]["interrupt"]["value"]["action_requests"]] == ["task"]
    # The second pause is the researcher's own `task` call, raised inside its stream.
    nested = [
        (env["task_id"], inner["value"])
        for env in _envelopes(legs[1])
        if (inner := env["event"]).get("name") == "HITL_INTERRUPT"
    ]
    assert nested
    assert nested[0][0] == "call-research"
    request = nested[0][1]["interrupt"]["value"]["action_requests"][0]
    assert request["args"]["subagent_type"] == "fact-checker"


def test_each_level_is_keyed_to_its_task_call(run):
    legs, _ = run
    events = [e for leg in legs for e in leg]
    envelopes = _envelopes(events)
    by_task: dict[str, list[dict]] = {}
    for env in envelopes:
        by_task.setdefault(env["task_id"], []).append(env)

    assert set(by_task) == {"call-research", "call-check"}
    assert {len(env["namespace"]) for env in by_task["call-research"]} == {1}
    assert {len(env["namespace"]) for env in by_task["call-check"]} == {2}
    nested_calls = [
        inner["value"]["task_id"]
        for env in by_task["call-research"]
        if (inner := env["event"]).get("name") == "TASK_SUBAGENT"
    ]
    assert set(nested_calls) == {"call-check"}
    tools = sorted(
        (env["task_id"], env["event"]["toolCallId"], env["event"]["toolCallName"])
        for env in envelopes
        if env["event"].get("type") == "TOOL_CALL_START"
    )
    assert tools == [
        ("call-check", "call-check-ls", "ls"),
        ("call-research", "call-research-ls", "ls"),
    ]
    completed_inside = [
        (env["task_id"], inner["value"]["task_id"])
        for env in envelopes
        if (inner := env["event"]).get("name") == "SUBAGENT_COMPLETED"
    ]
    assert completed_inside == [("call-research", "call-check")]
    top = [v["task_id"] for e in events if (v := _custom(e, "SUBAGENT_COMPLETED"))]
    assert top == ["call-research"]
    answer = "".join(
        e.get("delta") or ""
        for e in events
        if e.get("type") in {"TEXT_MESSAGE_CHUNK", "TEXT_MESSAGE_CONTENT"}
    )
    assert answer.startswith("The Eiffel Tower is 330 m tall")


def test_every_level_reports_its_token_usage(run):
    legs, _ = run
    envelopes = _envelopes([e for leg in legs for e in leg])
    usage_by_task = {
        env["task_id"] for env in envelopes if env["event"].get("name") == "TOKEN_USAGE"
    }
    assert usage_by_task == {"call-research", "call-check"}


def test_ask_user_is_not_a_tool_of_a_nested_subagent(run):
    _, raw = run
    refusals = [
        payload
        for chunk in raw
        for payload in [chunk[2][0] if chunk[1] == "messages" else None]
        if isinstance(payload, ToolMessage) and payload.tool_call_id == "call-check-ask"
    ]
    assert refusals, "the fact-checker's ask_user call never came back"
    assert all(
        m.status == "error" and "ask_user is not a valid tool" in str(m.content) for m in refusals
    )
