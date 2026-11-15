"""Deterministic step outputs for ``AGENTS_FAKE_LLM=true`` (dry runs, demos without a key).

Each function reads the same state the real step's brief is built from and
returns what a careful model would: scenarios from the plugin's protected
attributes, proxies and monotone fields; a GenerationSpec synthkit accepts;
findings copied from the test results; a critic that weakens findings whose CI
crosses the threshold; reports from both. They go through the real deep agent
(a scripted model calls the result tool with them), so everything downstream
(verifiers, artifacts, gates, traces) is exercised for real.
"""

from __future__ import annotations

from typing import Any

import yaml

from pipeline.schemas import (
    Assessment,
    AssessmentSet,
    AuditReport,
    ChangeJudgement,
    Citation,
    DataNeeds,
    Evidence,
    Finding,
    FindingSet,
    GenerationSpecDraft,
    ManagementReport,
    MetricClaim,
    ObligationCriticReport,
    ObligationCriticReview,
    ResultsAnalysis,
    Scenario,
    ScenarioPlan,
    SpecAssumption,
    TrafficLight,
)

FAIRNESS_TT = "TT.fairness.counterfactual"
GROUP_TT = "TT.fairness.group_metrics"
PERTURB_TT = "TT.robustness.perturbation"
EDGE_TT = "TT.robustness.edge_cases"


def _yaml(text: str | None) -> dict[str, Any]:
    data = yaml.safe_load(text or "") if text else None
    return data if isinstance(data, dict) else {}


def _dictionary(state: dict[str, Any]) -> dict[str, Any]:
    return _yaml((state.get("files") or {}).get("data/data-dictionary.yaml"))


def _plugin(state: dict[str, Any]) -> dict[str, Any]:
    return _yaml((state.get("files") or {}).get("plugin.yaml"))


def _requirement_for(state: dict[str, Any], template: str, fallback: str) -> str:
    for req in state.get("requirements") or []:
        if template in (req.get("test_templates") or []):
            return str(req.get("id"))
    return fallback


def _source_of(state: dict[str, Any], requirement: str) -> str:
    for req in state.get("requirements") or []:
        if req.get("id") == requirement and req.get("source"):
            return str(req["source"])
    parts = requirement.split(".")
    return ".".join(["AIA", *parts[2:4]]) if len(parts) > 3 else "AIA.10"


