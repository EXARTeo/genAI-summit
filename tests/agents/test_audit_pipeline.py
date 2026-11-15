"""The audit pipeline (``pipeline/``): order, gates, rejection loops, verifiers, artifacts.

The graph runs for real (LangGraph + deepagents step agents) with the scripted
fake model (``AGENTS_FAKE_LLM``), an in-memory checkpointer and in-memory
backend / reg-memory / sandbox / memory stand-ins (``pipeline_fakes.py``).
"""

from __future__ import annotations

import hashlib
from typing import Any

import pytest
import yaml
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command
from pipeline.clients import ExecResult
from pipeline.graph import StepFailed, annex_basis, normalise_decision
from pipeline.verdicts import finding_hash
from pipeline_fakes import (
    AUDIT_ID,
    DATASET,
    PREDICTIONS,
    SYSTEM_ID,
    FakeSandbox,
    build_graph,
    make_harness,
)

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
        "pin",
        "ground_obligations",
        "profile_model",
        "plan_scenarios",
        "analyse_scenarios",
        "approve_scenarios",
    ]
    assert h.backend.patches[-1]["status"] == "waiting_approval"
    # plan_scenarios writes the plan; analyse_scenarios rewrites it with the decision-model reviews.
    assert h.backend.kinds() == [
        "context",
        "pins",
        "obligation_map",
        "model_profile",
        "scenarios",
        "scenarios",
        "scenario_analysis",
    ]

    await _answer(graph, {"decision": "approved"})
    assert (await _pending(graph)).value["gate"] == "datasets"
    assert h.backend.kinds()[-3:] == ["generation_spec", "dataset", "dataset_analysis"]

    await _answer(graph, {"decision": "approved"})
    snapshot = await graph.aget_state(CONFIG)
    assert not snapshot.next and not snapshot.interrupts
    kinds = h.backend.kinds()
    assert kinds[kinds.index("dataset_analysis") + 1 :][:6] == [
        "test_plan",
        "inference",
        "test_result",
        "analysis",
        "verdicts",
        "critic",
    ]
    assert "finding" in kinds and kinds[-2:] == ["seal", "report"]
    assert h.backend.patches[-1]["status"] == "done"
    # Every sandbox step really ran synthkit, in order: raw inference first, metrics after.
    subcommands = [c.split("synthkit ")[-1].split()[0] for c in h.sandbox.commands]
    assert subcommands == [
        "profile",
        "scenarios-check",
        "generate",
        "analyze",
        "run-inference",
        "metrics",
    ]
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
    assert versions == [1, 2, 3, 4]  # plan, reviewed plan, redo, reviewed redo
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
    # Two drafts, then the code-built fallback spec (also rejected by this sandbox).
    specs = [a["data"] for a in h.backend.artifacts if a["kind"] == "generation_spec"]
    assert len(specs) == 3 and specs[-1]["fallback"] and not specs[0].get("fallback")
    assert [a["data"].get("status") for a in h.backend.artifacts if a["kind"] == "dataset"] == [
        "invalid_spec"
    ]


