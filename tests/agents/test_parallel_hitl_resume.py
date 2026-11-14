"""Parallel approvals: several interrupts pending at once, each answered by id.

The orchestrator delegates to three sub-agents in parallel and each one stops at
its own approval gate, so the checkpoint holds three interrupts at once. A
decision must reach the interrupt it was made for, whether the three are
answered together (one resume, ``Command(resume={interrupt_id: value, ...})``),
in part, or one at a time in any order. A bare resume value would go to
whichever paused task read it first.

The end-to-end tests build the real agent (``YamlDeepAgent`` -> deepagents ->
LangGraph, a three-level spec with scripted models), resume each leg on a fresh
instance like ``/resume`` does, and build every command with the route's own
:func:`utils.hitl_resume.build_resume_command`. The route tests check the
request shapes on top of that, with a stand-in agent.
"""

from __future__ import annotations

import asyncio
import importlib
import itertools
import json
from pathlib import Path
from typing import Any

import pytest
import route_fakes
from conftest import run_config
from deepagents.backends import StateBackend
from fastapi import HTTPException
from langchain.agents.middleware import human_in_the_loop
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command
from pydantic import Field

from core.logging import get_logger
from core.settings import settings
from harness.abstractions import AgentSpec, YamlDeepAgent
from harness.checkpointer.store import set_checkpointer
from harness.middlewares import tool_error
from schema.inference import AgentResumeRequest
from utils.hitl_resume import build_resume_command

_ids = itertools.count(1)
CLAIMS = ("1", "2", "3")
THREAD = "parallel-thread"

_ORCHESTRATOR = "You are the demo orchestrator. Delegate research with the `task` tool."
_RESEARCHER = "You are the demo researcher. Delegate each claim to your fact-checker."
_FACT_CHECKER = "You are the demo fact-checker. Say whether the claim holds."


@pytest.fixture(autouse=True)
def _blocking_subagents():
    """These tests pin the blocking ``task`` path (async sub-agents replace it when on)."""
    settings.async_tasks.enabled = False


def _spec(hitl: dict[str, bool]) -> AgentSpec:
    """main -> researcher -> fact-checker, prompts inline so no folder is needed."""
    return AgentSpec.model_validate(
        {
            "id": "parallel-demo",
            "slug": "parallel-demo",
            "name": "Parallel demo",
            "version": "1.0.0",
            "type": "deep_agent",
            "prompt": _ORCHESTRATOR,
            "model": {"main": "openai:gpt-4o-mini"},
            "subagents": [
                {
                    "name": "researcher",
                    "description": "Researches a claim and has it fact-checked.",
                    "prompt": _RESEARCHER,
                    "subagents": [
                        {
                            "name": "fact-checker",
                            "description": "Verifies one factual claim.",
                            "prompt": _FACT_CHECKER,
                        }
                    ],
                }
            ],
            "hitl": hitl,
        }
    )


def _task(call_id: str, subagent: str, description: str) -> dict[str, Any]:
    return {
        "id": call_id,
        "name": "task",
        "args": {"subagent_type": subagent, "description": description},
    }


class _ScriptedBase(FakeMessagesListChatModel):
    """Answers by role and by how far that agent's own conversation got, so
    parallel instances of one sub-agent never share a script cursor."""

    responses: list = Field(default_factory=list)

    def bind_tools(self, tools, **kwargs):
        return self

    def script(self, role: str, steps: int, claim: str) -> tuple[list[dict], str]:
        raise NotImplementedError

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        system = messages[0].text if messages else ""
        steps = sum(1 for m in messages if isinstance(m, AIMessage))
        brief = next((m.text for m in messages[1:] if m.type == "human"), "")
        claim = brief.rsplit(" ", 1)[-1]
        for role, prompt in (
            ("orchestrator", _ORCHESTRATOR),
            ("researcher", _RESEARCHER),
            ("fact-checker", _FACT_CHECKER),
        ):
            if system.startswith(prompt):
                calls, text = self.script(role, steps, claim)
                break
        else:
            raise AssertionError(f"no script for system prompt: {system[:80]!r}")
        message = AIMessage(
            id=f"msg-scripted-{next(_ids)}",
            content=text,
            tool_calls=[{**call, "type": "tool_call"} for call in calls],
        )
        return ChatResult(generations=[ChatGeneration(message=message)])

    async def _agenerate(self, *args, **kwargs):
        await asyncio.sleep(0.01)
        return self._generate(*args, **kwargs)