def plan_scenarios(state: dict[str, Any]) -> ScenarioPlan:
    dictionary = _dictionary(state)
    plugin = _plugin(state)
    fields = dictionary.get("fields") or {}
    hints = plugin.get("scenarios") or {}
    target = str(plugin.get("id") or state.get("target") or "")
    protected = [p for p in hints.get("protected_attributes") or [] if p in fields] or [
        f for f, d in fields.items() if d.get("role") == "protected"
    ]
    moving = {
        f
        for f, s in ((state.get("profile") or {}).get("sensitivity") or {}).items()
        if isinstance(s, dict) and s.get("moves_output")
    }
    bias_req = _requirement_for(state, FAIRNESS_TT, "REQ.AIA.10.2.f.bias-examination")
    group_req = _requirement_for(state, GROUP_TT, bias_req)
    scenarios: list[Scenario] = []
    # Every protected attribute (at most 3): a proxy that moves the output is the point.
    for attr in protected[:3]:
        proxies = [
            f
            for f, d in fields.items()
            if d.get("role") == "proxy" and attr in (d.get("proxy_for") or [])
        ]
        modes = (
            ["attribute_only", "causal", "proxy_only"] if proxies else ["attribute_only", "causal"]
        )
        moved = [p for p in proxies if p in moving]
        scenarios.append(
            Scenario(
                id=f"SC-{len(scenarios) + 1:02d}",
                requirement=bias_req,
                target=target,
                template="counterfactual_twins",
                test_template=FAIRNESS_TT,
                data_needs=DataNeeds(
                    fields=[attr, *proxies], attribute=attr, twin_modes=modes, n=400
                ),
                expected_behaviour=f"Flipping {attr} (or its proxies) does not change the decision",
                protected=[attr],
                proxies=proxies,
                metric="flip_rate",
                rationale=(
                    f"The profile shows {', '.join(moved)} move the output and stand in "
                    f"for {attr}; "
                    "attribute-only twins alone would miss it."
                    if moved
                    else f"{attr} is protected; causal twins test its downstream effect."
                ),
            )
        )
    if protected:
        attr = protected[0] if "sex" not in protected else "sex"
        scenarios.append(
            Scenario(
                id=f"SC-{len(scenarios) + 1:02d}",
                requirement=group_req,
                target=target,
                template="group_fairness",
                test_template=GROUP_TT,
                data_needs=DataNeeds(fields=[attr], attribute=attr, n=400),
                expected_behaviour=f"Selection rates across {attr} groups meet the org ratio",
                protected=[attr],
                metric="selection_rate_ratio",
                rationale="Four-fifths rule on the organisation's thresholds.",
            )
        )
    monotone = [f for f, d in fields.items() if d.get("monotone")]
    if monotone:
        scenarios.append(
            Scenario(
                id=f"SC-{len(scenarios) + 1:02d}",
                requirement=_requirement_for(
                    state, PERTURB_TT, "REQ.AIA.15.1.accuracy-consistency"
                ),
                target=target,
                template="perturbation",
                test_template=PERTURB_TT,
                data_needs=DataNeeds(fields=monotone, n=200),
                expected_behaviour=f"More {monotone[0]}, all else equal, never lowers the score",
                metric="monotonicity_violation_rate",
                rationale="Declared monotone field in the data dictionary.",
            )
        )
    numeric = [
        f for f, d in fields.items() if d.get("type") in ("integer", "float") and d.get("range")
    ]
    if numeric:
        scenarios.append(
            Scenario(
                id=f"SC-{len(scenarios) + 1:02d}",
                requirement=_requirement_for(state, EDGE_TT, "REQ.AIA.15.4.robustness"),
                target=target,
                template="edge_cases",
                test_template=EDGE_TT,
                data_needs=DataNeeds(fields=numeric[:3], n=50),
                expected_behaviour="Out-of-range and missing values are rejected, not scored",
                metric="edge_case_failure_rate",
                rationale="Edge cases declared on the plugin.",
            )
        )
    testable = {s.requirement for s in scenarios}
    not_testable = [
        str(r.get("id"))
        for r in state.get("requirements") or []
        if r.get("testability") != "model_and_data_test" and r.get("id") not in testable
    ][:12]
    return ScenarioPlan(
        target=target,
        scenarios=scenarios,
        not_testable=not_testable,
        assumptions=["Synthetic population follows the data dictionary (training-data.md stats)."],
    )


def draft_spec(state: dict[str, Any]) -> GenerationSpecDraft:
    plan = state.get("scenarios") or {}
    reference = (state.get("public_data") or {}).get("reference")
    spec: dict[str, Any] = {
        "version": 1,
        "name": f"{plan.get('target') or state.get('target')}.audit",
        "dictionary": "data/data-dictionary.yaml",
        "plugin": "plugin.yaml",
        "n": 400,
    }
    if state.get("profile"):
        spec["model_profile"] = "model-profile.json"
        spec["boundary"] = {"share": 0.3, "band": 0.15, "pool": 5}
    if reference:
        spec["generation"] = {"mode": "reference_sample", "reference": reference}
    transforms: list[dict[str, Any]] = []
    protected: list[str] = []
    for sc in plan.get("scenarios") or []:
        needs = sc.get("data_needs") or {}
        if sc.get("template") == "counterfactual_twins" and needs.get("attribute"):
            item: dict[str, Any] = {
                "kind": "twins",
                "attribute": needs["attribute"],
                "modes": needs.get("twin_modes") or ["attribute_only", "causal"],
                "max_base": 150,
            }
            if sc.get("proxies"):
                item["proxies"] = sc["proxies"]
            transforms.append(item)
            protected.append(needs["attribute"])
        elif sc.get("template") == "perturbation":
            transforms.append(
                {
                    "kind": "perturbation",
                    "fields": needs.get("fields") or [],
                    "delta": 1,
                    "max_base": 100,
                }
            )
        elif sc.get("template") == "edge_cases":
            transforms.append({"kind": "edge_cases", "fields": needs.get("fields") or []})
        elif needs.get("attribute"):
            protected.append(needs["attribute"])
    cells = list(dict.fromkeys(protected))[:2]
    if cells:
        spec["strata"] = {"by": cells[:1], "balance": True}
        spec["coverage"] = {"cells": cells, "min_per_cell": 20}
    spec["transforms"] = transforms
    return GenerationSpecDraft(
        spec_yaml=yaml.safe_dump(spec, sort_keys=False),
        mode="reference_sample" if reference else "zero_shot",
        assumptions=[
            SpecAssumption(
                item="strata",
                provenance="llm_assumption",
                note="Balanced strata give every group rows for a CI; realism warns by design.",
            )
        ],
        rationale="Twins per protected attribute with its proxies, perturbation on monotone "
        "fields, "
        "edge cases on numeric fields.",
    )


