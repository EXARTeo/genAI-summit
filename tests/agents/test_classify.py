"""The risk-classification agent (``classification/``, plan 02): no paid API is called.

Gemini is the scripted fake (``AGENTS_FAKE_LLM``), Iris an ``IrisClient`` over an
``httpx.MockTransport``, reg-memory either a duck-typed fake or the real client
over a ``MockTransport`` (the route test).
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
from classification import agent as classifier
from classification.agent import (
    ClassifierStep,
    ClassifyRequest,
    agent_option,
    classify,
    compare,
    iris_check,
    key_dates,
    render_brief,
)
from classification.claims import (
    MAX_CLAIMS,
    build_claims,
    claim_questions,
    claim_reasons,
    fold_answers,
    summarise,
)
from classification.prechecks import KbCache, prechecks
from classification.schemas import (
    Art63Assessment,
    CounterArgument,
    IrisCheck,
    IrisClaim,
    ProvisionCheck,
    RiskCitation,
    RiskProposal,
    Transparency,
)
from classification.tools import guidance_excerpt, regulation_tools
from classification.verify import classification_problems
from pipeline.clients import PipelineHTTPError, RegMemory
from pipeline.decision import IrisClient

from core.settings import settings
from utils import classify_runs

KB = "2026.11.15-1"
GUIDE = "INT.demo-art6-guideline-mirror.2-employment-recruitment-and-selection"

CV_PARSER = {
    "id": "SYS-004",
    "name": "CV Parser",
    "description": "Turns CVs into structured fields for recruiters. No ranking, no filtering.",
    "intended_purpose": "Parse job applications into a structured format with a trained model.",
    "affected_persons": "job applicants",
    "profiling": "no",
    "acquisition": "in_house",
    "features": [],
    "annex_i_product": None,
}
CV_SCREENER = {
    **CV_PARSER,
    "name": "CV Screener",
    "description": "A machine learning model that ranks job applicants for a shortlist.",
    "intended_purpose": "Shortlist candidates for recruiters.",
    "profiling": "yes",
}


def _node(pid: str, **extra: Any) -> dict[str, Any]:
    return {"id": pid, "title": pid, "text": f"Text of {pid}.", "kb_version": KB, **extra}


NODES: dict[str, dict[str, Any]] = {
    pid: _node(pid)
    for pid in (
        "AIA.3.1",
        "AIA.3.3",
        "AIA.3.4",
        "AIA.5",
        "AIA.5.1",
        "AIA.5.1.f",
        "AIA.6.1",
        "AIA.6.3.a",
        "AIA.6.3.b",
        "AIA.6.3.c",
        "AIA.6.3.d",
        "AIA.25.1",
        "AIA.49.2",
        "AIA.50",
        "AIA.50.1",
        "AIA.ANNEX_III.4.a",
    )
}
_BASIS = {"annex_iii": "2027-12-02", "annex_i": "2028-08-02"}
NODES["AIA.6.2"] = _node("AIA.6.2", valid_from="2027-12-02", valid_from_by_basis=_BASIS)
NODES["AIA.6.3"] = _node("AIA.6.3", children=["AIA.6.3.a", "AIA.6.3.b"])
NODES["AIA.6.4"] = _node(
    "AIA.6.4", valid_from="2027-12-02", valid_from_by_basis=_BASIS, amended_by=["OMNIBUS.1.12"]
)
NODES["AIA.ANNEX_III.4.a"]["valid_from"] = "2027-12-02"
NODES["AIA.49.2"]["valid_from"] = "2026-08-02"
GUIDANCE = {
    "id": GUIDE,
    "title": "Demo mirror: 2. Employment",
    "binding": False,
    "status": "draft",
    "relates_to": ["AIA.6.2", "AIA.6.3.a", "AIA.ANNEX_III.4.a"],
    "kb_version": KB,
    "text": "## 2. Employment\n\nA CV screening system that ranks applicants is high-risk.\n\n"
    "Example 12: a system that only converts CVs into a structured format performs a "
    "narrow procedural task under Article 6(3)(a).",
}


class FakeRegMemory:
    def __init__(self, *, down: bool = False) -> None:
        self.down = down
        self.calls: list[str] = []

    async def active_kb_version(self) -> str:
        if self.down:
            raise PipelineHTTPError("reg-memory", None, "ConnectError")
        return KB

    async def provision(self, pid: str, kb_version: str | None = None) -> dict[str, Any]:
        self.calls.append(pid)
        if pid not in NODES:
            raise PipelineHTTPError("reg-memory", 404, "missing")
        return NODES[pid]

    async def interpretation(self, iid: str, kb_version: str | None = None) -> dict[str, Any]:
        if iid != GUIDE:
            raise PipelineHTTPError("reg-memory", 404, "missing")
        return GUIDANCE

    async def interpretations(self, relates_to: str, kb_version: str | None = None):
        if relates_to in {"AIA.6.3", "AIA.ANNEX_III.4.a"}:
            return [{k: v for k, v in GUIDANCE.items() if k != "text"}]
        return []

    async def search(self, q: str, kb_version: str | None = None, limit: int = 10):
        return [{"id": "AIA.ANNEX_III.4.a", "label": "Annex III 4(a)", "snippet": "recruitment"}]


@pytest.fixture(autouse=True)
def _fake_llm():
    settings.gemini.fake_llm = True


def _iris(
    choice: str,
    p: float = 0.85,
    profiling: float = 0.1,
    status: int = 200,
    claims: dict[str, float] | None = None,
    seen: list[dict[str, Any]] | None = None,
) -> IrisClient:
    """Iris over a MockTransport: every ``noul`` claim gets 0.5 (never strong) unless a
    substring of its instructions is in ``claims``; the profiling claim gets ``profiling``."""

    def noul(instructions: str) -> float:
        for needle, value in (claims or {}).items():
            if needle in instructions:
                return value
        return profiling if "profiles natural persons" in instructions else 0.5

    def handler(request: httpx.Request) -> httpx.Response:
        if status != 200:
            return httpx.Response(status, json={"detail": "x"})
        questions = json.loads(request.content)["questions"]
        if seen is not None:
            seen.append(questions)
        options = list(questions["risk_class"]["criteria"])
        rest = (1 - p) / (len(options) - 1)
        probs = {o: (p if o == choice else rest) for o in options}
        answers: dict[str, Any] = {
            "risk_class": {"choice": choice, "confidence": p, "probabilities": probs}
        }
        for key, q in questions.items():
            if q["type"] == "noul":
                answers[key] = {"noul": noul(q["instructions"])}
        return httpx.Response(200, json={"answers": answers})

    return IrisClient(
        base_url="https://iris.test/v1",
        model="projects/p/models/iris-latest",
        api_key="k",
        transport=httpx.MockTransport(handler),
    )


def _proposal(**over: Any) -> RiskProposal:
    base: dict[str, Any] = {
        "risk_class": "high_risk",
        "route": "art6_2_annex_iii",
        "annex_basis": "Annex III 4(a)",
        "annex_basis_id": "AIA.ANNEX_III.4.a",
        "role": "provider",
        "role_reasoning": "Built in-house (Art. 3(3)).",
        "annex_iii_considered": [
            ProvisionCheck(provision_id="AIA.ANNEX_III.4.a", applies=True, why="recruitment")
        ],
        "art6_3": Art63Assessment(considered=True, profiling="yes", holds=False, why="ranks"),
        "reasoning": "Ranks applicants.",
        "counter_arguments": [CounterArgument(argument="x", would_change_to="minimal_risk")],
        "would_change_if": ["it stops ranking"],
        "confidence": 0.8,
        "citations": [RiskCitation(id="AIA.ANNEX_III.4.a"), RiskCitation(id="AIA.6.2")],
    }
    base.update(over)
    return RiskProposal(**base)


KNOWN = {**NODES, GUIDE: GUIDANCE}
PRE_CV = prechecks(CV_SCREENER, [])


# ---- pre-checks -----------------------------------------------------------------------------


def test_prechecks_cv_text_gives_annex_iii_4a_first():
    pre = prechecks(CV_PARSER, [{"path": "docs/system-specification.md"}])
    assert pre["annex_iii_candidates"][0]["provision"] == "AIA.ANNEX_III.4.a"
    assert {"cvs", "recruiters"} <= set(pre["annex_iii_candidates"][0]["matched"])
    assert pre["art5_flags"] == []
    assert pre["profiling"] == "no"
    assert pre["role_hint"] == "provider"
    assert pre["annex_i"] == {"flag": False, "product_law": None}
    assert pre["ai_system_doubt"] is False


def test_prechecks_emotion_of_employees_flags_art_5_1_f():
    card = {"description": "Emotion recognition of employees during video calls."}
    pre = prechecks(card, [])
    assert [f["provision"] for f in pre["art5_flags"]] == ["AIA.5.1.f"]
    assert pre["ai_system_doubt"] is True  # no learning / inference words


@pytest.mark.parametrize(
    ("acquisition", "role"),
    [
        ("in_house", "provider"),
        ("bought_as_is", "deployer"),
        ("as_is", "deployer"),
        ("bought_and_changed", "provider_by_art25"),
        ("rebranded", "provider_by_art25"),
    ],
)
def test_role_hint_from_acquisition(acquisition, role):
    assert prechecks({"acquisition": acquisition}, [])["role_hint"] == role


def test_profiling_yes_blocks_6_3_in_the_verifier():
    claim = _proposal(
        risk_class="minimal_risk",
        route="art6_3_exempt",
        annex_basis=None,
        annex_basis_id=None,
        art6_3=Art63Assessment(considered=True, condition="a", profiling="no", holds=True),
        next_steps=["Document the Art. 6(4) assessment"],
        citations=[RiskCitation(id="AIA.6.3"), RiskCitation(id="AIA.ANNEX_III.4.a")],
    )
    problems = classification_problems(claim, KNOWN, PRE_CV)  # PRE_CV: profiling yes
    assert "Art. 6(3) never holds when the system profiles people" in problems


# ---- verifier -------------------------------------------------------------------------------


def test_verifier_passes_a_consistent_high_risk_proposal():
    assert classification_problems(_proposal(), KNOWN, PRE_CV) == []


def test_verifier_unknown_citation():
    bad = _proposal(citations=[*_proposal().citations, RiskCitation(id="AIA.999")])
    assert "citation AIA.999 does not exist at the pinned kb_version" in classification_problems(
        bad, KNOWN, PRE_CV
    )


def test_verifier_high_risk_without_basis():
    problems = classification_problems(_proposal(annex_basis=None), KNOWN, PRE_CV)
    assert "high_risk needs annex_basis" in problems


def test_verifier_unaddressed_flag_and_candidate():
    pre = prechecks({"description": "emotion recognition of employees, recruitment"}, [])
    problems = classification_problems(_proposal(annex_iii_considered=[]), KNOWN, pre)
    assert any("AIA.5.1.f" in p and "art5_screening" in p for p in problems)
    assert any("AIA.ANNEX_III.4.a" in p and "annex_iii_considered" in p for p in problems)


def test_verifier_missing_counter_argument_and_would_change_if():
    problems = classification_problems(
        _proposal(counter_arguments=[], would_change_if=[]), KNOWN, PRE_CV
    )
    assert "give at least one counter_argument" in problems
    assert "give at least one would_change_if" in problems


def test_verifier_guidance_must_be_non_binding_draft():
    cites = [*_proposal().citations, RiskCitation(id=GUIDE, binding=True, status="final")]
    problems = classification_problems(_proposal(citations=cites), KNOWN, PRE_CV)
    assert f"guidance citation {GUIDE} must be binding: false" in problems
    assert f"guidance citation {GUIDE} is a draft: mark it status: draft" in problems


# ---- compare --------------------------------------------------------------------------------


def _check(choice: str, conf: float = 0.9, profiling: float = 0.1) -> IrisCheck:
    return IrisCheck(
        choice=choice, confidence=conf, profiling=profiling, agent_choice="high_risk_annex_iii"
    )


def test_compare_agree_is_not_needs_human():
    agreement, reasons = compare(_proposal(), _check("high_risk_annex_iii"), [], None, 0.6)
    assert agreement is True and reasons == []


def test_compare_disagree_low_confidence_or_no_iris_needs_human():
    agreement, reasons = compare(_proposal(), _check("minimal"), [], None, 0.6)
    assert agreement is False and "Iris chose minimal" in reasons[0]
    _, reasons = compare(_proposal(), _check("high_risk_annex_iii", conf=0.4), [], None, 0.6)
    assert any("Iris confidence 0.40" in r for r in reasons)
    _, reasons = compare(_proposal(confidence=0.3), _check("high_risk_annex_iii"), [], None, 0.6)
    assert any("agent confidence 0.30" in r for r in reasons)
    agreement, reasons = compare(_proposal(), None, [], "not_configured", 0.6)
    assert agreement is None
    assert reasons == ["independent check unavailable (not_configured)"]


def test_agent_option_maps_to_iris_choices():
    assert agent_option(_proposal()) == "high_risk_annex_iii"
    assert agent_option(_proposal(route="art6_1_annex_i")) == "high_risk_annex_i"
    exempt = _proposal(risk_class="minimal_risk", route="art6_3_exempt")
    assert agent_option(exempt) == "not_high_risk_6_3"
    assert agent_option(_proposal(risk_class="limited_risk", route="art50_only")) == (
        "transparency_only"
    )
    assert agent_option(_proposal(risk_class="prohibited", route="art5")) == "prohibited"


# ---- dates ----------------------------------------------------------------------------------


def test_key_dates_come_from_valid_from_at_the_kb():
    kb = KbCache(kb_version=KB, nodes=dict(NODES))
    dates = {d.provision_id: d for d in key_dates(_proposal(), kb)}
    assert dates["AIA.6.2"].date == "2027-12-02"
    assert dates["AIA.ANNEX_III.4.a"].date == "2027-12-02"
    exempt = _proposal(risk_class="minimal_risk", route="art6_3_exempt")
    dates = {d.provision_id: d for d in key_dates(exempt, kb)}
    assert dates["AIA.6.4"].amended_by == ["OMNIBUS.1.12"]
    assert dates["AIA.49.2"].date == "2026-08-02"


# ---- read_guidance --------------------------------------------------------------------------


def test_guidance_excerpt_windows_the_query_and_caps_length():
    filler = "\n\n".join(f"Paragraph {i} about something unrelated entirely." for i in range(400))
    text = filler + "\n\nExample 12: a CV parser is a narrow procedural task.\n\n" + filler
    excerpt, matched = guidance_excerpt(text, "narrow procedural CV", limit=500)
    assert excerpt.startswith("Example 12") and len(excerpt) <= 500
    assert matched == ["narrow", "procedural"]  # 'cv' is under 3 letters
    long = "word " * 5000
    excerpt, _ = guidance_excerpt(long, "nothing here")
    assert 0 < len(excerpt) <= 4_000


async def test_read_guidance_returns_binding_status_and_errors_as_text():
    kb = KbCache(kb_version=KB)
    tools = {t.name: t for t in regulation_tools(FakeRegMemory(), kb)}
    body = json.loads(
        await tools["read_guidance"].ainvoke({"interpretation_id": GUIDE, "query": "narrow task"})
    )
    assert body["binding"] is False and body["status"] == "draft" and body["kb_version"] == KB
    assert "Example 12" in body["excerpt"]
    assert kb.known(GUIDE)
    text = await tools["read_guidance"].ainvoke({"interpretation_id": "INT.nope", "query": "x"})
    assert text.startswith("Could not read INT.nope") and "404" in text
    hits = json.loads(await tools["search_regulation"].ainvoke({"query": "recruitment"}))
    assert hits[0]["id"] == "AIA.ANNEX_III.4.a"


# ---- the run (fake Gemini) ------------------------------------------------------------------


def _req(card: dict[str, Any], **kw: Any) -> ClassifyRequest:
    return ClassifyRequest(
        classification_id="CLS-SYS-004-20261115-1405", system_id="SYS-004", card=card, **kw
    )


async def test_cv_parser_is_6_3_a_and_needs_human_without_iris():
    result = await classify(_req(CV_PARSER), regmem=FakeRegMemory(), iris=None)
    assert (result.risk_class, result.route) == ("minimal_risk", "art6_3_exempt")
    assert result.art6_3.condition == "a" and result.art6_3.holds is True
    assert result.verifier_problems == []
    assert result.kb_version == KB
    guide = next(c for c in result.citations if c.id == GUIDE)
    assert (guide.binding, guide.status, guide.kb_version) == (False, "draft", KB)
    assert result.iris is None and result.decided_by == "gemini"
    assert result.needs_human is True
    assert result.needs_human_reasons == ["independent check unavailable (not_configured)"]
    assert {d.provision_id for d in result.key_dates} == {"AIA.6.4", "AIA.49.2"}


async def test_iris_agrees_then_disagrees():
    agree = _iris("not_high_risk_6_3")
    result = await classify(_req(CV_PARSER), regmem=FakeRegMemory(), iris=agree)
    assert result.agreement is True and result.needs_human is False
    assert result.decided_by == "gemini+iris"
    assert result.iris and result.iris.probabilities["not_high_risk_6_3"] == pytest.approx(0.85)
    result = await classify(
        _req(CV_PARSER), regmem=FakeRegMemory(), iris=_iris("high_risk_annex_iii")
    )
    assert result.agreement is False and result.needs_human is True
    assert "Iris chose high_risk_annex_iii" in result.needs_human_reasons[0]
    result = await classify(_req(CV_PARSER), regmem=FakeRegMemory(), iris=_iris("x", status=500))
    assert result.iris is None and "http_500" in result.needs_human_reasons[0]


async def test_cv_screener_is_high_risk_4a():
    result = await classify(_req(CV_SCREENER), regmem=FakeRegMemory(), iris=None)
    assert (result.risk_class, result.route) == ("high_risk", "art6_2_annex_iii")
    assert result.annex_basis == "Annex III 4(a)"
    assert result.verifier_problems == []
    assert next(d for d in result.key_dates if d.provision_id == "AIA.6.2").date == "2027-12-02"


async def test_verifier_problems_trigger_one_redo_then_needs_human(monkeypatch):
    briefs: list[dict[str, Any] | None] = []
    orig = ClassifierStep.run

    async def spy(self, brief, tools, *, feedback, fake, config=None):
        briefs.append(feedback)
        return await orig(
            self,
            brief,
            tools,
            feedback=feedback,
            fake=lambda: fake().model_copy(update={"counter_arguments": []}),
            config=config,
        )

    monkeypatch.setattr(ClassifierStep, "run", spy)
    result = await classify(
        _req(CV_PARSER, feedback={"source": "human", "reason": "It also ranks"}),
        regmem=FakeRegMemory(),
        iris=_iris("not_high_risk_6_3"),
    )
    assert briefs[0] == {"source": "human", "reason": "It also ranks"}
    assert briefs[1]["source"] == "verifier" and briefs[1]["human_reason"] == "It also ranks"
    assert result.verifier_problems == ["give at least one counter_argument"]
    assert result.needs_human is True


def test_human_feedback_is_rendered_in_the_brief():
    text = render_brief({"a": 1}, {"source": "human", "reason": "It also ranks"})
    assert "rejected the previous classification" in text and "It also ranks" in text
    assert "remember" not in text


def test_prompt_is_layered_with_precedence():
    from datetime import date

    prompt = classifier.compose_prompt(date(2026, 11, 15))
    order = [prompt.index(t) for t in ("<platform_rules>", "<agent_instructions>", "<defaults>")]
    assert order == sorted(order) and prompt.endswith("Sunday, 15 November 2026.")


# ---- the route ------------------------------------------------------------------------------


def _regmem_transport(down: bool = False) -> RegMemory:
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if down:
            return httpx.Response(503, json={"detail": "down"})
        if path == "/v1/releases":
            return httpx.Response(200, json={"active": KB, "items": []})
        if path.startswith("/v1/provisions/"):
            pid = path.rsplit("/", 1)[1]
            return httpx.Response(200, json=NODES[pid]) if pid in NODES else httpx.Response(404)
        if path == "/v1/interpretations":
            rel = request.url.params.get("relates_to")
            items = [GUIDANCE] if rel in {"AIA.6.3", "AIA.ANNEX_III.4.a"} else []
            return httpx.Response(200, json={"items": items})
        if path.startswith("/v1/interpretations/"):
            return httpx.Response(200, json=GUIDANCE)
        return httpx.Response(404)

    return RegMemory(client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))


BODY = {
    "classification_id": "CLS-SYS-004-20261115-1405",
    "kb_version": None,
    "card": CV_PARSER,
    "documents": [{"path": "docs/system-specification.md", "version": 1, "text": "Parser."}],
    "feedback": None,
    "trace": {"name": "classify:CLS-SYS-004-20261115-1405"},
}


async def test_route_classifies_end_to_end(client, internal_headers, monkeypatch):
    monkeypatch.setattr(classify_runs, "RegMemory", lambda: _regmem_transport())
    resp = await client.post("/systems/SYS-004/classify", json=BODY, headers=internal_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["risk_class"] == "minimal_risk" and body["route"] == "art6_3_exempt"
    assert body["classification_id"] == BODY["classification_id"]
    assert body["kb_version"] == KB and body["trace_id"]
    assert body["needs_human"] is True and body["iris"] is None
    assert {"key_dates", "prechecks", "citations", "counter_arguments"} <= set(body)


async def test_route_502_when_reg_memory_is_down(client, internal_headers, monkeypatch):
    monkeypatch.setattr(classify_runs, "RegMemory", lambda: _regmem_transport(down=True))
    resp = await client.post("/systems/SYS-004/classify", json=BODY, headers=internal_headers)
    assert resp.status_code == 502


async def test_route_needs_the_internal_secret(client):
    resp = await client.post("/systems/SYS-004/classify", json=BODY)
    assert resp.status_code in {401, 403}


def test_verifier_limited_risk_needs_a_declared_art_50_feature():
    """A 6(3)-exempt CV parser with no declared Art. 50 feature is minimal, not limited, risk."""
    pre = prechecks(CV_PARSER, [])
    assert pre["features"] == []
    limited = _proposal(
        risk_class="limited_risk",
        route="art6_3_exempt",
        annex_basis="Annex III 4(a)",
        annex_basis_id=None,
        art6_3=Art63Assessment(considered=True, condition="a", profiling="no", holds=True),
        citations=[RiskCitation(id="AIA.6.3"), RiskCitation(id="AIA.ANNEX_III.4.a")],
    )
    problems = classification_problems(limited, KNOWN, pre)
    assert any(p.startswith("limited_risk / art50_only needs an Art. 50 feature") for p in problems)
    declared = prechecks({**CV_PARSER, "features": ["chatbot"]}, [])
    assert not any(
        p.startswith("limited_risk") for p in classification_problems(limited, KNOWN, declared)
    )


# ---- Iris claims ----------------------------------------------------------------------------


def _rich_proposal() -> RiskProposal:
    return _proposal(
        annex_iii_considered=[
            ProvisionCheck(provision_id="AIA.ANNEX_III.4.b", applies=False, why="no"),
            ProvisionCheck(provision_id="AIA.ANNEX_III.4.a", applies=True, why="recruitment"),
        ],
        art5_screening=[ProvisionCheck(provision_id="AIA.5.1.f", applies=False, why="no")],
        art6_3=Art63Assessment(considered=True, condition="a", profiling="no", holds=False),
        transparency=Transparency(features=["chatbot"], provisions=["AIA.50.1"]),
        counter_arguments=[
            CounterArgument(argument="It only parses CVs", would_change_to="minimal_risk"),
            CounterArgument(argument="It is bought as is", would_change_to="deployer"),
        ],
    )


def test_claims_are_built_per_group_in_priority_order():
    pre = prechecks(CV_SCREENER, [])
    claims = build_claims(_rich_proposal(), pre, {"AIA.50.3": {}})
    by_key = {c.key: c for c in claims}
    assert [c.key for c in claims] == [
        "art6_3:condition",
        "art6_3:profiling",
        "annex_iii:AIA.ANNEX_III.4.a",
        "role",
        "art5:AIA.5.1.f",
        "art50:AIA.50.1",
        "art50:AIA.50.2",
        "art50:AIA.50.3",
        "annex_iii:AIA.ANNEX_III.4.b",
        "assumption:ai_system",
        "counter:1",
        "counter:2",
    ]
    cond = by_key["art6_3:condition"]
    assert cond.statement == "The Art. 6(3)(a) condition (narrow procedural task) holds"
    assert (cond.agent, cond.provision_id, cond.group) == (False, "AIA.6.3.a", "art6_3")
    assert by_key["art6_3:profiling"].agent is False
    assert (
        by_key["annex_iii:AIA.ANNEX_III.4.a"].statement == "Annex III 4(a) applies to this system"
    )
    assert by_key["annex_iii:AIA.ANNEX_III.4.b"].agent is False
    assert by_key["art5:AIA.5.1.f"].statement.endswith("Art. 5(1)(f)")
    assert by_key["art50:AIA.50.1"].agent is True and by_key["art50:AIA.50.2"].agent is False
    assert by_key["role"].agent is True and by_key["assumption:ai_system"].agent is True
    assert by_key["counter:1"].agent is False
    assert "It only parses CVs" in by_key["counter:1"].statement
    assert all(c.iris is None and c.agrees is None for c in claims)
    questions = claim_questions(claims)
    assert list(questions)[:2] == ["c01", "c02"] and len(questions) == len(claims)
    assert all(q["type"] == "noul" for q in questions.values())
    assert "[AIA.6.3.a]" in questions["c01"]["instructions"]


def test_claims_for_annex_i_and_6_3_exempt_and_the_cap():
    exempt = _proposal(
        risk_class="minimal_risk",
        route="art6_3_exempt",
        art6_3=Art63Assessment(considered=True, condition="a", profiling="no", holds=True),
    )
    keys = [c.key for c in build_claims(exempt, PRE_CV, {})]
    assert "assumption:no_ranking" in keys and "annex_i" not in keys
    annex_i = _proposal(route="art6_1_annex_i")
    claim = next(c for c in build_claims(annex_i, PRE_CV, {}) if c.key == "annex_i")
    assert claim.agent is True
    many = _proposal(
        annex_iii_considered=[
            ProvisionCheck(provision_id=f"AIA.ANNEX_III.{i}", applies=False, why="no")
            for i in range(1, 30)
        ]
    )
    claims = build_claims(many, PRE_CV, {})
    assert len(claims) == MAX_CLAIMS and claims[0].group == "art6_3"


def _claim(agent: bool) -> IrisClaim:
    return IrisClaim(key="role", group="role", statement="S", agent=agent)


@pytest.mark.parametrize(
    ("agent", "p", "agrees", "strong"),
    [
        (True, 0.9, True, False),
        (True, 0.5, True, False),
        (True, 0.4, False, False),
        (True, 0.12, False, True),
        (False, 0.1, True, False),
        (False, 0.6, False, False),
        (False, 0.8, False, True),
    ],
)
def test_claim_agreement_and_strong_disagreement(agent, p, agrees, strong):
    (claim,) = fold_answers([_claim(agent)], {"c01": {"noul": p}})
    assert (claim.iris, claim.agrees, claim.strong_disagreement) == (p, agrees, strong)
    assert claim_reasons([claim]) == ([f"Iris disagrees: S (P={p:.2f})"] if strong else [])


def test_summary_counts_checked_claims_only():
    answers = {"c01": {"noul": 0.9}, "c02": {"noul": 0.9}}
    claims = fold_answers([_claim(True), _claim(False), _claim(True)], answers)
    assert summarise(claims).model_dump() == {"checked": 2, "agree": 1, "disagree": 1}


async def test_iris_checks_every_claim_in_one_call():
    seen: list[dict[str, Any]] = []
    iris = _iris("not_high_risk_6_3", seen=seen)
    result = await classify(_req(CV_PARSER), regmem=FakeRegMemory(), iris=iris)
    assert len(seen) == 1
    claim_keys = [k for k in seen[0] if k != "risk_class"]
    assert claim_keys == [f"c{i:02d}" for i in range(1, len(result.iris_claims) + 1)]
    assert {c.group for c in result.iris_claims} >= {"art6_3", "annex_iii", "role", "assumption"}
    assert all(c.iris is not None for c in result.iris_claims)
    assert result.iris_summary.checked == len(result.iris_claims)
    assert result.iris and result.iris.profiling == pytest.approx(0.1)
    assert result.needs_human is False  # 0.5 everywhere: weak disagreements only


async def test_strong_claim_disagreement_needs_human():
    iris = _iris("not_high_risk_6_3", claims={"does not rank, score": 0.12})
    result = await classify(_req(CV_PARSER), regmem=FakeRegMemory(), iris=iris)
    assert result.agreement is True and result.needs_human is True
    assert result.needs_human_reasons == [
        "Iris disagrees: The system does not rank, score, filter or reject people (P=0.12)"
    ]
    claim = next(c for c in result.iris_claims if c.key == "assumption:no_ranking")
    assert claim.strong_disagreement is True and claim.agrees is False


async def test_iris_down_keeps_the_claims_unchecked():
    for iris in (None, _iris("x", status=500)):
        result = await classify(_req(CV_PARSER), regmem=FakeRegMemory(), iris=iris)
        assert result.iris_claims
        assert all(c.iris is None and c.agrees is None for c in result.iris_claims)
        assert result.iris_summary.model_dump() == {"checked": 0, "agree": 0, "disagree": 0}
        assert result.needs_human_reasons[0].startswith("independent check unavailable")
    check, failure, claims = await iris_check(
        None, {}, "minimal", [_claim(True)], trace_id=None, parent_id=None
    )
    assert check is None and failure == "not_configured" and claims == [_claim(True)]
