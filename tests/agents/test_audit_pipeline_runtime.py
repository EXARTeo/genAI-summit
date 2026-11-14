"""Gemini provider, step runner, AG-UI stream, the /audits routes and the change judge."""

from __future__ import annotations

import json
from typing import Any

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from pipeline import fakes
from pipeline.agent import AuditPipelineAgent
from pipeline.impact import IrisDecisionModel, impact_index
from pipeline.prompting import compose_step_prompt, render_brief
from pipeline.schemas import ChangeJudgement, Finding, ScenarioPlan
from pipeline.steps import StepRunner
from pipeline.verify import evidence_problems, parse_spec
from pipeline_fakes import AUDIT_ID, SYSTEM_ID, FakeBackend, FakeRegMemory, make_harness
from pydantic import SecretStr, ValidationError

from core.settings import settings
from harness.models.fake import ScriptedChatModel, tool_call_message
from harness.models.gemini import (
    ModelNotConfiguredError,
    build_chat_model,
    ensure_specs_configured,
    model_name,
)
from schema.audits import ChangeJudgeIn
from utils import audit_runs
from utils.change_judge import judge_change


@pytest.fixture(autouse=True)
def _settings():
    settings.gemini.fake_llm = False
    settings.api_keys.google = SecretStr("")
    settings.gemini.model = "gemini-3.5-flash-lite"
    settings.gemini.reasoning_model = ""


# ------------------------------------------------------------------ provider
def test_no_key_is_a_clear_error_never_a_crash():
    with pytest.raises(ModelNotConfiguredError) as err:
        build_chat_model()
    assert "GOOGLE_API_KEY" in err.value.public_message
    with pytest.raises(ModelNotConfiguredError):
        ensure_specs_configured(["google_genai:gemini-3.5-flash-lite"])
    ensure_specs_configured(["openai:gpt-4o"])  # not ours to check


def test_gemini_model_roles():
    settings.api_keys.google = SecretStr("test-google-key")
    settings.gemini.reasoning_model = "gemini-3.5-pro"
    model = build_chat_model("default")
    assert type(model).__name__ == "ChatGoogleGenerativeAI"
    assert model.model.endswith("gemini-3.5-flash-lite")
    assert model_name("reasoning") == "gemini-3.5-pro"
    settings.gemini.reasoning_model = ""
    assert model_name("reasoning") == "gemini-3.5-flash-lite"


async def test_the_real_path_uses_the_step_role_and_validates_the_result():
    roles: list[str] = []
    payload = fakes.critic(
        {"findings": [{"id": "F-01", "verdict": "inconclusive", "confidence": 0.5}]}
    )

    def factory(role: str) -> ScriptedChatModel:
        roles.append(role)
        return ScriptedChatModel(
            script=[
                tool_call_message("CriticReport", {"reviews": [{"finding_id": "F-01"}]}),  # invalid
                tool_call_message("CriticReport", payload.model_dump(mode="json")),
            ]
        )

    h = make_harness(steps=StepRunner(model_factory=factory))
    pipeline_scope = __import__("pipeline.steps", fromlist=["StepScope"]).StepScope(
        audit_id=AUDIT_ID, system_id=SYSTEM_ID, kb_version="kb", step="critic"
    )
    result = await h.deps.steps.run("critic", {"findings": []}, pipeline_scope)
    assert roles == ["reasoning"]
    assert result.reviews[0].call == "weakened"  # type: ignore[attr-defined]


def test_prompts_are_layered_short_and_state_precedence():
    prompt = compose_step_prompt(
        "plan_scenarios", memory_index="- lesson", today=__import__("datetime").date(2026, 11, 14)
    )
    order = [
        prompt.index(tag)
        for tag in (
            "<platform_rules>",
            "<step_instructions>",
            "<platform_defaults>",
            "<system_memory>",
            "Today is",
        )
    ]
    assert order == sorted(order)
    assert "never overrides" in prompt and "not the AI Act's" in prompt
    for step in ("plan_scenarios", "draft_spec", "analyse", "critic", "report", "change_judge"):
        body = compose_step_prompt(
            step, memory_index=None, today=__import__("datetime").date(2026, 11, 14)
        )
        step_block = body.split("<step_instructions>")[1].split("</step_instructions>")[0]
        assert len(step_block.split()) < 260, step
    brief = render_brief("draft_spec", {"a": 1}, {"source": "human", "reason": "ages wrong"})
    assert "remember" in brief and "ages wrong" in brief


# ------------------------------------------------------------- schemas, verify
def test_result_schemas_reject_bad_values():
    with pytest.raises(ValidationError):
        Finding(id="F", requirement="R", title="t", verdict="maybe", confidence=0.5, reasoning="r")
    with pytest.raises(ValidationError):
        Finding(
            id="F",
            requirement="R",
            title="t",
            verdict="inconclusive",
            confidence=1.5,
            reasoning="r",
        )
    with pytest.raises(ValidationError):
        ScenarioPlan(target="x", scenarios=[])
    with pytest.raises(ValidationError):
        ChangeJudgement(
            decision="panic", rationale="", strongest_counter_argument="", confidence=0.1
        )