class ParallelModel(_ScriptedBase):
    """Orchestrator -> three researchers in parallel -> each delegates to a
    fact-checker through the gated ``task`` tool, so three gates pause at once."""

    def script(self, role, steps, claim):
        if role == "orchestrator":
            if steps == 0:
                return [
                    _task(f"call-r{k}", "researcher", f"Research claim {k}") for k in CLAIMS
                ], ""
            return [], "All three claims were researched."
        if role == "researcher":
            if steps == 0:
                return [_task(f"call-c{claim}", "fact-checker", f"Verify claim {claim}")], ""
            return [], f"Report {claim}"
        return [], f"TRUE claim {claim}"


class NestedModel(_ScriptedBase):
    """main -> one researcher -> three parallel fact-checkers, each paused on ``ls``."""

    def script(self, role, steps, claim):
        if role == "orchestrator":
            if steps == 0:
                return [_task("call-research", "researcher", "Research all claims")], ""
            return [], "All claims researched."
        if role == "researcher":
            if steps == 0:
                return [
                    _task(f"call-c{k}", "fact-checker", f"Verify claim {k}") for k in CLAIMS
                ], ""
            return [], "Report"
        if steps == 0:
            return [{"id": f"call-ls{claim}", "name": "ls", "args": {"path": "/"}}], ""
        return [], f"TRUE claim {claim}"


def _use_model(monkeypatch, model: Any) -> None:
    deep_models = importlib.import_module("deepagents._models")
    monkeypatch.setattr(deep_models, "init_chat_model", lambda *_a, **_k: model)


@pytest.fixture
def scripted(monkeypatch):
    _use_model(monkeypatch, ParallelModel(responses=[]))


@pytest.fixture
def nested_scripted(monkeypatch):
    _use_model(monkeypatch, NestedModel(responses=[]))


@pytest.fixture
def tool_errors(monkeypatch):
    """Every tool failure the run turned into an error result, with its message."""
    errors: list[str] = []
    original = tool_error.ToolErrorMiddleware._error_message

    def spy(request, exc):
        errors.append(f"{request.tool_call.get('name')}: {type(exc).__name__}: {exc}")
        return original(request, exc)

    monkeypatch.setattr(tool_error.ToolErrorMiddleware, "_error_message", staticmethod(spy))
    return errors


def _decode(frame: Any) -> dict[str, Any]:
    text = frame.decode("utf-8") if isinstance(frame, (bytes, bytearray)) else str(frame)
    for line in text.splitlines():
        if line.startswith("data:"):
            return json.loads(line[len("data:") :].lstrip())
    return {"type": "UNDECODABLE", "raw": text}