async def test_a_spec_that_stays_invalid_falls_back_to_the_code_built_spec():
    fails = iter([ExecResult(2, "", "synthkit: invalid input: rule ids"), None, None])

    class Flaky(FakeSandbox):
        async def run(self, command, files, *, timeout=None):
            if "synthkit generate" in command:
                failure = next(fails, None)
                if failure is not None:
                    self.commands.append(command)
                    return failure
            return await super().run(command, files, timeout=timeout)

    settings.pipeline.max_auto_redos = 0
    h = make_harness(sandbox=Flaky())
    graph = build_graph(h, InMemorySaver())
    await graph.ainvoke(START, CONFIG)
    await _answer(graph, {"decision": "approved"})
    assert (await _pending(graph)).value["gate"] == "datasets"
    state = (await graph.aget_state(CONFIG)).values
    assert state["spec"]["fallback"] and state["dataset"]["sha256"]


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
    assert (await _pending(graph)).value["gate"] == "scenarios"
    assert not h.searches  # the search waits for the approved scenarios
    await _answer(graph, {"decision": "approved"})  # scenarios
    gate = await _pending(graph)
    assert gate.value["gate"] == "public_data"
    assert gate.value["artifact_ids"] == {"public_dataset_candidates": "cand-1"}
    # The search got the approved scenarios (what the data must carry).
    (search,) = h.searches
    assert search[2] and all("data_needs" in sc for sc in search[2])
    await _answer(graph, {"decision": "approved", "edits": {"selected": "openml:31"}})
    state = (await graph.aget_state(CONFIG)).values
    assert state["public_data"]["mode"] == "reference_sample"
    spec = yaml.safe_load(state["spec"]["yaml"])
    assert spec["generation"] == {
        "mode": "reference_sample",
        "reference": "datasets/public/openml-31/data.csv",
    }
    assert state["spec"]["mode"] == "reference_sample"


async def test_an_old_order_audit_paused_before_planning_resumes_by_planning_first():
    h = make_harness()
    graph = build_graph(h, InMemorySaver())
    await graph.ainvoke(START, CONFIG)
    # Old order: find_public_data ran before plan_scenarios, so no plan exists yet.
    await graph.aupdate_state(
        CONFIG,
        {"scenarios": {}, "public_data": {"mode": "zero_shot", "reason": "old order"}},
        as_node="find_public_data",
    )
    assert (await graph.aget_state(CONFIG)).next == ("gate_public_data",)
    await graph.ainvoke(None, CONFIG)
    assert (await _pending(graph)).value["gate"] == "scenarios"
    assert (await graph.aget_state(CONFIG)).values["scenarios"]["scenarios"]


async def test_every_obligation_in_scope_gets_exactly_one_sealed_verdict():
    h = make_harness()
    graph = build_graph(h, InMemorySaver())
    await graph.ainvoke(START, CONFIG)
    await _answer(graph, {"decision": "approved"})
    await _answer(graph, {"decision": "approved"})
    state = (await graph.aget_state(CONFIG)).values
    scope = [e["obligation_id"] for e in state["scope"]]
    sealed = h.backend.sealed
    # Coverage invariant: one verdict per obligation in scope, posted to the findings endpoint.
    assert sorted(f["obligation_id"] for f in sealed) == sorted(scope)
    by = {f["obligation_id"]: f for f in sealed}
    bias = by["OBL.AIA.10.2.f.bias-examination"]
    assert bias["verdict"] == "gap" and bias["gap_id"].startswith("G-SYS-001-")
    assert bias["severity"] in {"critical", "high", "medium"}
    assert {"rule", "gemini", "iris"} <= set(bias["judges"])
    assert bias["citations"][0]["kb_version"] == "2026.11.14-1"
    shas = {r.get("sha256") for r in bias["evidence_refs"]}
    assert hashlib.sha256(PREDICTIONS).hexdigest() in shas
    assert hashlib.sha256(DATASET).hexdigest() in shas
    assert by["OBL.AIA.11.1.technical-documentation"]["verdict"] == "not_assessable_by_testing"
    assert bias["critic"]["grounds"]
    # Hash chain: each finding seals the previous one's hash.
    assert sealed[0]["prev_hash"].startswith("genesis:")
    assert all(b["prev_hash"] == a["hash"] for a, b in zip(sealed, sealed[1:], strict=False))
    assert all(f["hash"] == finding_hash(f, f["prev_hash"]) for f in sealed)
    # The pins are written back to the audit with the concrete model version.
    pins = next(p["data"]["pins"] for p in h.backend.patches if (p["data"] or {}).get("pins"))
    assert pins["kb_version"] == "2026.11.14-1" and pins["dossier_version"] == 3
    assert pins["seeds"]["generation"] == settings.pipeline.seed
    # The UI's finding artifacts and the report (with the code-written sections).
    findings = [a for a in h.backend.artifacts if a["kind"] == "finding"]
    assert len(findings) == len(scope)
    report = next(a for a in h.backend.artifacts if a["kind"] == "report")["data"]
    assert "## Evidence register" in report["engineer_markdown"]
    assert "## Gap list" in report["engineer_markdown"]
    assert report["gap_list"][0]["gap_id"].startswith("G-SYS-001-")
    assert len(report["evidence_register"]) == len(scope)
    assert "Fairness metrics" in report["bias_fairness_markdown"]
    assert "Annex IV" in report["annex_iv_markdown"]
    analysis = next(a for a in h.backend.artifacts if a["kind"] == "analysis")["data"]
    assert analysis["mismatches"] == []
    # Metrics replayed the SAVED predictions (no regeneration, no second model call).
    metrics_files = h.sandbox.files_seen[-1]
    assert metrics_files["inference/predictions.parquet"] == PREDICTIONS
    assert metrics_files["data/generated/dataset.parquet"] == DATASET


