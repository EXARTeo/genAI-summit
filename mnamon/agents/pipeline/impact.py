"""Regulation change → which systems → what to do (PDF §12.6).

1. **Impact index** (deterministic, no LLM): the RegChange's changed provisions
   and interpretations intersected with each system's **obligation map** at the
   change's new kb (``pipeline/obligations.py``: an applicable obligation whose
   article or related provisions changed, or one reg-memory listed in
   ``impacted_obligations``), plus the older evidence paths: the requirements
   reg-memory marked impacted and the provisions the latest findings cite. A
   system is affected when any of the three hits.
2. **Change judge** per affected (system, change): the decision model
   (``pipeline/decision.py``) returns a :class:`~pipeline.schemas.ChangeJudgement`
   (``no_impact | reinterpret_existing_evidence | rerun_tests | new_tests_needed``,
   rationale, strongest counter-argument). Gemini is the default; with
   ``CHANGE_JUDGE_MODEL=iris`` Oumi *Iris* scores the four decisions and the
   Gemini step is the fallback.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from core.settings import settings
from pipeline import fakes
from pipeline.decision import (
    Decision,
    DecisionModel,
    DecisionTask,
    choice_confidence,
    load_questions,
)
from pipeline.schemas import ChangeJudgement
from pipeline.steps import StepRunner, StepScope


def _touches(provision: str, changed: set[str]) -> bool:
    return any(
        provision == c or provision.startswith(c + ".") or c.startswith(provision + ".")
        for c in changed
    )


def changed_provisions(change: dict[str, Any]) -> set[str]:
    out: set[str] = set()
    for entry in [*(change.get("provisions") or []), *(change.get("interpretations") or [])]:
        if entry.get("id"):
            out.add(str(entry["id"]))
        out.update(str(p) for p in entry.get("relates_to") or [])
    return out


@dataclass
class AffectedSystem:
    system_id: str
    audit_id: str | None
    kb_version: str | None
    via_requirements: list[str] = field(default_factory=list)
    via_provisions: list[str] = field(default_factory=list)
    findings: list[dict[str, Any]] = field(default_factory=list)
    tests: list[dict[str, Any]] = field(default_factory=list)
    #: Applicable obligations of the system's map the change touched (ids, sorted).
    via_obligations: list[str] = field(default_factory=list)
    #: Those map entries (obligation_id, article, verification_mode, in_force_date, ...).
    obligations: list[dict[str, Any]] = field(default_factory=list)
    #: The latest findings on an affected obligation (what goes ``stale``).
    affected_findings: list[dict[str, Any]] = field(default_factory=list)


def finding_obligation(finding: dict[str, Any], entries: list[dict[str, Any]]) -> str | None:
    """A finding's obligation id: its own, or the map entry covering its requirement."""
    if finding.get("obligation_id"):
        return str(finding["obligation_id"])
    req = finding.get("requirement")
    if not req:
        return None
    return next((e["obligation_id"] for e in entries if req in (e.get("requirements") or [])), None)


def obligations_touched(
    change: dict[str, Any], entries: list[dict[str, Any]], changed: set[str] | None = None
) -> list[dict[str, Any]]:
    """Applicable map entries whose article / related provisions changed (or reg-memory
    listed them in ``impacted_obligations``)."""
    changed = changed if changed is not None else changed_provisions(change)
    listed = {str(o.get("obligation_id")) for o in change.get("impacted_obligations") or [] if o}
    out = []
    for e in entries:
        if not e.get("applicable"):
            continue
        provisions = [e.get("article"), *(e.get("related") or [])]
        if e["obligation_id"] in listed or any(p and _touches(str(p), changed) for p in provisions):
            out.append(e)
    return out


def impact_index(
    change: dict[str, Any],
    systems: list[dict[str, Any]],
    maps: dict[str, list[dict[str, Any]]] | None = None,
) -> list[AffectedSystem]:
    """Systems whose obligations or latest evidence rely on what the change touched (no LLM).

    ``maps``: system id -> its obligation map at the change's new kb (none = the older
    requirement / citation paths only)."""
    impacted = {
        str(r.get("requirement_id")) for r in change.get("impacted_requirements") or [] if r
    }
    changed = changed_provisions(change)
    out: list[AffectedSystem] = []
    for system in systems:
        sid = str(system.get("system_id"))
        findings = list(system.get("findings") or [])
        tests = list(system.get("tests") or [])
        reqs = {str(r) for r in system.get("requirements") or []}
        reqs |= {str(f.get("requirement")) for f in findings if f.get("requirement")}
        reqs |= {str(t.get("requirement")) for t in tests if t.get("requirement")}
        cited = {
            str(c.get("provision_id"))
            for f in findings
            for c in f.get("citations") or []
            if isinstance(c, dict) and c.get("provision_id")
        }
        entries = (maps or {}).get(sid) or []
        touched = obligations_touched(change, entries, changed)
        via_obl = sorted({e["obligation_id"] for e in touched})
        via_req = sorted(reqs & impacted)
        via_prov = sorted(p for p in cited if _touches(p, changed))
        hit_findings = [
            f
            for f in findings
            if finding_obligation(f, entries) in set(via_obl)
            or (f.get("requirement") and str(f.get("requirement")) in impacted)
        ]
        if via_req or via_prov or via_obl:
            out.append(
                AffectedSystem(
                    system_id=sid,
                    audit_id=system.get("audit_id"),
                    kb_version=system.get("kb_version"),
                    via_requirements=via_req,
                    via_provisions=via_prov,
                    findings=findings,
                    tests=tests,
                    via_obligations=via_obl,
                    obligations=touched,
                    affected_findings=hit_findings,
                )
            )
    return out


