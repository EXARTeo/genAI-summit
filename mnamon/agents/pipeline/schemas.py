"""The result contracts of the pipeline's LLM steps (one pydantic model per step).

Each deep-agent step returns exactly ONE of these, through a structured-output
tool (LangChain ``ToolStrategy``): a malformed result is a validation error the
model reads and fixes in the same run. Deterministic verifiers then check the
content against evidence (``pipeline/verify.py``). The models are kept flat and
explicit (no free-form maps) so Gemini's function-calling schema accepts them.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Verdict = Literal[
    "supports_compliance", "indicates_gap", "inconclusive", "not_assessable_by_testing"
]
CriticCall = Literal["upheld", "weakened", "overturned"]
ChangeDecision = Literal[
    "no_impact", "reinterpret_existing_evidence", "rerun_tests", "new_tests_needed"
]
Template = Literal[
    "group_fairness",
    "counterfactual_twins",
    "perturbation",
    "edge_cases",
    "accuracy_per_subgroup",
    "monotonicity",
]
TwinMode = Literal["attribute_only", "causal", "proxy_only"]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="ignore")


# --------------------------------------------------------------- plan_scenarios
class DataNeeds(_Strict):
    fields: list[str] = Field(description="Dictionary fields the test varies or groups by.")
    attribute: str | None = Field(None, description="The protected attribute flipped or grouped.")
    twin_modes: list[TwinMode] = Field(
        default_factory=list, description="Twin modes for counterfactual tests."
    )
    n: int = Field(400, ge=20, le=5000, description="Base rows the test needs.")


class Scenario(_Strict):
    id: str = Field(description="SC-01, SC-02, ...")
    requirement: str = Field(description="Requirement id from the context (REQ.AIA...).")
    target: str = Field(description="The plugin id under test, e.g. SYS-001.cv-ranker.")
    template: Template
    test_template: str = Field("", description="reg-memory test template id (TT....).")
    data_needs: DataNeeds
    expected_behaviour: str = Field(description="What a compliant model does, testably.")
    protected: list[str] = Field(default_factory=list)
    proxies: list[str] = Field(default_factory=list)
    metric: str = Field(description="selection_rate_ratio, flip_rate, score_gap, ...")
    rationale: str = Field(description="Why this test, citing the profile or memory.")
    memory_applied: list[str] = Field(
        default_factory=list, description="Memory entry paths this scenario follows."
    )


class ScenarioPlan(_Strict):
    target: str
    scenarios: list[Scenario] = Field(min_length=1)
    not_testable: list[str] = Field(
        default_factory=list,
        description="Requirement ids that need document review, not a model test.",
    )
    assumptions: list[str] = Field(default_factory=list)
    lessons_recorded: list[str] = Field(
        default_factory=list, description="Names of memory entries written in this step."
    )


# ------------------------------------------------------------------ draft_spec
class SpecAssumption(_Strict):
    item: str = Field(description="The spec path, e.g. fields.postcode_region.conditional.")
    provenance: Literal["dictionary", "training_doc", "memory", "llm_assumption", "public_data"]
    note: str


class GenerationSpecDraft(_Strict):
    spec_yaml: str = Field(
        description="The synthkit GenerationSpec as YAML (version, name, dictionary, n, "
        "generation, strata, boundary, coverage, transforms)."
    )
    mode: Literal["zero_shot", "reference_sample"] = "zero_shot"
    assumptions: list[SpecAssumption] = Field(default_factory=list)
    rationale: str = ""
    lessons_recorded: list[str] = Field(default_factory=list)


# ---------------------------------------------------------- analyse (findings)
class Evidence(_Strict):
    test_id: str
    metric: str
    value: float | None = None
    ci95: list[float] | None = Field(None, description="[low, high] when the test reports one.")
    threshold: str | None = Field(None, description="e.g. '>= 0.80'.")
    threshold_source: str = Field(
        description="Where the threshold comes from, e.g. system-card org_thresholds "
        "(organisational, not set by the AI Act)."
    )
    mlflow_run_id: str | None = None


class Citation(_Strict):
    provision_id: str = Field(description="AIA.10.2.f, AIA.ANNEX_III.4.a, ...")
    kb_version: str


class Finding(_Strict):
    id: str = Field(description="F-01, F-02, ...")
    requirement: str
    title: str
    verdict: Verdict
    confidence: float = Field(ge=0, le=1)
    reasoning: str
    evidence: list[Evidence] = Field(default_factory=list)
    counter_evidence: list[str] = Field(default_factory=list)
    would_change_if: list[str] = Field(default_factory=list)
    citations: list[Citation] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


class FindingSet(_Strict):
    findings: list[Finding] = Field(min_length=1)
    summary: str = ""


# ---------------------------------------------------------------------- critic
class CriticReview(_Strict):
    finding_id: str
    call: CriticCall
    strongest_objection: str = Field(description="The best argument against the finding.")
    adjusted_verdict: Verdict
    adjusted_confidence: float = Field(ge=0, le=1)
    checked_evidence: list[str] = Field(
        default_factory=list, description="Test ids / run ids / provisions actually checked."
    )


class CriticReport(_Strict):
    reviews: list[CriticReview] = Field(min_length=1)
    overall: str = ""


# ---------------------------------------------------------------------- report
class TrafficLight(_Strict):
    requirement: str
    status: Literal["green", "amber", "red", "grey"]
    note: str


class ManagementReport(_Strict):
    headline: str
    traffic_lights: list[TrafficLight] = Field(default_factory=list)
    decisions_needed: list[str] = Field(default_factory=list)
    next_steps: list[str] = Field(default_factory=list)


class AuditReport(_Strict):
    engineer_markdown: str = Field(
        description="Reproducible engineer report: setup, data, tests, findings, limits."
    )
    management: ManagementReport


# ---------------------------------------------------------------- change judge
class ChangeJudgement(_Strict):
    decision: ChangeDecision
    rationale: str
    strongest_counter_argument: str
    affected_findings: list[str] = Field(default_factory=list)
    affected_requirements: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0, le=1)


#: The step -> result model table (the result contract of each deep-agent step).
STEP_RESULTS: dict[str, type[BaseModel]] = {
    "plan_scenarios": ScenarioPlan,
    "draft_spec": GenerationSpecDraft,
    "analyse": FindingSet,
    "critic": CriticReport,
    "report": AuditReport,
    "change_judge": ChangeJudgement,
}

__all__ = [
    "STEP_RESULTS",
    "AuditReport",
    "ChangeDecision",
    "ChangeJudgement",
    "Citation",
    "CriticReport",
    "CriticReview",
    "DataNeeds",
    "Evidence",
    "Finding",
    "FindingSet",
    "GenerationSpecDraft",
    "ManagementReport",
    "Scenario",
    "ScenarioPlan",
    "SpecAssumption",
    "TrafficLight",
    "Verdict",
]
