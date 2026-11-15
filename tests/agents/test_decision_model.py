"""The decision model (``pipeline/decision.py``): Oumi Iris first, Gemini (the fake) as fallback.

No network: Iris is an ``IrisClient`` over an ``httpx.MockTransport`` that
answers like ``POST https://inference.oumi.ai/v1/systemone`` (docs.oumi.ai,
decision models); Gemini is the scripted fake (``AGENTS_FAKE_LLM``).
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command
from pipeline.decision import DecisionModel, IrisClient
from pipeline.impact import ChangeJudge
from pipeline.scenario_review import SCENARIO_REVIEW, fake_review
from pipeline.schemas import ScenarioReview
from pipeline.steps import StepScope
from pipeline_fakes import (
    AUDIT_ID,
    SYSTEM_ID,
    FakeBackend,
    FakeRegMemory,
    build_graph,
    make_harness,
)

from core.settings import settings
from harness.observability import langfuse as lf
from schema.audits import ChangeJudgeIn
from utils.change_judge import judge_change

CONFIG = {"configurable": {"thread_id": "audit-AUD-1"}}
START = {"audit_id": AUDIT_ID, "system_id": SYSTEM_ID}
REVIEW_KEYS = {"model", "verdict", "rationale", "suggested_change", "confidence"}
SCOPE = StepScope(audit_id=AUDIT_ID, system_id=SYSTEM_ID, kb_version="kb", step="scenario_review")


@pytest.fixture(autouse=True)
def _fake_llm():
    settings.gemini.fake_llm = True
    settings.pipeline.max_auto_redos = 1
    settings.pipeline.max_redos = 3
    settings.pipeline.scenario_review_model = "iris"


def _choice(choice: str, options: list[str], p: float = 0.8) -> dict[str, Any]:
    rest = (1 - p) / (len(options) - 1)
    return {
        "type": "choice",
        "choice": choice,
        "confidence": p,
        "probabilities": {o: (p if o == choice else rest) for o in options},
    }


def iris_answering(
    verdict: str = "relevant",
    *,
    checks: dict[str, float] | None = None,
    status: int = 200,
    body: Any = None,
    seen: list[httpx.Request] | None = None,
) -> IrisClient:
    """An IrisClient whose endpoint answers every question set with ``verdict``."""

    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        if body is not None or status != 200:
            return httpx.Response(status, json=body if body is not None else {"detail": "x"})
        sent = json.loads(request.content)
        answers: dict[str, Any] = {}
        for name, q in sent["questions"].items():
            if q["type"] == "choice":
                options = list(q["criteria"])
                pick = verdict if verdict in options else options[0]
                answers[name] = _choice(pick, options)
            else:
                answers[name] = {"type": "noul", "noul": (checks or {}).get(name, 0.9)}
        return httpx.Response(
            200, json={"model": sent["model"], "answers": answers, "usage": {"inputTokens": 1}}
        )

    return IrisClient(
        base_url="https://inference.oumi.ai/v1",
        model="projects/P-1/models/iris-latest",
        api_key="test-oumi-key",
        transport=httpx.MockTransport(handler),
    )


BRIEF = {
    "system": {"id": SYSTEM_ID, "risk_class": "high_risk"},
    "plugin": {"id": "SYS-001.cv-ranker"},
    "model_profile": {"proxies": {"postcode_region": {"proxy_for": ["nationality"]}}},
    "applicable_requirements": [{"id": "REQ.A", "testability": "model_and_data_test"}],
    "scenario": {
        "id": "SC-01",
        "requirement": "REQ.A",
        "template": "counterfactual_twins",
        "protected": ["nationality"],
        "proxies": ["postcode_region"],
        "data_needs": {"twin_modes": ["attribute_only", "causal", "proxy_only"]},
        "metric": "flip_rate",
    },
}


# ----------------------------------------------------------------- the model
async def test_iris_success_maps_choice_and_checks_into_the_review():
    seen: list[httpx.Request] = []
    iris = iris_answering("needs_change", checks={"covers_proxies": 0.2}, seen=seen)
    decision = await DecisionModel("iris", iris=iris).decide(
        SCENARIO_REVIEW, BRIEF, ScenarioReview, SCOPE
    )
    assert decision.model == "iris" and not decision.fallback
    review = decision.result
    assert review.verdict == "needs_change" and review.confidence == pytest.approx(0.8)
    assert "covers_proxies 0.20" in review.rationale
    assert review.suggested_change and "proxy_only" in review.suggested_change
    (request,) = seen
    assert str(request.url) == "https://inference.oumi.ai/v1/systemone"
    assert request.headers["X-API-Key"] == "test-oumi-key"
    sent = json.loads(request.content)
    assert sent["model"] == "projects/P-1/models/iris-latest"
    assert sent["questions"]["verdict"]["type"] == "choice"
    assert set(sent["questions"]["verdict"]["criteria"]) == {
        "relevant",
        "needs_change",
        "not_relevant",
    }
    assert sent["state"]["scenario"]["id"] == "SC-01"


async def test_iris_http_failure_falls_back_to_gemini():
    decision = await DecisionModel("iris", iris=iris_answering(status=503)).decide(
        SCENARIO_REVIEW, BRIEF, ScenarioReview, SCOPE
    )
    assert decision.model == "gemini" and decision.fallback
    assert decision.failure == "http_503"
    assert decision.result == fake_review(BRIEF)


@pytest.mark.parametrize(
    "body",
    [
        {"answers": {"verdict": {"type": "choice", "choice": "maybe"}}},  # not an option
        {"answers": {}},  # questions unanswered
        {"no_answers": True},
        ["not", "an", "object"],
    ],
)
async def test_a_malformed_iris_answer_falls_back(body):
    decision = await DecisionModel("iris", iris=iris_answering(body=body)).decide(
        SCENARIO_REVIEW, BRIEF, ScenarioReview, SCOPE
    )
    assert decision.model == "gemini" and decision.fallback and decision.failure


async def test_unconfigured_iris_falls_back_without_a_call():
    seen: list[httpx.Request] = []
    iris = iris_answering(seen=seen)
    iris.model = ""
    decision = await DecisionModel("iris", iris=iris).decide(
        SCENARIO_REVIEW, BRIEF, ScenarioReview, SCOPE
    )
    assert decision.failure == "not_configured" and not seen


async def test_gemini_preferred_never_calls_iris():
    seen: list[httpx.Request] = []
    decision = await DecisionModel("gemini", iris=iris_answering(seen=seen)).decide(
        SCENARIO_REVIEW, BRIEF, ScenarioReview, SCOPE
    )
    assert decision.model == "gemini" and not decision.fallback and not seen


def test_fake_review_flags_unknown_requirements_and_missing_proxies():
    assert fake_review(BRIEF).verdict == "relevant"
    unknown = {**BRIEF, "scenario": {**BRIEF["scenario"], "requirement": "REQ.Z"}}
    assert fake_review(unknown).verdict == "not_relevant"
    no_proxy = {**BRIEF, "scenario": {**BRIEF["scenario"], "proxies": []}}
    review = fake_review(no_proxy)
    assert review.verdict == "needs_change" and "postcode_region" in review.suggested_change


class _Span:
    def __init__(self, sink: list) -> None:
        self.sink = sink

    def update(self, **kw):
        self.sink.append(("update", kw))

    def end(self):
        self.sink.append(("end", {}))


class _Client:
    def __init__(self, fail: bool = False) -> None:
        self.calls: list = []
        self.fail = fail

    def start_observation(self, **kw):
        if self.fail:
            raise RuntimeError("langfuse down")
        self.calls.append(("start", kw))
        return _Span(self.calls)


async def test_each_decision_is_one_langfuse_span_in_the_audit_trace(monkeypatch):
    client = _Client()
    monkeypatch.setattr(lf, "_client", client)
    await DecisionModel("iris", iris=iris_answering(), trace_id="b" * 32).decide(
        SCENARIO_REVIEW, BRIEF, ScenarioReview, SCOPE
    )
    (start, update, end) = client.calls
    assert start[1]["name"] == "iris.decide"
    assert start[1]["trace_context"] == {"trace_id": "b" * 32}
    meta = update[1]["metadata"]
    assert meta["model"] == "iris" and meta["verdict"] == "relevant"
    assert meta["fallback"] is False and isinstance(meta["latency_ms"], int)
    assert end[0] == "end"


async def test_a_failing_langfuse_never_breaks_a_decision(monkeypatch):
    monkeypatch.setattr(lf, "_client", _Client(fail=True))
    decision = await DecisionModel("iris", iris=iris_answering()).decide(
        SCENARIO_REVIEW, BRIEF, ScenarioReview, SCOPE
    )
    assert decision.model == "iris"


# -------------------------------------------------------------- the pipeline
async def _pending(graph) -> Any:
    snapshot = await graph.aget_state(CONFIG)
    assert snapshot.interrupts, f"not paused; next={snapshot.next}"
    return snapshot.interrupts[0]


def _latest(h, kind: str) -> dict[str, Any]:
    return [a for a in h.backend.artifacts if a["kind"] == kind][-1]["data"]


async def test_iris_reviews_are_attached_to_every_scenario():
    h = make_harness()
    h.deps.iris = iris_answering("relevant")
    graph = build_graph(h, InMemorySaver())
    await graph.ainvoke(START, CONFIG)
    gate = await _pending(graph)
    scenarios = _latest(h, "scenarios")["scenarios"]
    assert scenarios
    for sc in scenarios:
        assert set(sc["review"]) == REVIEW_KEYS
        assert sc["review"]["model"] == "iris" and sc["review"]["verdict"] == "relevant"
    # The gate reviews the reviewed version, and its summary carries each verdict.
    assert gate.value["artifact_ids"]["scenarios"] == h.backend.artifacts[-2]["id"]
    assert {s["review"] for s in gate.value["summary"]["scenarios"]} == {"relevant"}
    analysis = _latest(h, "scenario_analysis")
    assert analysis["verifier"]["action"] == "next"
    assert set(analysis["review"]["by"].values()) == {"iris"}


async def test_needs_change_goes_back_to_plan_scenarios_once():
    h = make_harness()
    h.deps.iris = iris_answering("needs_change", checks={"metric_fits": 0.1})
    graph = build_graph(h, InMemorySaver())
    await graph.ainvoke(START, CONFIG)
    assert (await _pending(graph)).value["gate"] == "scenarios"
    actions = [
        a["data"]["verifier"]["action"]
        for a in h.backend.artifacts
        if a["kind"] == "scenario_analysis"
    ]
    assert actions == ["redo", "next"]
    state = (await graph.aget_state(CONFIG)).values
    feedback = state["feedback"]["plan_scenarios"]
    assert feedback["source"] == "verifier"
    assert feedback["check"] == "decision-model scenario review"
    assert feedback["scenario_reviews"][0]["suggested_change"].startswith("Pick a metric")
    # Reviews still attached for the human at the gate.
    assert all(sc["review"]["verdict"] == "needs_change" for sc in state["scenarios"]["scenarios"])


async def test_not_relevant_is_flagged_for_the_human_without_a_redo():
    h = make_harness()
    h.deps.iris = iris_answering("not_relevant")
    graph = build_graph(h, InMemorySaver())
    await graph.ainvoke(START, CONFIG)
    gate = await _pending(graph)
    analysis = _latest(h, "scenario_analysis")
    ids = [sc["id"] for sc in _latest(h, "scenarios")["scenarios"]]
    assert analysis["verifier"]["action"] == "next"
    assert analysis["verifier"]["flagged"] == sorted(ids)
    assert gate.value["summary"]["flagged"] == ids
    # The human still decides: approving goes on to the datasets gate.
    await graph.ainvoke(Command(resume={gate.id: {"decision": "approved"}}), CONFIG)
    assert (await _pending(graph)).value["gate"] == "datasets"


async def test_review_off_attaches_nothing():
    settings.pipeline.scenario_review_model = "off"
    h = make_harness()
    graph = build_graph(h, InMemorySaver())
    await graph.ainvoke(START, CONFIG)
    assert h.backend.kinds().count("scenarios") == 1
    assert all("review" not in sc for sc in _latest(h, "scenarios")["scenarios"])


# ----------------------------------------------------------- the change judge
CHANGE = {
    "id": "RC-1",
    "from_kb_version": "2026.11.14-1",
    "to_kb_version": "2026.11.15-1",
    "change_types": ["substantive"],
    "provisions": [{"id": "AIA.10.2.f", "change": "modified"}],
    "impacted_requirements": [{"requirement_id": "REQ.AIA.10.2.f.bias-examination"}],
}
SYSTEMS = [
    {
        "system_id": "SYS-001",
        "audit_id": "AUD-1",
        "findings": [
            {
                "id": "F-01",
                "requirement": "REQ.AIA.10.2.f.bias-examination",
                "citations": [{"provision_id": "AIA.10.2.f"}],
            }
        ],
        "tests": [],
    }
]


class _Impact:
    def __init__(self) -> None:
        self.stored: list = []

    async def impact_index(self):
        return SYSTEMS

    async def store_judgement(self, change_id, affected, decided_by):
        self.stored.append((change_id, affected, decided_by))

    async def start_audit(self, system_id, data):
        return {"id": f"AUD-new-{system_id}"}


@pytest.mark.parametrize(("status", "decided_by"), [(200, "iris"), (500, "gemini")])
async def test_the_change_judge_runs_through_the_decision_model(status, decided_by):
    backend, impact = FakeBackend(), _Impact()
    judge = ChangeJudge(DecisionModel("iris", iris=iris_answering("rerun_tests", status=status)))
    out = await judge_change(
        CHANGE["id"],
        ChangeJudgeIn(change=CHANGE),
        regmem=FakeRegMemory(),  # type: ignore[arg-type]
        backend=impact,  # type: ignore[arg-type]
        model=judge,
        audit_backend=lambda aid: backend,  # type: ignore[arg-type,return-value]
        spawn=lambda coro: coro.close(),
    )
    (judgement,) = out.judgements
    assert judgement.decision == "rerun_tests" and judgement.decided_by == decided_by
    assert judgement.affected_findings == ["F-01"]
    (art,) = [a for a in backend.artifacts if a["kind"] == "change_judgement"]
    assert art["data"]["decided_by"] == decided_by
    assert art["data"]["decision_fallback"] is (decided_by == "gemini")
    assert impact.stored[0][2] == decided_by
    if decided_by == "iris":
        assert judgement.rationale.startswith("Iris: rerun_tests")
        assert "runner-up" in judgement.strongest_counter_argument
