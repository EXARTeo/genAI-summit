"""Scenario relevance review: the decision model judges each planned scenario for this system.

Runs in ``analyse_scenarios`` (after ``plan_scenarios``, before the Approve
scenarios gate). For each scenario the decision model (Oumi *Iris* by default,
``SCENARIO_REVIEW_MODEL``) sees the system card (risk class, intended purpose,
components), the plugin card, the model profile's detected proxies, the
applicable requirements and the scenario, and returns a
:class:`~pipeline.schemas.ScenarioReview`. The pipeline stores it on the
scenario as ``review: {model, verdict, rationale, suggested_change, confidence}``
(a contract shared with the frontend).

Iris writes no text: it answers the ``verdict`` choice plus four yes/no checks
(``prompts/decisions/scenario_review.yaml``); the rationale quotes those
probabilities and the suggested change is the fix of each failed check.
"""

from __future__ import annotations

from typing import Any

import yaml

from pipeline.decision import DecisionTask, choice_confidence, load_questions
from pipeline.schemas import ScenarioReview

#: Longest requirement obligation text sent to the decision model.
MAX_OBLIGATION = 240
#: Most requirements sent per review.
MAX_REQUIREMENTS = 30


def _yaml(text: str | None) -> dict[str, Any]:
    data = yaml.safe_load(text or "") if text else None
    return data if isinstance(data, dict) else {}


def review_context(state: dict[str, Any], profile_proxies: Any) -> dict[str, Any]:
    """What every review of this audit shares: system, plugin, profile, requirements."""
    card = state.get("card") or {}
    plugin = _yaml((state.get("files") or {}).get("plugin.yaml"))
    return {
        "system": {
            k: card.get(k)
            for k in (
                "id",
                "name",
                "risk_class",
                "annex_basis",
                "intended_purpose",
                "components",
                "protected_attributes",
                "known_proxies",
            )
        },
        "plugin": {
            "id": plugin.get("id") or state.get("target"),
            "access": (plugin.get("access") or {}).get("type"),
            "placement": plugin.get("placement"),
            "io": plugin.get("io"),
            "expected_behaviour": plugin.get("expected_behaviour"),
            "input_fields": sorted(
                (_yaml((state.get("files") or {}).get("data/data-dictionary.yaml")).get("fields"))
                or {}
            ),
        },
        "model_profile": {
            "proxies": profile_proxies,
            "protected": ((state.get("profile") or {}).get("protected")),
        },
        "applicable_requirements": [
            {
                "id": r.get("id"),
                "testability": r.get("testability"),
                "obligation": str(r.get("obligation") or "")[:MAX_OBLIGATION],
            }
            for r in (state.get("requirements") or [])[:MAX_REQUIREMENTS]
        ],
    }


def review_brief(context: dict[str, Any], scenario: dict[str, Any]) -> dict[str, Any]:
    """The brief of one review: the shared context plus the scenario (no prior review)."""
    return {**context, "scenario": {k: v for k, v in scenario.items() if k != "review"}}


def _iris_request(brief: dict[str, Any]) -> tuple[Any, dict[str, Any]]:
    spec = load_questions("scenario_review")
    questions: dict[str, Any] = {"verdict": spec["verdict"]}
    for name, check in (spec.get("checks") or {}).items():
        questions[name] = {
            "type": "noul",
            "instructions": check["instructions"],
            "criteria": check["criteria"],
        }
    return brief, questions


def _from_iris(answers: dict[str, Any], brief: dict[str, Any]) -> ScenarioReview:
    spec = load_questions("scenario_review")
    verdict_answer = answers["verdict"]
    verdict = verdict_answer["choice"]
    probs = verdict_answer.get("probabilities") or {}
    checks = {
        name: float(answers[name]["noul"]) for name in (spec.get("checks") or {}) if name in answers
    }
    failed = [name for name, p in checks.items() if p < 0.5]
    shown = ", ".join(f"{name} {p:.2f}" for name, p in checks.items())
    rationale = (
        f"Iris: {verdict} (p={float(probs.get(verdict, 0) or 0):.2f}). "
        f"Checks P(yes): {shown or 'none'}."
    )
    if failed:
        rationale += f" Failed: {', '.join(failed)}."
    suggested = None
    if verdict == "needs_change":
        fixes = [spec["checks"][name]["fix"] for name in failed] or [
            "Tighten the scenario to the requirement, the plugin's fields and the detected proxies."
        ]
        suggested = " ".join(fixes)
    return ScenarioReview(
        verdict=verdict,
        rationale=rationale,
        suggested_change=suggested,
        confidence=choice_confidence(verdict_answer),
    )


def fake_review(brief: dict[str, Any]) -> ScenarioReview:
    """Deterministic review under ``AGENTS_FAKE_LLM``: requirement and proxy checks by rule."""
    scenario = brief.get("scenario") or {}
    requirement = scenario.get("requirement")
    applicable = {r.get("id") for r in brief.get("applicable_requirements") or []}
    if applicable and requirement not in applicable:
        return ScenarioReview(
            verdict="not_relevant",
            rationale=f"{requirement} is not among this system's applicable requirements.",
            confidence=0.8,
        )
    protected = set(scenario.get("protected") or [])
    proxies = _proxy_names((brief.get("model_profile") or {}).get("proxies"), protected)
    modes = set((scenario.get("data_needs") or {}).get("twin_modes") or [])
    covered = set(scenario.get("proxies") or [])
    missing = sorted(p for p in proxies if p not in covered) if protected else []
    if scenario.get("template") == "counterfactual_twins" and (
        missing or (proxies and "proxy_only" not in modes)
    ):
        names = ", ".join(missing or sorted(proxies))
        return ScenarioReview(
            verdict="needs_change",
            rationale=f"The profile detected proxies ({names}) this scenario does not cover.",
            suggested_change=f"Add {names} with causal and proxy_only twin modes.",
            confidence=0.7,
        )
    return ScenarioReview(
        verdict="relevant",
        rationale=f"Tests {requirement} on {scenario.get('target')} with {scenario.get('metric')}.",
        confidence=0.9,
    )


def _proxy_names(proxies: Any, protected: set[str]) -> set[str]:
    """Detected proxies for ``protected`` (synthkit's ``{field: {proxy_for, ...}}`` or a list)."""
    if isinstance(proxies, dict):
        return {
            str(name)
            for name, info in proxies.items()
            if not isinstance(info, dict)
            or not info.get("proxy_for")
            or protected & set(info.get("proxy_for") or [])
        }
    return {str(p) for p in proxies or [] if isinstance(p, str)}


SCENARIO_REVIEW: DecisionTask[ScenarioReview] = DecisionTask(
    name="scenario_review",
    step="scenario_review",
    iris_request=_iris_request,
    from_iris=_from_iris,
    fake=fake_review,
    verdict=lambda r: r.verdict,
)


__all__ = ["SCENARIO_REVIEW", "fake_review", "review_brief", "review_context"]