def test_evidence_must_match_the_test_results():
    results = {"tests": [{"id": "T-01", "value": 0.11, "mlflow_run_id": "run-1"}]}
    good = [
        {
            "id": "F-01",
            "citations": [{"provision_id": "AIA.10.2.f"}],
            "evidence": [{"test_id": "T-01", "value": 0.11, "mlflow_run_id": "run-1"}],
        }
    ]
    assert evidence_problems(good, results) == []
    bad = [
        {
            "id": "F-01",
            "citations": [],
            "evidence": [
                {"test_id": "T-01", "value": 0.2, "mlflow_run_id": "run-9"},
                {"test_id": "T-09"},
            ],
        }
    ]
    problems = evidence_problems(bad, results)
    assert len(problems) == 4


def test_spec_parse_flags_unknown_keys():
    spec, problems = parse_spec("version: 1\nname: x\ndictionary: d.yaml\nn: 10\nbogus: 1\n")
    assert spec and problems == ["unknown top-level key 'bogus'"]
    assert parse_spec("[")[0] is None


# ------------------------------------------------------------ AG-UI + routes
def _agent(h, **context: Any) -> AuditPipelineAgent:
    agent = AuditPipelineAgent(
        config={
            "run_config": {"configurable": {"thread_id": f"audit-{AUDIT_ID}"}},
            "context": {
                "client_id": "c",
                "conversation_id": "x",
                "system_id": SYSTEM_ID,
                "audit_id": AUDIT_ID,
                **context,
            },
        },
        deps=h.deps,
    )
    agent.memory_saver = InMemorySaver()
    return agent


async def _frames(agent, command=None) -> list[dict[str, Any]]:
    out = []
    async for frame in agent.astream({}, command=command):
        text = frame.decode() if isinstance(frame, bytes) else frame
        if text.startswith("data: "):
            out.append(json.loads(text[6:]))
    return out


async def test_the_agent_streams_steps_and_the_gate_as_ag_ui():
    settings.gemini.fake_llm = True
    agent = _agent(make_harness())
    events = await _frames(agent)
    steps = [e["stepName"] for e in events if e["type"] == "STEP_STARTED"]
    assert steps[:3] == ["load_context", "profile_model", "find_public_data"]
    hitl = [e for e in events if e.get("name") == "HITL_INTERRUPT"]
    assert hitl and hitl[-1]["value"]["interrupt"]["value"]["gate"] == "scenarios"
    assert any(e.get("name") == "AUDIT_ARTIFACT" for e in events)


async def test_no_key_streams_one_run_error_with_the_fix():
    events = await _frames(_agent(make_harness()))
    assert [e["type"] for e in events] == ["RUN_ERROR"]
    assert "GOOGLE_API_KEY" in events[0]["message"]


async def test_missing_sandbox_fails_with_a_public_message():
    settings.gemini.fake_llm = True
    h = make_harness()
    h.sandbox.available = False
    events = await _frames(_agent(h))
    assert events[-1]["type"] == "RUN_ERROR"
    assert "sandbox" in events[-1]["message"].lower()


def test_the_pipeline_needs_a_system_and_an_audit():
    with pytest.raises(ValueError):
        AuditPipelineAgent(config={"context": {"client_id": "c", "conversation_id": "x"}})


async def test_run_and_resume_routes(client, internal_headers, monkeypatch):
    settings.gemini.fake_llm = True
    h = make_harness()
    saver = InMemorySaver()

    def factory(config):
        agent = AuditPipelineAgent(config=config, deps=h.deps)
        agent.memory_saver = saver
        return agent

    audit_runs.set_agent_factory(factory)
    try:
        res = await client.post(
            f"/audits/{AUDIT_ID}/run", json={"system_id": SYSTEM_ID}, headers=internal_headers
        )
        assert res.status_code == 202 and res.json()["status"] == "started"
        await audit_runs.wait_for(AUDIT_ID)
        state = await client.get(
            f"/audits/{AUDIT_ID}/state", params={"system_id": SYSTEM_ID}, headers=internal_headers
        )
        assert state.json()["pending_gate"]["gate"] == "scenarios"
        again = await client.post(
            f"/audits/{AUDIT_ID}/run", json={"system_id": SYSTEM_ID}, headers=internal_headers
        )
        assert again.status_code == 409
        wrong = await client.post(
            f"/audits/{AUDIT_ID}/resume",
            json={"system_id": SYSTEM_ID, "gate": "datasets", "decision": "approved"},
            headers=internal_headers,
        )
        assert wrong.status_code == 409
        ok = await client.post(
            f"/audits/{AUDIT_ID}/resume",
            json={
                "system_id": SYSTEM_ID,
                "gate": "scenarios",
                "decision": "approved",
                "reasonCategory": "other",
            },
            headers=internal_headers,
        )
        assert ok.status_code == 202
        await audit_runs.wait_for(AUDIT_ID)
        state = await client.get(
            f"/audits/{AUDIT_ID}/state", params={"system_id": SYSTEM_ID}, headers=internal_headers
        )
        assert state.json()["pending_gate"]["gate"] == "datasets"
        assert (
            await client.post(f"/audits/{AUDIT_ID}/run", json={"system_id": SYSTEM_ID})
        ).status_code == 403
    finally:
        audit_runs.set_agent_factory(None)