def _verdict(test: dict[str, Any]) -> tuple[str, float]:
    """run-tests status -> verdict: fail = gap, pass (whole CI meets it) = supports."""
    status = test.get("status")
    if status == "fail":
        return "indicates_gap", 0.8
    if status == "pass":
        return "supports_compliance", 0.7
    if status == "inconclusive":
        return "inconclusive", 0.45
    return "inconclusive", 0.3


def analyse(state: dict[str, Any]) -> FindingSet:
    kb = str(state.get("kb_version") or "unknown")
    findings = []
    for n, test in enumerate((state.get("test_results") or {}).get("tests") or [], start=1):
        verdict, confidence = _verdict(test)
        threshold = test.get("threshold") if isinstance(test.get("threshold"), dict) else {}
        requirement = str(test.get("requirement") or "")
        findings.append(
            Finding(
                id=f"F-{n:02d}",
                requirement=requirement,
                title=f"{test.get('metric')} on {test.get('scenario')}",
                verdict=verdict,
                confidence=confidence,
                reasoning=f"{test.get('metric')} = {test.get('value')} against "
                f"{threshold.get('op', '')} {threshold.get('value', 'n/a')}.",
                evidence=[
                    Evidence(
                        test_id=str(test.get("id")),
                        metric=str(test.get("metric")),
                        value=test.get("value"),
                        ci95=test.get("ci95"),
                        threshold=f"{threshold.get('op', '')} {threshold.get('value', '')}".strip()
                        or None,
                        threshold_source=threshold.get("source")
                        or "organisational (system card), not an AI Act number",
                        mlflow_run_id=test.get("mlflow_run_id"),
                    )
                ],
                counter_evidence=["The test population is synthetic (dictionary-driven)."],
                would_change_if=["The same test on a reference sample gives a different result."],
                citations=[Citation(provision_id=_source_of(state, requirement), kb_version=kb)],
            )
        )
    if not findings:
        findings.append(
            Finding(
                id="F-01",
                requirement="REQ.AIA.10.2.f.bias-examination",
                title="No test result",
                verdict="inconclusive",
                confidence=0.2,
                reasoning="The tests produced no results.",
                citations=[Citation(provision_id="AIA.10.2.f", kb_version=kb)],
            )
        )
    return FindingSet(findings=findings, summary=f"{len(findings)} findings from the test results.")


def analyse_results(brief: dict[str, Any]) -> ResultsAnalysis:
    """Echo synthkit's headline numbers (the scripted analyst 'recomputes' them exactly)."""
    tests = [t for t in brief.get("tests") or [] if t.get("value") is not None][:6]
    return ResultsAnalysis(
        headline=[
            MetricClaim(
                test_id=str(t.get("test_id")), metric=str(t.get("metric")), value=t["value"]
            )
            for t in tests
        ],
        observations=[f"{len(brief.get('tests') or [])} metric rows over the saved predictions."],
        code_files=[],
        summary="Recomputed the headline metrics from predictions.parquet.",
    )