def _hitl_values(frames: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for frame in frames:
        if frame.get("type") != "CUSTOM":
            continue
        if frame.get("name") == "HITL_INTERRUPT":
            out.append(frame["value"])
        elif frame.get("name") == "SUBAGENT_EVENT":
            inner = (frame.get("value") or {}).get("event") or {}
            if inner.get("name") == "HITL_INTERRUPT":
                out.append(inner["value"])
    return out


def _claim(interrupt_value: dict[str, Any]) -> str:
    args = interrupt_value["action_requests"][0]["args"]
    return str(args.get("description", "")).rsplit(" ", 1)[-1]


def _claims_of(values: list[dict[str, Any]]) -> set[str]:
    return {
        _claim(v["interrupt"]["value"])
        for v in values
        if len(v["interrupt"]["value"]["action_requests"]) == 1
    }


def _approve(interrupt_id: str) -> dict[str, Any]:
    return {"interrupt_id": interrupt_id, "decision": "approve"}


def _reject(interrupt_id: str, reason: str) -> dict[str, Any]:
    return {"interrupt_id": interrupt_id, "decision": "reject", "reason": reason}


class _Run:
    """One conversation thread, resumed leg by leg on fresh agent instances."""

    def __init__(self, folder: Path, hitl: dict[str, bool]) -> None:
        self.spec = _spec(hitl)
        self.folder = folder
        self.checkpointer = MemorySaver()
        self.logger = get_logger("tests.parallel_resume")
        self.emitted: list[list[str]] = []
        self.pending: list[Any] = []
        self.state: dict[str, Any] = {}

    def _agent(self) -> YamlDeepAgent:
        config = run_config(thread_id=THREAD, run_id="parallel-run")
        config["run_config"]["recursion_limit"] = 200
        agent = YamlDeepAgent(self.spec, self.folder, config=config)
        agent.checkpointer = self.checkpointer
        # The workspace is LangGraph state: no conversation files, no database.
        agent._build_composite_backend = StateBackend
        return agent

    async def leg(self, command: Command | None) -> list[Any]:
        """Stream one leg; returns the interrupts the run is paused on after it."""
        agent = self._agent()
        if command is not None:
            await agent.ensure_built()
            snapshot = await agent.compiled.aget_state(agent.run_config)
            agent.agui_normalizer.seed_pending_tasks(snapshot.values.get("messages"))
        payload = {"messages": [{"role": "user", "content": "q"}]}
        frames = [_decode(f) async for f in agent.astream(payload, command=command)]
        self.emitted.append(sorted(_claims_of(_hitl_values(frames))))
        snapshot = await agent.compiled.aget_state(agent.run_config)
        self.state = snapshot.values
        return list(snapshot.interrupts or [])

    def command(self, **request: Any) -> Command:
        body = {"config": {}, "thread_id": THREAD, "decision": "approve", **request}
        return build_resume_command(AgentResumeRequest(**body), self.pending, self.logger)

    async def pause_on_three_gates(self) -> dict[str, str]:
        """Approve the orchestrator's three delegations; returns claim -> interrupt id."""
        first = await self.leg(None)
        assert len(first) == 1 and len(first[0].value["action_requests"]) == 3
        self.pending = first
        self.pending = await self.leg(self.command(interrupt_id=first[0].id))
        ids = {_claim(i.value): i.id for i in self.pending}
        assert sorted(ids) == list(CLAIMS) and len(set(ids.values())) == 3
        return ids

    async def pause_on_three_nested_gates(self) -> None:
        """Approve the ``task`` pauses one at a time, as the chat does, until the
        three fact-checkers wait on their ``ls`` gates."""
        self.pending = await self.leg(None)
        while len(self.pending) == 1:
            self.pending = await self.leg(self.command(interrupt_id=self.pending[0].id))
        assert len(self.pending) == 3
        assert all(i.value["action_requests"][0]["name"] == "ls" for i in self.pending)

    def tool_result(self, call_id: str) -> str:
        """What one of the orchestrator's ``task`` calls returned (a researcher's report)."""
        return next(
            str(m.content)
            for m in self.state["messages"]
            if m.type == "tool" and m.tool_call_id == call_id
        )


@pytest.fixture
def parallel_run(tmp_path, scripted) -> _Run:
    return _Run(tmp_path, {"task": True})


@pytest.fixture
def nested_run(tmp_path, nested_scripted) -> _Run:
    # Every `ls` waits for approval too.
    return _Run(tmp_path, {"task": True, "ls": True})


# ---------------------------------------------------------------------------
# End to end through LangGraph
# ---------------------------------------------------------------------------
async def test_three_parallel_approvals_apply_together_in_one_resume(parallel_run):
    run = parallel_run
    ids = await run.pause_on_three_gates()
    command = run.command(
        resumes=[_approve(ids["2"]), _reject(ids["3"], "not claim 3"), _approve(ids["1"])]
    )
    assert set(command.resume) == set(ids.values())
    assert await run.leg(command) == []
    # Every researcher reported: the two approved fact-checks ran, the rejected
    # one came back to its researcher as the rejection.
    assert [run.tool_result(f"call-r{k}") for k in CLAIMS] == ["Report 1", "Report 2", "Report 3"]
    assert run.state["messages"][-1].content == "All three claims were researched."


async def test_a_partial_batch_leaves_the_rest_pending_and_they_resume_later(parallel_run):
    run = parallel_run
    ids = await run.pause_on_three_gates()
    run.pending = await run.leg(run.command(resumes=[_approve(ids["1"]), _approve(ids["3"])]))
    # The stream re-surfaces only the gate still waiting.
    assert run.emitted[-1] == ["2"]
    assert run.pending, "the run finished without claim 2's decision"
    assert await run.leg(run.command(**_approve(ids["2"]))) == []
    assert run.state["messages"][-1].content == "All three claims were researched."


async def test_one_at_a_time_each_decision_reaches_its_own_interrupt(parallel_run, monkeypatch):
    # Reject claim 2 only, answering in the order 2, 1, 3: the rejection must
    # land on researcher 2's gate and nowhere else.
    verdicts: dict[str, str] = {}
    original = human_in_the_loop.HumanInTheLoopMiddleware.after_model

    def spy(self, state, runtime):
        result = original(self, state, runtime)
        for message in (result or {}).get("messages", []):
            if message.type == "tool":
                verdicts[message.tool_call_id] = str(message.content)
        return result

    monkeypatch.setattr(human_in_the_loop.HumanInTheLoopMiddleware, "after_model", spy)
    run = parallel_run
    ids = await run.pause_on_three_gates()
    run.pending = await run.leg(run.command(**_reject(ids["2"], "skip claim 2")))
    assert run.emitted[-1] == ["1", "3"]
    run.pending = await run.leg(run.command(**_approve(ids["1"])))
    assert run.emitted[-1] == ["3"]
    assert await run.leg(run.command(**_approve(ids["3"]))) == []
    assert list(verdicts) == ["call-c2"]
    assert "skip claim 2" in verdicts["call-c2"]


async def test_a_decision_for_an_interrupt_that_is_not_pending_is_refused(parallel_run):
    run = parallel_run
    await run.pause_on_three_gates()
    with pytest.raises(HTTPException) as refused:
        run.command(interrupt_id="0" * 32)
    assert refused.value.status_code == 409
    # The 409 says which ids are stale and which are still pending, so the
    # backend can drop the stale decision and send the rest again.
    assert refused.value.detail["stale_interrupt_ids"] == ["0" * 32]
    assert sorted(refused.value.detail["pending_interrupt_ids"]) == sorted(
        i.id for i in run.pending
    )


async def test_a_nested_partial_resume_keeps_every_other_helper_alive(nested_run, tool_errors):
    # One helper's approval goes out alone: a stale run-wide answer from an
    # earlier `task` approval must not reach another helper's gate ("Number of
    # human decisions (3) does not match number of hanging tool calls (1)").
    run = nested_run
    await run.pause_on_three_nested_gates()
    first, *rest = [i.id for i in run.pending]
    run.pending = await run.leg(run.command(**_approve(first)))
    assert sorted(i.id for i in run.pending) == sorted(rest), "a helper's approval vanished"
    run.pending = await run.leg(run.command(resumes=[_approve(i) for i in rest]))
    assert run.pending == []
    assert run.state["messages"][-1].content == "All claims researched."
    assert tool_errors == []


async def test_nested_helpers_answered_one_at_a_time_all_finish(nested_run, tool_errors):
    run = nested_run
    await run.pause_on_three_nested_gates()
    for _ in range(3):
        assert run.pending, "the run lost a pending approval"
        run.pending = await run.leg(run.command(**_approve(run.pending[-1].id)))
    assert run.pending == []
    assert run.state["messages"][-1].content == "All claims researched."
    assert tool_errors == []


# ---------------------------------------------------------------------------
# The /resume route
# ---------------------------------------------------------------------------
_A, _B, _C = "a" * 32, "b" * 32, "c" * 32


class _ThreeGatesAgent(route_fakes.FakeAgent):
    interrupts = (route_fakes.interrupt(_A), route_fakes.interrupt(_B), route_fakes.interrupt(_C))


class _OneGateAgent(route_fakes.FakeAgent):
    interrupts = (route_fakes.interrupt(_A),)


class _LegacyIdAgent(route_fakes.FakeAgent):
    interrupts = (route_fakes.interrupt("int-1"),)


class _BatchedGateAgent(route_fakes.FakeAgent):
    interrupts = (route_fakes.interrupt(_A, actions=3),)


@pytest.fixture
def saver():
    set_checkpointer(MemorySaver())
    yield
    set_checkpointer(None)


def _resume(client, internal_headers, **body):
    payload = {"config": run_config(), "thread_id": "t-1", "decision": "approve", **body}
    return client.post("/agents/fake/resume", headers=internal_headers, json=payload)


async def test_route_applies_a_batch_keyed_by_interrupt(
    client, internal_headers, monkeypatch, saver
):
    built = route_fakes.install(monkeypatch, _ThreeGatesAgent)
    response = await _resume(
        client, internal_headers, interrupt_id=_C, resumes=[_approve(_C), _reject(_A, "no")]
    )
    assert response.status_code == 200
    assert built[0].commands[0].resume == {
        _C: {"decisions": [{"type": "approve"}]},
        _A: {"decisions": [{"type": "reject", "message": "no"}]},
    }
    # A resume streams no new input: the command is the whole input.
    assert built[0].payloads[0] == {"messages": []}


async def test_route_targets_the_named_interrupt_not_the_first(
    client, internal_headers, monkeypatch, saver
):
    built = route_fakes.install(monkeypatch, _ThreeGatesAgent)
    response = await _resume(
        client, internal_headers, interrupt_id=_B, decision="reject", reason="later"
    )
    assert response.status_code == 200
    assert built[0].commands[0].resume == {
        _B: {"decisions": [{"type": "reject", "message": "later"}]}
    }


async def test_route_refuses_a_batch_with_an_interrupt_that_is_not_pending(
    client, internal_headers, monkeypatch, saver
):
    built = route_fakes.install(monkeypatch, _ThreeGatesAgent)
    response = await _resume(client, internal_headers, resumes=[_approve(_A), _approve("d" * 32)])
    assert response.status_code == 409
    assert built[0].commands == []
    # Listed through the service's error handler, so the backend can recover.
    detail = response.json()["detail"]
    assert detail["stale_interrupt_ids"] == ["d" * 32]
    assert detail["pending_interrupt_ids"] == [_A, _B, _C]


async def test_route_refuses_a_batch_answering_one_interrupt_twice(
    client, internal_headers, monkeypatch, saver
):
    built = route_fakes.install(monkeypatch, _ThreeGatesAgent)
    response = await _resume(client, internal_headers, resumes=[_approve(_A), _reject(_A, "no")])
    assert response.status_code == 422
    assert built[0].commands == []


async def test_route_keys_a_single_pending_interrupt_too(
    client, internal_headers, monkeypatch, saver
):
    # Never a bare value for a real interrupt id: a bare value is stored as a
    # run-wide answer a nested sub-agent's later gate could read as its own.
    built = route_fakes.install(monkeypatch, _OneGateAgent)
    response = await _resume(client, internal_headers, interrupt_id=_A)
    assert response.status_code == 200
    assert built[0].commands[0].resume == {_A: {"decisions": [{"type": "approve"}]}}


async def test_route_keeps_a_bare_value_for_an_id_langgraph_would_not_key(
    client, internal_headers, monkeypatch, saver
):
    built = route_fakes.install(monkeypatch, _LegacyIdAgent)
    response = await _resume(client, internal_headers, interrupt_id="int-1")
    assert response.status_code == 200
    assert built[0].commands[0].resume == {"decisions": [{"type": "approve"}]}


async def test_route_without_an_interrupt_id_answers_the_first_pending_one(
    client, internal_headers, monkeypatch, saver
):
    built = route_fakes.install(monkeypatch, _OneGateAgent)
    response = await _resume(client, internal_headers, decision="reject")
    assert response.status_code == 200
    # A reject without a reason still carries the message LangChain requires.
    assert built[0].commands[0].resume == {
        _A: {"decisions": [{"type": "reject", "message": "User rejected this action."}]}
    }


async def test_route_replicates_one_decision_across_a_batched_gate(
    client, internal_headers, monkeypatch, saver
):
    built = route_fakes.install(monkeypatch, _BatchedGateAgent)
    response = await _resume(client, internal_headers, interrupt_id=_A)
    assert response.status_code == 200
    assert built[0].commands[0].resume == {_A: {"decisions": [{"type": "approve"}] * 3}}


async def test_route_applies_per_action_decisions_in_order(
    client, internal_headers, monkeypatch, saver
):
    built = route_fakes.install(monkeypatch, _BatchedGateAgent)
    decisions = [
        {"decision": "approve"},
        {"decision": "reject", "reason": "not this one"},
        {"decision": "approve"},
    ]
    response = await _resume(client, internal_headers, interrupt_id=_A, decisions=decisions)
    assert response.status_code == 200
    assert built[0].commands[0].resume == {
        _A: {
            "decisions": [
                {"type": "approve"},
                {"type": "reject", "message": "not this one"},
                {"type": "approve"},
            ]
        }
    }


async def test_route_refuses_a_per_action_count_mismatch(
    client, internal_headers, monkeypatch, saver
):
    built = route_fakes.install(monkeypatch, _BatchedGateAgent)
    response = await _resume(
        client, internal_headers, interrupt_id=_A, decisions=[{"decision": "approve"}]
    )
    assert response.status_code == 422
    assert built[0].commands == []


async def test_route_resumes_the_body_thread_whatever_the_config_says(
    client, internal_headers, monkeypatch, saver
):
    built = route_fakes.install(monkeypatch, _OneGateAgent)
    response = await _resume(
        client, internal_headers, thread_id="paused-thread", config=run_config(thread_id="other")
    )
    assert response.status_code == 200
    assert built[0].run_config["configurable"]["thread_id"] == "paused-thread"
    events = route_fakes.sse_events(response.text)
    assert events[-1]["value"]["thread_id"] == "paused-thread"


@pytest.mark.parametrize("count", [0, 65])
async def test_route_bounds_the_batch_size(client, internal_headers, monkeypatch, saver, count):
    route_fakes.install(monkeypatch, _ThreeGatesAgent)
    resumes = [_approve(f"{n:032x}") for n in range(count)]
    response = await _resume(client, internal_headers, resumes=resumes)
    assert response.status_code == 422