def judge_brief(change: dict[str, Any], system: AffectedSystem) -> dict[str, Any]:
    """What the judge sees: the diff of what changed and this system's evidence."""
    entries = [*(change.get("provisions") or []), *(change.get("interpretations") or [])]
    return {
        "change": {
            "id": change.get("id"),
            "from_kb_version": change.get("from_kb_version"),
            "to_kb_version": change.get("to_kb_version"),
            "summary": change.get("summary"),
            "change_types": change.get("change_types"),
            "entries": [
                {
                    k: e.get(k)
                    for k in ("id", "kind", "change", "title", "change_type", "rationale", "diff")
                }
                for e in entries[:20]
            ],
        },
        "system_id": system.system_id,
        "evidence_kb_version": system.kb_version,
        # requirements reg-memory marked + those behind the affected obligations
        "impacted_requirements": sorted(
            {
                *system.via_requirements,
                *(r for e in system.obligations for r in e.get("requirements") or []),
            }
        ),
        "changed_cited_provisions": system.via_provisions,
        "affected_obligations": [
            {
                k: e.get(k)
                for k in (
                    "obligation_id",
                    "article",
                    "verification_mode",
                    "in_force_date",
                    "in_force_now",
                    "summary",
                )
            }
            for e in system.obligations
        ],
        "findings": [
            {
                **{
                    k: f.get(k)
                    for k in ("id", "requirement", "verdict", "confidence", "title", "kb_version")
                },
                "obligation_id": finding_obligation(f, system.obligations),
            }
            for f in system.findings
        ],
        "tests": [
            {k: t.get(k) for k in ("id", "requirement", "metric", "value", "status")}
            for t in system.tests
        ],
    }


def _iris_request(brief: dict[str, Any]) -> tuple[Any, dict[str, Any]]:
    return brief, dict(load_questions("change_judge"))


def _from_iris(answers: dict[str, Any], brief: dict[str, Any]) -> ChangeJudgement:
    """Iris scores the four decisions; the text comes from its probabilities and the brief."""
    answer = answers["decision"]
    decision = answer["choice"]
    probs = {k: float(v) for k, v in (answer.get("probabilities") or {}).items()}
    runner_up = max((k for k in probs if k != decision), key=lambda k: probs[k], default=None)
    criteria = load_questions("change_judge")["decision"]["criteria"]
    impacted = list(brief.get("impacted_requirements") or [])
    obligations = [
        str(o.get("obligation_id")) for o in brief.get("affected_obligations") or [] if o
    ]
    hit = [
        str(f.get("id"))
        for f in brief.get("findings") or []
        if f.get("id")
        and (f.get("requirement") in impacted or f.get("obligation_id") in set(obligations))
    ]
    cited = [str(p) for p in brief.get("changed_cited_provisions") or []]
    counter = (
        f"Iris's runner-up: {runner_up} (p={probs[runner_up]:.2f}): {criteria[runner_up]}"
        if runner_up
        else "Iris gave no alternative."
    )
    return ChangeJudgement(
        decision=decision,
        rationale=f"Iris: {decision} (p={probs.get(decision, 0):.2f}). {criteria[decision]} "
        f"Affected obligations: {', '.join(obligations) or 'none'}; "
        f"impacted requirements: {', '.join(impacted) or 'none'}; "
        f"changed cited provisions: {', '.join(cited) or 'none'}.",
        strongest_counter_argument=counter,
        affected_findings=hit,
        affected_requirements=impacted,
        confidence=choice_confidence(answer) or 0.0,
    )


#: The change judge as a decision-model task (Iris first, the ``change_judge`` step as fallback).
CHANGE_JUDGE: DecisionTask[ChangeJudgement] = DecisionTask(
    name="change_judge",
    step="change_judge",
    iris_request=_iris_request,
    from_iris=_from_iris,
    fake=fakes.change_judge,
    verdict=lambda r: r.decision,
)


class ChangeJudge:
    """Judges one (system, change) with the configured decision model (``CHANGE_JUDGE_MODEL``)."""

    def __init__(self, model: DecisionModel) -> None:
        self.model = model

    @property
    def name(self) -> str:
        return self.model.name

    async def judge(self, brief: dict[str, Any], scope: StepScope) -> Decision[ChangeJudgement]:
        return await self.model.decide(CHANGE_JUDGE, brief, ChangeJudgement, scope)


def decision_model(steps: StepRunner | None = None) -> ChangeJudge:
    """The configured change judge (``CHANGE_JUDGE_MODEL``: iris falls back to gemini)."""
    preferred = "iris" if settings.pipeline.decision_model == "iris" else "gemini"
    return ChangeJudge(DecisionModel(preferred, steps=steps))


__all__ = [
    "CHANGE_JUDGE",
    "AffectedSystem",
    "ChangeJudge",
    "changed_provisions",
    "decision_model",
    "finding_obligation",
    "impact_index",
    "obligations_touched",
    "judge_brief",
]