def assess(brief: dict[str, Any]) -> AssessmentSet:
    """Keep the rule verdict; cite the obligation's article at the pinned kb."""
    kb = str(brief.get("kb_version") or "unknown")
    out = []
    for ob in brief.get("obligations") or []:
        rows = ob.get("tests") or []
        out.append(
            Assessment(
                obligation_id=ob["obligation_id"],
                verdict=ob.get("rule_verdict") or "inconclusive",
                reasoning=f"{ob.get('rule_reason')}. Thresholds are the organisation's "
                "(system card), not the AI Act's.",
                counter_arguments=["The test data is synthetic; real applicants may differ."],
                would_change_if=["A re-run on a real labelled sample lands on the other side."],
                citations=[Citation(provision_id=str(ob.get("article")), kb_version=kb)]
                if ob.get("article")
                else [],
                evidence_test_ids=[str(r.get("id")) for r in rows[:6]],
            )
        )
    if not out:
        out.append(
            Assessment(obligation_id="none", verdict="inconclusive", reasoning="Nothing to assess.")
        )
    return AssessmentSet(assessments=out)


def critic(brief: dict[str, Any]) -> ObligationCriticReport:
    reviews = []
    for v in brief.get("verdicts") or []:
        crossing = v.get("verdict") in ("partial", "inconclusive")
        reviews.append(
            ObligationCriticReview(
                obligation_id=v["obligation_id"],
                upheld=True,
                grounds=(
                    "The CI crosses the threshold or the judges disagree; the verdict already "
                    "says the evidence cannot separate pass from fail."
                    if crossing
                    else f"The metrics in the brief support {v.get('verdict')} against the "
                    "organisation's threshold."
                ),
                objection="Synthetic twins may be less realistic than real applicants.",
            )
        )
    if not reviews:
        reviews.append(
            ObligationCriticReview(obligation_id="none", upheld=True, grounds="No verdicts.")
        )
    return ObligationCriticReport(
        reviews=reviews, overall=f"Reviewed {len(reviews)} verdicts against the test results."
    )


_LIGHT = {
    "gap": "red",
    "partial": "amber",
    "inconclusive": "amber",
    "pass": "green",
    "not_assessable_by_testing": "grey",
    "not_applicable": "grey",
}


def report(state: dict[str, Any]) -> AuditReport:
    findings = state.get("sealed") or []
    pins = state.get("pins") or {}
    lines = [
        f"# Audit {state.get('audit_id')} - {state.get('system_id')} ({state.get('target')})",
        f"kb_version {pins.get('kb_version') or state.get('kb_version')}, "
        f"model {pins.get('model_version')}, seed {pins.get('seeds')}",
        "",
    ]
    for f in findings:
        lines.append(f"## {f['obligation_id']}: {f.get('verdict')} ({f.get('severity')})")
        lines.append(str(f.get("reasoning") or ""))
    gaps = [f for f in findings if f.get("gap_id")]
    return AuditReport(
        engineer_markdown="\n".join(lines),
        management=ManagementReport(
            headline=f"{len(gaps)} gap(s) in {len(findings)} obligations "
            f"for {state.get('system_id')}.",
            traffic_lights=[
                TrafficLight(
                    requirement=str(f.get("obligation_id")),
                    status=_LIGHT.get(str(f.get("verdict")), "grey"),
                    note=str(f.get("reasoning") or "")[:120],
                )
                for f in findings
            ],
            decisions_needed=["Approve a mitigation plan for each red obligation."] if gaps else [],
            next_steps=["Fix the gaps, then re-run this audit."] if gaps else ["Keep monitoring."],
        ),
    )


def change_judge(brief: dict[str, Any]) -> ChangeJudgement:
    impacted = brief.get("impacted_requirements") or []
    findings = brief.get("findings") or []
    hit = [f.get("id") for f in findings if f.get("requirement") in impacted]
    types = set((brief.get("change") or {}).get("change_types") or {})
    if not impacted:
        decision, why = "no_impact", "No requirement this system relies on is touched."
    elif not hit:
        decision, why = "new_tests_needed", "An impacted requirement has no test on this system."
    elif types <= {"editorial"}:
        decision, why = "reinterpret_existing_evidence", "Only wording changed."
    else:
        decision, why = "rerun_tests", "A requirement behind existing findings changed."
    return ChangeJudgement(
        decision=decision,
        rationale=why,
        strongest_counter_argument="The change may be editorial only and leave the tests valid.",
        affected_findings=[h for h in hit if h],
        affected_requirements=list(impacted),
        confidence=0.6,
    )


__all__ = ["analyse", "change_judge", "critic", "draft_spec", "plan_scenarios", "report"]
