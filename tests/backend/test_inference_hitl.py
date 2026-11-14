"""HITL approvals: the per-interrupt decision queue, the paused run on the
manager end to end (parallel approvals, batching, stale recovery, cancel),
the ``/resume`` body sent upstream, and the ``/resume`` route.

The run is driven by the real ``InferenceRunManager._run``; the agents service
is simulated at the ``_do_stream`` / ``_do_resume`` seam by :class:`FakeAgents`,
which keeps its own pending interrupts like the real service does.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx
import pytest
import pytest_asyncio
from conftest import CLIENT_ID
from run_helpers import RESUME_PATH, finished, seed_queued_run, until

import utils.inference_runs as ir
from core.settings import settings
from utils.hitl_decisions import EXPIRED_DECISION, HitlDecisionQueue, ResumeOutcome, StaleDecisions
from utils.inference_runs import inference_run_manager

IDS = ("int-1", "int-2", "int-3")


def _decision(interrupt_id: str | None, decision: str = "approve", **extra: Any) -> dict[str, Any]:
    return {
        "interrupt_id": interrupt_id,
        "decision": decision,
        "reason": None,
        "value": None,
        "decisions": None,
        **extra,
    }


# --- HitlDecisionQueue -----------------------------------------------------
def test_decisions_queue_per_interrupt_and_come_out_in_pending_order():
    queue = HitlDecisionQueue()
    for interrupt_id in ("int-3", "int-1", "int-2"):
        assert queue.offer(_decision(interrupt_id), list(IDS))[0] is ResumeOutcome.ACCEPTED
    assert [token for token, _ in queue.take_ready(list(IDS))] == list(IDS)
    assert len(queue) == 0


def test_without_batching_one_decision_goes_out_per_take():
    queue = HitlDecisionQueue()
    for interrupt_id in IDS:
        queue.offer(_decision(interrupt_id), list(IDS))
    assert [t for t, _ in queue.take_ready(list(IDS), batch=False)] == ["int-1"]
    assert [t for t, _ in queue.take_ready(list(IDS[1:]), batch=False)] == ["int-2"]
    assert len(queue) == 1


def test_unknown_repeat_and_conflicting_decisions():
    queue = HitlDecisionQueue()
    assert queue.offer(_decision("made-up"), list(IDS))[0] is ResumeOutcome.UNKNOWN_INTERRUPT
    assert queue.offer(_decision("made-up"), [])[0] is ResumeOutcome.NOT_PAUSED
    queue.offer(_decision("int-1"), list(IDS))
    assert queue.offer(_decision("int-1"), list(IDS))[0] is ResumeOutcome.ALREADY_RECEIVED
    conflicting = queue.offer(_decision("int-1", "reject"), list(IDS))[0]
    assert conflicting is ResumeOutcome.CONFLICTING_DECISION


def test_a_decision_without_an_id_answers_the_first_undecided_one():
    queue = HitlDecisionQueue()
    queue.offer(_decision("int-1"), list(IDS))
    assert queue.offer(_decision(None), list(IDS)) == (ResumeOutcome.ACCEPTED, "int-2")
    # An id-less decision cannot be keyed for a batch: it goes out on its own.
    assert [t for t, _ in queue.take_ready(list(IDS))] == ["int-1"]


def test_a_second_pause_on_an_answered_interrupt_takes_a_new_decision():
    queue = HitlDecisionQueue()
    queue.offer(_decision("int-1"), list(IDS))
    queue.take_ready(list(IDS))
    queue.forget_answered(["int-1"])
    assert queue.offer(_decision("int-1", "reject"), list(IDS))[0] is ResumeOutcome.ACCEPTED


def test_refusals_carry_a_message_for_the_409():
    for outcome in ResumeOutcome:
        assert bool(outcome.detail) is not outcome.accepted


# --- the paused run, end to end -------------------------------------------
class FakeAgents:
    """Three interrupts surface on the first leg; each resume answers some."""

    def __init__(self) -> None:
        self.pending = list(IDS)
        self.legs: list[list[str]] = []
        self.refused: list[list[str]] = []
        self.leg_seconds = 0.05
        self.leg_running = asyncio.Event()

    @staticmethod
    def _interrupts(ids: list[str]) -> list[dict[str, Any]]:
        events = []
        for interrupt_id in ids:
            hitl = {
                "type": "CUSTOM",
                "name": "HITL_INTERRUPT",
                "value": {"interrupt": {"id": interrupt_id}},
            }
            # Delivered twice, like a sub-agent's interrupt: wrapped and bare.
            events.append(
                {
                    "type": "CUSTOM",
                    "name": "SUBAGENT_EVENT",
                    "value": {"task_id": f"task-{interrupt_id}", "event": hitl},
                }
            )
            events.append(hitl)
        return events

    async def _emit(self, manager, run_id, run_meta, runtime, events) -> None:
        applied = [e for e in (runtime.apply_event(event) for event in events) if e is not None]
        await manager._publish_delta(run_id, run_meta, runtime, applied)

    async def stream(self, manager, run_id, run_meta, runtime, url, payload) -> str:
        await self._emit(manager, run_id, run_meta, runtime, self._interrupts(self.pending))
        return "completed"

    async def resume(self, manager, run_id, run_meta, runtime, url, config, payloads) -> str:
        ids = [p["interrupt_id"] for p in payloads]
        stale = [i for i in ids if i not in self.pending]
        if stale:
            self.refused.append(ids)
            raise StaleDecisions(stale, list(self.pending))
        self.legs.append(ids)
        self.pending = [i for i in self.pending if i not in ids]
        self.leg_running.set()
        await asyncio.sleep(self.leg_seconds)
        self.leg_running.clear()
        await self._emit(manager, run_id, run_meta, runtime, self._interrupts(self.pending))
        return "completed"


@pytest_asyncio.fixture
async def seeded_run(session_factory, monkeypatch):
    monkeypatch.setattr(ir, "SessionLocal", session_factory)
    return await seed_queued_run(session_factory, CLIENT_ID, "Edit three files in parallel")


@pytest.fixture
def fake_agents(monkeypatch):
    fake = FakeAgents()

    async def _do_stream(self, *args):
        return await fake.stream(self, *args)

    async def _do_resume(self, *args):
        return await fake.resume(self, *args)

    monkeypatch.setattr(ir.InferenceRunManager, "_do_stream", _do_stream)
    monkeypatch.setattr(ir.InferenceRunManager, "_do_resume", _do_resume)
    return fake


def _paused_on_three(run_id: str) -> bool:
    runtime = inference_run_manager._runtimes.get(run_id)
    return runtime is not None and runtime.pending_interrupts == 3


def _markers(run) -> dict[str, dict[str, Any]]:
    """The last resolved marker per interrupt."""
    return {
        e["value"]["interrupt_id"]: e["value"]
        for e in run.raw_events or []
        if e.get("type") == "CUSTOM" and e.get("name") == "BRIDGE_HITL_RESOLVED"
    }


@pytest.mark.parametrize("batch, legs", [(True, [list(IDS)]), (False, [[i] for i in IDS])])
async def test_three_near_simultaneous_decisions_all_apply_in_pending_order(
    seeded_run, fake_agents, session_factory, monkeypatch, batch, legs
):
    monkeypatch.setattr(settings.inference, "batch_hitl_resume", batch)
    inference_run_manager.launch(seeded_run)
    await until(lambda: _paused_on_three(seeded_run))
    for interrupt_id in ("int-3", "int-1", "int-2"):
        outcome = inference_run_manager.request_resume(seeded_run, _decision(interrupt_id))
        assert outcome is ResumeOutcome.ACCEPTED
    run = await finished(seeded_run, session_factory)
    assert fake_agents.legs == legs
    assert run.streaming_status == "completed"
    assert list(_markers(run)) == list(IDS)


async def test_decisions_arriving_while_a_leg_streams_are_queued_not_overwritten(
    seeded_run, fake_agents, session_factory, monkeypatch
):
    monkeypatch.setattr(settings.inference, "batch_hitl_resume", True)
    inference_run_manager.launch(seeded_run)
    await until(lambda: _paused_on_three(seeded_run))
    inference_run_manager.request_resume(seeded_run, _decision("int-1"))
    await asyncio.wait_for(fake_agents.leg_running.wait(), timeout=5)
    inference_run_manager.request_resume(seeded_run, _decision("int-2"))
    inference_run_manager.request_resume(seeded_run, _decision("int-3", "reject", reason="no"))
    run = await finished(seeded_run, session_factory)
    assert fake_agents.legs == [["int-1"], ["int-2", "int-3"]]
    assert _markers(run)["int-3"]["decision"] == "reject"


async def test_cancel_while_paused_ends_the_run_and_drops_its_queue(
    seeded_run, fake_agents, session_factory
):
    fake_agents.leg_seconds = 0.3
    inference_run_manager.launch(seeded_run)
    await until(lambda: _paused_on_three(seeded_run))
    inference_run_manager.request_resume(seeded_run, _decision("int-1"))
    await asyncio.wait_for(fake_agents.leg_running.wait(), timeout=5)
    inference_run_manager.request_resume(seeded_run, _decision("int-2"))
    inference_run_manager.request_cancel(seeded_run)
    run = await finished(seeded_run, session_factory)
    assert run.streaming_status == "cancelled"
    for registry in (
        inference_run_manager._resume_queues,
        inference_run_manager._resume_events,
        inference_run_manager._runtimes,
        inference_run_manager._tasks,
    ):
        assert seeded_run not in registry


async def test_a_stale_id_in_a_batch_is_voided_and_the_rest_sent_again(
    seeded_run, fake_agents, session_factory, monkeypatch
):
    monkeypatch.setattr(settings.inference, "batch_hitl_resume", True)
    fake_agents.leg_seconds = 0.2
    inference_run_manager.launch(seeded_run)
    await until(lambda: _paused_on_three(seeded_run))
    inference_run_manager.request_resume(seeded_run, _decision("int-3"))
    await asyncio.wait_for(fake_agents.leg_running.wait(), timeout=5)
    fake_agents.pending.remove("int-1")  # gone on the agent's side
    inference_run_manager.request_resume(seeded_run, _decision("int-2"))
    inference_run_manager.request_resume(seeded_run, _decision("int-1"))
    run = await finished(seeded_run, session_factory)
    assert run.streaming_status == "completed"
    assert fake_agents.refused == [["int-1", "int-2"]]
    assert fake_agents.legs == [["int-3"], ["int-2"]]
    assert _markers(run)["int-1"]["decision"] == EXPIRED_DECISION


async def test_an_agent_paused_on_nothing_finishes_the_run(
    seeded_run, fake_agents, session_factory
):
    inference_run_manager.launch(seeded_run)
    await until(lambda: _paused_on_three(seeded_run))
    fake_agents.pending.clear()
    inference_run_manager.request_resume(seeded_run, _decision("int-2"))
    run = await finished(seeded_run, session_factory)
    assert run.streaming_status == "completed" and not run.error_message
    assert {m["decision"] for m in _markers(run).values()} == {EXPIRED_DECISION}


# --- what _do_resume sends --------------------------------------------------
async def _resume_once(payloads) -> str:
    config = {"run_config": {"configurable": {"thread_id": "thread-1"}}, "context": {"run_id": "r"}}
    return await inference_run_manager._do_resume(
        "r", {}, ir.InferenceRunRuntime(), "http://agents.test" + RESUME_PATH, config, payloads
    )


async def test_a_batch_goes_out_as_one_resume_keyed_by_interrupt(agents_service):
    bodies: list[dict] = []

    def reply(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content))
        return httpx.Response(200, content=b"", headers={"content-type": "text/event-stream"})

    agents_service.on("POST", RESUME_PATH, reply)
    assert await _resume_once([_decision("int-1"), _decision("int-2", "reject")]) == "completed"
    body = bodies[0]
    assert (body["interrupt_id"], body["thread_id"]) == ("int-1", "thread-1")
    assert [r["interrupt_id"] for r in body["resumes"]] == ["int-1", "int-2"]


async def test_a_stale_409_is_raised_for_recovery(agents_service):
    detail = {"stale_interrupt_ids": ["int-1"], "pending_interrupt_ids": ["int-2"]}
    agents_service.on("POST", RESUME_PATH, httpx.Response(409, json={"detail": detail}))
    with pytest.raises(StaleDecisions) as stale:
        await _resume_once([_decision("int-1"), _decision("int-2")])
    assert (stale.value.stale_ids, stale.value.pending_ids) == (["int-1"], ["int-2"])


async def test_any_other_409_fails_the_resume(agents_service, session_factory, monkeypatch):
    monkeypatch.setattr(ir, "SessionLocal", session_factory)
    agents_service.on("POST", RESUME_PATH, httpx.Response(409, json={"detail": "Something else."}))
    assert await _resume_once([_decision("int-1")]) == "failed"


# --- the /resume route ------------------------------------------------------
async def test_resume_route_404_409_and_dispatch(client, seeded_run, monkeypatch):
    url = f"/v1/inference/runs/{seeded_run}/resume"
    assert (
        await client.post("/v1/inference/runs/nope/resume", json={"decision": "approve"})
    ).status_code == 404
    not_paused = await client.post(url, json={"decision": "approve"})
    assert not_paused.status_code == 409 and "paused" in not_paused.json()["detail"].lower()
    assert (await client.post(url, json={"decision": "maybe"})).status_code == 422

    captured: dict[str, Any] = {}

    def fake_request_resume(run_id: str, payload: dict) -> ResumeOutcome:
        captured.update(run_id=run_id, payload=payload)
        return ResumeOutcome.ACCEPTED

    monkeypatch.setattr(inference_run_manager, "request_resume", fake_request_resume)
    ok = await client.post(
        url,
        json={
            "interruptId": "int-x",
            "decision": "reject",
            "reason": "no",
            "decisions": [{"decision": "approve"}, {"decision": "reject", "reason": "path"}],
        },
    )
    assert ok.status_code == 200
    assert captured["run_id"] == seeded_run
    assert captured["payload"]["interrupt_id"] == "int-x"
    assert captured["payload"]["decisions"] == [
        {"decision": "approve", "reason": None},
        {"decision": "reject", "reason": "path"},
    ]


async def test_another_browser_cannot_resume_the_run(other_client, seeded_run, monkeypatch):
    monkeypatch.setattr(
        inference_run_manager, "request_resume", lambda *_: pytest.fail("must not be reached")
    )
    response = await other_client.post(
        f"/v1/inference/runs/{seeded_run}/resume", json={"decision": "approve"}
    )
    assert response.status_code == 404
