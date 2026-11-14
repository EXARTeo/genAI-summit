"""The audit pipeline (``pipeline/``): order, gates, rejection loops, verifiers, artifacts.

The graph runs for real (LangGraph + deepagents step agents) with the scripted
fake model (``AGENTS_FAKE_LLM``), an in-memory checkpointer and in-memory
backend / reg-memory / sandbox / memory stand-ins (``pipeline_fakes.py``).
"""

from __future__ import annotations

from typing import Any

import pytest
import yaml
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command
from pipeline.clients import ExecResult
from pipeline.graph import StepFailed, annex_basis, normalise_decision
from pipeline_fakes import AUDIT_ID, SYSTEM_ID, FakeSandbox, build_graph, make_harness

from core.settings import settings

CONFIG = {"configurable": {"thread_id": "audit-AUD-1"}}
START = {"audit_id": AUDIT_ID, "system_id": SYSTEM_ID}


@pytest.fixture(autouse=True)
def _fake_llm():
    settings.gemini.fake_llm = True
    settings.pipeline.max_auto_redos = 1
    settings.pipeline.max_redos = 3


async def _pending(graph) -> Any:
    snapshot = await graph.aget_state(CONFIG)
    assert snapshot.interrupts, f"not paused; next={snapshot.next}"
    return snapshot.interrupts[0]


async def _answer(graph, decision: dict[str, Any]) -> None:
    pending = await _pending(graph)
    await graph.ainvoke(Command(resume={pending.id: decision}), CONFIG)


async def test_runs_in_order_pauses_at_both_gates_and_finishes():
    h = make_harness()
    graph = build_graph(h, InMemorySaver())

    await graph.ainvoke(START, CONFIG)
    gate = await _pending(graph)
    assert gate.value["gate"] == "scenarios"
    assert gate.value["artifact_ids"]["scenarios"]
    assert h.backend.stages() == [
        "load_context",
        "profile_model",
        "find_public_data",
        "plan_scenarios",
        "analyse_scenarios",
        "approve_scenarios",
    ]
    assert h.backend.patches[-1]["status"] == "waiting_approval"
    assert h.backend.kinds() == ["context", "model_profile", "scenarios", "scenario_analysis"]

    await _answer(graph, {"decision": "approved"})
    assert (await _pending(graph)).value["gate"] == "datasets"
    assert h.backend.kinds()[-3:] == ["generation_spec", "dataset", "dataset_analysis"]

    await _answer(graph, {"decision": "approved"})
    snapshot = await graph.aget_state(CONFIG)
    assert not snapshot.next and not snapshot.interrupts
    kinds = h.backend.kinds()
    assert kinds[kinds.index("dataset_analysis") + 1 :][:2] == ["test_plan", "test_result"]
    assert "finding" in kinds and kinds[-2:] == ["critic", "report"]
    assert h.backend.patches[-1]["status"] == "done"
    # Every sandbox step really ran synthkit, in order.
    subcommands = [c.split("synthkit ")[-1].split()[0] for c in h.sandbox.commands]
    assert subcommands == ["profile", "scenarios-check", "generate", "analyze", "run-tests"]
    # Langfuse trace per stage recorded on the audit.
    assert h.backend.patches[0]["data"]["stageTraces"]["load_context"] == "a" * 32


async def test_context_comes_from_the_system_folder_and_reg_memory():
    h = make_harness()
    graph = build_graph(h, InMemorySaver())
    await graph.ainvoke(START, CONFIG)
    params = h.regmem.calls[0][1]
    assert params["basis"] == "AIA.ANNEX_III.4.a" and params["risk_class"] == "high"
    context = h.backend.artifacts[0]["data"]
    assert context["target"] == "SYS-001.cv-ranker"
    assert "REQ.AIA.10.2.f.bias-examination" in context["testable"]
    assert any(r["path"] == "plugins/cv-ranker/plugin.yaml" for r in context["files_read"])
    state = (await graph.aget_state(CONFIG)).values
    assert state["kb_version"] == "2026.11.14-1"
    # The sandbox got the plugin files under input/ paths the plugin.yaml refers to.
    assert {"plugin.yaml", "data/data-dictionary.yaml"} <= set(h.sandbox.files_seen[0])