async def test_a_focused_audit_judges_only_the_named_obligations():
    h = make_harness()
    h.backend.audit_data["obligations"] = ["OBL.AIA.10.2.f.bias-examination"]
    graph = build_graph(h, InMemorySaver())
    await graph.ainvoke(START, CONFIG)
    await _answer(graph, {"decision": "approved"})
    await _answer(graph, {"decision": "approved"})
    assert [f["obligation_id"] for f in h.backend.sealed] == ["OBL.AIA.10.2.f.bias-examination"]
    plan = next(a for a in h.backend.artifacts if a["kind"] == "scenarios")["data"]
    assert {s["obligation_id"] for s in plan["scenarios"]} == {"OBL.AIA.10.2.f.bias-examination"}


async def test_a_failed_node_writes_an_incomplete_report_and_keeps_the_checkpoint():
    box = FakeSandbox(fail={"run-inference": ExecResult(3, "", "model unreachable")})
    h = make_harness(sandbox=box)
    graph = build_graph(h, InMemorySaver())
    await graph.ainvoke(START, CONFIG)
    await _answer(graph, {"decision": "approved"})
    with pytest.raises(StepFailed, match="run-inference failed"):
        await _answer(graph, {"decision": "approved"})
    assert (await graph.aget_state(CONFIG)).next == ("run_inference",)
    report = [a for a in h.backend.artifacts if a["kind"] == "report"][-1]["data"]
    assert report["incomplete"]["stage"] == "run_inference"
    assert "generate_data" in report["incomplete"]["ran"] and "seal" in report["not_run"]
    failed = h.backend.patches[-1]
    assert failed["status"] == "failed" and failed["stage"] == "run_inference"


async def test_findings_endpoint_missing_still_writes_finding_artifacts():
    h = make_harness()
    h.backend.findings_endpoint = False
    graph = build_graph(h, InMemorySaver())
    await graph.ainvoke(START, CONFIG)
    await _answer(graph, {"decision": "approved"})
    await _answer(graph, {"decision": "approved"})
    assert not h.backend.sealed
    assert any(a["kind"] == "finding" for a in h.backend.artifacts)
    assert h.backend.patches[-1]["status"] == "done"


def test_annex_basis_and_decisions_are_normalised():
    assert annex_basis({"annex_basis": "Annex III 4(a)"}) == "AIA.ANNEX_III.4.a"
    assert annex_basis({"annex_basis": "Annex III 5(b)"}) == "AIA.ANNEX_III.5.b"
    assert annex_basis({}) is None
    assert normalise_decision("approve")["decision"] == "approved"
    assert normalise_decision({"decision": "reject", "comment": "x"})["reason"] == "x"
    assert normalise_decision({"decision": "changes_requested"})["decision"] == "changes_requested"
