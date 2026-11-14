"""Regulation change → which systems → what to do (PDF §12.6).

1. **Impact index** (deterministic, no LLM): the RegChange's changed provisions
   and interpretations, and the requirements reg-memory already marked impacted,
   matched against every system's latest audit (findings, test results, the
   requirements its context listed). A system is affected when one of its
   requirements is impacted or a finding cites a changed provision.
2. **Change judge** per affected (system, change): a :class:`DecisionModel`
   returns a :class:`~pipeline.schemas.ChangeJudgement`
   (``no_impact | reinterpret_existing_evidence | rerun_tests | new_tests_needed``,
   rationale, strongest counter-argument). Gemini is the default; the Oumi *Iris*
   adapter sits behind the same interface (``CHANGE_JUDGE_MODEL=iris``).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Protocol

import httpx

from core.logging import get_logger
from core.settings import settings
from pipeline import fakes
from pipeline.schemas import ChangeJudgement
from pipeline.steps import StepRunner, StepScope

logger = get_logger(__name__)


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


def impact_index(change: dict[str, Any], systems: list[dict[str, Any]]) -> list[AffectedSystem]:
    """Systems whose latest evidence relies on what the change touched (no LLM)."""
    impacted = {
        str(r.get("requirement_id")) for r in change.get("impacted_requirements") or [] if r
    }
    changed = changed_provisions(change)
    out: list[AffectedSystem] = []
    for system in systems:
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
        via_req = sorted(reqs & impacted)
        via_prov = sorted(p for p in cited if _touches(p, changed))
        if via_req or via_prov:
            out.append(
                AffectedSystem(
                    system_id=str(system.get("system_id")),
                    audit_id=system.get("audit_id"),
                    kb_version=system.get("kb_version"),
                    via_requirements=via_req,
                    via_provisions=via_prov,
                    findings=findings,
                    tests=tests,
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
        "impacted_requirements": system.via_requirements,
        "changed_cited_provisions": system.via_provisions,
        "findings": [
            {k: f.get(k) for k in ("id", "requirement", "verdict", "confidence", "title")}
            for f in system.findings
        ],
        "tests": [
            {k: t.get(k) for k in ("id", "requirement", "metric", "value", "status")}
            for t in system.tests
        ],
    }


class DecisionModel(Protocol):
    """Anything that turns a judge brief into a :class:`ChangeJudgement`."""

    name: str

    async def judge(self, brief: dict[str, Any], scope: StepScope) -> ChangeJudgement: ...


class GeminiDecisionModel:
    """The default: a scoped deep agent on Gemini's reasoning role (regulation tools only)."""

    name = "gemini"

    def __init__(self, steps: StepRunner | None = None) -> None:
        self.steps = steps or StepRunner()

    async def judge(self, brief: dict[str, Any], scope: StepScope) -> ChangeJudgement:
        result = await self.steps.run(
            "change_judge", brief, scope, fake=lambda: fakes.change_judge(brief)
        )
        assert isinstance(result, ChangeJudgement)  # noqa: S101 - STEP_RESULTS maps it
        return result


class IrisDecisionModel:
    """Oumi *Iris* adapter (early access; the API is not public yet: UNVERIFIED).

    Assumes an OpenAI-compatible ``POST {OUMI_BASE_URL}/chat/completions`` that
    returns the judgement as JSON. Any failure (no key, no URL, an error, an
    answer that does not validate) falls back to the Gemini judge, logged, so
    swapping the decision model can never break the impact pipeline.
    """

    name = "iris"

    def __init__(
        self, fallback: DecisionModel | None = None, client: httpx.AsyncClient | None = None
    ) -> None:
        self.fallback = fallback or GeminiDecisionModel()
        self.client = client

    async def judge(self, brief: dict[str, Any], scope: StepScope) -> ChangeJudgement:
        cfg = settings.pipeline
        key, base = cfg.oumi_api_key.get_secret_value(), cfg.oumi_base_url.rstrip("/")
        if key and base:
            try:
                return await self._call(base, key, brief)
            except Exception as exc:
                logger.warning(
                    "iris_judge_failed",
                    "Iris judge failed; using Gemini",
                    failure_reason=type(exc).__name__,
                )
        return await self.fallback.judge(brief, scope)

    async def _call(self, base: str, key: str, brief: dict[str, Any]) -> ChangeJudgement:
        client = self.client or httpx.AsyncClient(timeout=60)
        schema = ChangeJudgement.model_json_schema()
        response = await client.post(
            f"{base}/chat/completions",
            headers={"Authorization": f"Bearer {key}"},
            json={
                "model": "iris",
                "messages": [
                    {
                        "role": "system",
                        "content": "Judge a regulation change for one AI system. Answer only "
                        f"JSON matching this schema: {json.dumps(schema)}",
                    },
                    {"role": "user", "content": json.dumps(brief, default=str)},
                ],
                "response_format": {"type": "json_object"},
            },
        )
        response.raise_for_status()
        content = response.json()["choices"][0]["message"]["content"]
        return ChangeJudgement.model_validate_json(content)


def decision_model(steps: StepRunner | None = None) -> DecisionModel:
    """The configured judge (``CHANGE_JUDGE_MODEL``)."""
    gemini = GeminiDecisionModel(steps)
    return (
        IrisDecisionModel(fallback=gemini) if settings.pipeline.decision_model == "iris" else gemini
    )


__all__ = [
    "AffectedSystem",
    "DecisionModel",
    "GeminiDecisionModel",
    "IrisDecisionModel",
    "changed_provisions",
    "decision_model",
    "impact_index",
    "judge_brief",
]