async def test_rejection_loops_back_with_the_reason_and_the_agent_remembers():
    h = make_harness()
    graph = build_graph(h, InMemorySaver())
    await graph.ainvoke(START, CONFIG)
    await _answer(
        graph,
        {
            "decision": "changes_requested",
            "reasonCategory": "wrong_metric",
            "comment": "Use selection rate ratio per nationality, not only flip rate",
        },
    )
    gate = await _pending(graph)
    assert gate.value["gate"] == "scenarios"
    versions = [a["version"] for a in h.backend.artifacts if a["kind"] == "scenarios"]
    assert versions == [1, 2]
    state = (await graph.aget_state(CONFIG)).values
    assert state["redos"]["plan_scenarios"] == 1
    assert state["feedback"]["plan_scenarios"]["reason"].startswith("Use selection rate")
    # The redo recorded the lesson in the system's memory (step + audit provenance).
    (record,) = await h.memory.list_system(SYSTEM_ID)
    assert record.name == "plan-scenarios-wrong-metric"
    assert record.audit_id == AUDIT_ID and record.step == "plan_scenarios"
    assert "selection rate ratio" in record.content_md

    await _answer(graph, {"decision": "approved"})
    assert (await _pending(graph)).value["gate"] == "datasets"
    assert "plan_scenarios" not in (await graph.aget_state(CONFIG)).values["feedback"]


async def test_too_many_rejections_stop_the_audit():
    settings.pipeline.max_redos = 1
    h = make_harness()
    graph = build_graph(h, InMemorySaver())
    await graph.ainvoke(START, CONFIG)
    await _answer(graph, {"decision": "rejected", "comment": "no"})
    await _answer(graph, {"decision": "rejected", "comment": "still no"})
    snapshot = await graph.aget_state(CONFIG)
    assert not snapshot.next
    assert snapshot.values["status"] == "rejected"
    assert h.backend.patches[-1]["status"] == "failed"


async def test_scenarios_check_gaps_send_the_plan_back_once():
    box = FakeSandbox(scenario_missing=[{"priority": "high", "what": "x", "why": "y"}])
    h = make_harness(sandbox=box)
    graph = build_graph(h, InMemorySaver())
    await graph.ainvoke(START, CONFIG)
    assert (await _pending(graph)).value["gate"] == "scenarios"
    assert sum(1 for c in box.commands if "scenarios-check" in c) == 2
    analyses = [a for a in h.backend.artifacts if a["kind"] == "scenario_analysis"]
    assert [a["data"]["verifier"]["action"] for a in analyses] == ["redo", "next"]


async def test_failed_dataset_gate_redrafts_the_spec_then_asks_the_human():
    box = FakeSandbox(analyze_overall="fail")
    h = make_harness(sandbox=box)
    graph = build_graph(h, InMemorySaver())
    await graph.ainvoke(START, CONFIG)
    await _answer(graph, {"decision": "approved"})
    assert (await _pending(graph)).value["gate"] == "datasets"
    assert h.backend.kinds().count("generation_spec") == 2
    state = (await graph.aget_state(CONFIG)).values
    assert state["feedback"]["draft_spec"]["source"] == "verifier"