# --------------------------------------------------------------- change judge
CHANGE = {
    "id": "RC-2026.11.15-1",
    "from_kb_version": "2026.11.14-1",
    "to_kb_version": "2026.11.15-1",
    "change_types": {"substantive": 1},
    "impacted_requirements": [
        {"requirement_id": "REQ.AIA.10.2.f.bias-examination", "via": ["AIA.10.2.f"]}
    ],
    "provisions": [
        {"id": "AIA.10.2.f", "kind": "provision", "change": "changed", "relates_to": []}
    ],
    "interpretations": [],
}
SYSTEMS = [
    {
        "system_id": "SYS-001",
        "audit_id": "AUD-1",
        "kb_version": "2026.11.14-1",
        "findings": [
            {
                "id": "F-01",
                "requirement": "REQ.AIA.10.2.f.bias-examination",
                "verdict": "indicates_gap",
                "citations": [{"provision_id": "AIA.10.2.f"}],
            }
        ],
        "tests": [],
    },
    {
        "system_id": "SYS-002",
        "audit_id": "AUD-2",
        "findings": [
            {
                "id": "F-01",
                "requirement": "REQ.AIA.15.1.x",
                "citations": [{"provision_id": "AIA.15.1"}],
            }
        ],
    },
    {"system_id": "SYS-003", "audit_id": None, "requirements": ["REQ.AIA.10.2.f.bias-examination"]},
]


def test_impact_index_finds_systems_through_requirements_and_citations():
    affected = {a.system_id: a for a in impact_index(CHANGE, SYSTEMS)}
    assert set(affected) == {"SYS-001", "SYS-003"}
    assert affected["SYS-001"].via_provisions == ["AIA.10.2.f"]


class _Impact:
    def __init__(self) -> None:
        self.started: list[tuple[str, dict]] = []
        self.stored: list[tuple[str, list, str]] = []

    async def store_judgement(self, change_id, affected, decided_by):
        self.stored.append((change_id, affected, decided_by))

    async def impact_index(self):
        return SYSTEMS

    async def start_audit(self, system_id, data):
        self.started.append((system_id, data))
        return {"id": f"AUD-new-{system_id}"}


async def test_change_judge_writes_artifacts_and_triggers_reruns():
    settings.gemini.fake_llm = True
    backend, impact = FakeBackend(), _Impact()
    out = await judge_change(
        CHANGE["id"],
        ChangeJudgeIn(change=CHANGE, rerun=True),
        regmem=FakeRegMemory(),  # type: ignore[arg-type]
        backend=impact,  # type: ignore[arg-type]
        audit_backend=lambda aid: backend,  # type: ignore[arg-type,return-value]
    )
    by_system = {j.system_id: j for j in out.judgements}
    assert by_system["SYS-001"].decision == "rerun_tests"
    assert by_system["SYS-001"].affected_findings == ["F-01"]
    assert by_system["SYS-003"].decision == "new_tests_needed"
    assert by_system["SYS-001"].rerun_audit_id == "AUD-new-SYS-001"
    (art,) = backend.artifacts
    assert art["kind"] == "change_judgement" and art["name"] == CHANGE["id"]
    assert art["data"]["to_kb_version"] == "2026.11.15-1"
    assert impact.started[0][1]["trigger"] == f"regchange:{CHANGE['id']}"
    ((change_id, rows, decided_by),) = impact.stored
    assert change_id == CHANGE["id"] and decided_by == "gemini"
    row = next(r for r in rows if r["systemId"] == "SYS-001")
    assert row["decision"] == "rerun_tests" and row["rerunAuditId"] == "AUD-new-SYS-001"
    assert row["path"] == ["REQ.AIA.10.2.f.bias-examination", "AIA.10.2.f"]


async def test_iris_falls_back_to_gemini_without_a_key():
    class _Gemini:
        name = "gemini"
        calls = 0

        async def judge(self, brief, scope):
            self.calls += 1
            return fakes.change_judge(brief)

    gemini = _Gemini()
    iris = IrisDecisionModel(fallback=gemini)
    result = await iris.judge({"impacted_requirements": []}, None)  # type: ignore[arg-type]
    assert result.decision == "no_impact" and gemini.calls == 1