async def test_invalid_spec_from_generate_goes_back_to_draft_spec():
    box = FakeSandbox(
        fail={"generate": ExecResult(2, "", "synthkit: invalid input: unknown field")}
    )
    h = make_harness(sandbox=box)
    graph = build_graph(h, InMemorySaver())
    await graph.ainvoke(START, CONFIG)
    # One automatic redo, then the spec is still invalid: the run fails with a public
    # message and the checkpoint stays on generate_data (a retry resumes there).
    with pytest.raises(StepFailed, match="still invalid"):
        await _answer(graph, {"decision": "approved"})
    snapshot = await graph.aget_state(CONFIG)
    assert snapshot.next == ("generate_data",)
    assert h.backend.kinds().count("generation_spec") == 2
    assert [a["data"].get("status") for a in h.backend.artifacts if a["kind"] == "dataset"] == [
        "invalid_spec"
    ]


async def test_public_data_gate_and_reference_sample():
    found = {
        "results": [
            {
                "artifact_id": "cand-1",
                "candidates": [{"id": "openml:31", "score": 0.75}],
                "recommendation": {"mode": "reference_sample", "candidate": "openml:31"},
            }
        ]
    }
    h = make_harness(search_result=found)
    graph = build_graph(h, InMemorySaver())
    await graph.ainvoke(START, CONFIG)
    gate = await _pending(graph)
    assert gate.value["gate"] == "public_data"
    assert gate.value["artifact_ids"] == {"public_dataset_candidates": "cand-1"}
    await _answer(graph, {"decision": "approved", "edits": {"selected": "openml:31"}})
    await _answer(graph, {"decision": "approved"})  # scenarios
    state = (await graph.aget_state(CONFIG)).values
    assert state["public_data"]["mode"] == "reference_sample"
    spec = yaml.safe_load(state["spec"]["yaml"])
    assert spec["generation"] == {
        "mode": "reference_sample",
        "reference": "datasets/public/openml-31/data.csv",
    }
    assert state["spec"]["mode"] == "reference_sample"


async def test_findings_carry_grounded_evidence_and_the_critic_adjusts_them():
    h = make_harness()
    graph = build_graph(h, InMemorySaver())
    await graph.ainvoke(START, CONFIG)
    await _answer(graph, {"decision": "approved"})
    await _answer(graph, {"decision": "approved"})
    findings = [a for a in h.backend.artifacts if a["kind"] == "finding"]
    first = findings[0]["data"]
    assert first["verdict"] in {
        "supports_compliance",
        "indicates_gap",
        "inconclusive",
        "not_assessable_by_testing",
    }
    ev = first["evidence"][0]
    assert ev["mlflow_run_id"].startswith("run-T-")
    assert "organisational" in ev["threshold_source"]
    assert first["citations"][0]["kb_version"] == "2026.11.14-1"
    assert findings[0]["fileRefs"] == [f"mlflow:runs/{ev['mlflow_run_id']}"]
    gap = next(f["data"] for f in findings if f["data"]["verdict"] == "indicates_gap")
    assert gap["evidence"][0]["metric"] == "cf_flip_rate.nationality.causal"
    plan = next(a for a in h.backend.artifacts if a["kind"] == "test_plan")["data"]
    assert plan["card"] == "system-card.yaml" and plan["tests"][0]["template"].startswith("TT.")
    report = next(a for a in h.backend.artifacts if a["kind"] == "report")["data"]
    assert report["management"]["traffic_lights"]
    critic = next(a for a in h.backend.artifacts if a["kind"] == "critic")["data"]
    assert {r["finding_id"] for r in critic["reviews"]} == {f["name"] for f in findings}


def test_annex_basis_and_decisions_are_normalised():
    assert annex_basis({"annex_basis": "Annex III 4(a)"}) == "AIA.ANNEX_III.4.a"
    assert annex_basis({"annex_basis": "Annex III 5(b)"}) == "AIA.ANNEX_III.5.b"
    assert annex_basis({}) is None
    assert normalise_decision("approve")["decision"] == "approved"
    assert normalise_decision({"decision": "reject", "comment": "x"})["reason"] == "x"
    assert normalise_decision({"decision": "changes_requested"})["decision"] == "changes_requested"
