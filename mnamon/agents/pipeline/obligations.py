"""The system obligation map (plan 01 §3.3): which catalogue obligations apply to a system.

``resolve_obligation_map(card, kb_version, *, iris=None)`` takes the system card and the
obligation catalogue at ``kb_version`` (reg-memory ``GET /v1/obligations``, snapshotted per
release) and returns one entry per catalogue row::

    {obligation_id, article, related[], applicable, reason, in_force_date, in_force_now,
     verification_mode, checks[], decided_by: rule | iris, borderline, summary,
     requirements[], evidence_types[]}

Deterministic rules first: role x risk class x basis family x Annex III point x features x
the Art. 6(3) claim x the in-force date. Iris (an injected ``IrisClient``-like object with
``async ask(state, questions)``) decides only the **borderline** rows:

* the card claims the Art. 6(3) derogation: does it hold? (one yes/no question; rows gated
  on the claim follow the answer);
* a features-gated row (Art. 50) and the card declares no ``features``: does the system
  interact with people / generate synthetic content? (one yes/no question per feature group).

Without Iris (or when Iris fails) the rule default stands and the row says so: an
unverified 6(3) claim keeps the high-risk duties *and* the 6(4) documentation duty
(conservative); undeclared features do not trigger Art. 50. No network here except the
optional catalogue fetch, which tests replace with ``catalogue=``.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from datetime import date as Date
from typing import Any, Protocol

from core.logging import get_logger
from pipeline.clients import RegMemory

logger = get_logger(__name__)

_ANNEX_RE = re.compile(
    r"annex[\s_]*(iii|ii|i)\b(?:[\s._]*(\d+)(?:\s*[.(]\s*([a-z])\b)?)?", re.IGNORECASE
)
_CLAIM_KEYS = ("exempt_6_3", "art_6_3_claim", "derogation_6_3", "art_6_3")
_IRIS_THRESHOLD = 0.5

#: Plain-language yes/no questions for the feature groups the catalogue gates on.
FEATURE_QUESTIONS: dict[str, tuple[tuple[str, ...], str]] = {
    "interacts_with_persons": (
        ("interacts_with_persons", "chatbot"),
        "Does the AI system interact directly with natural persons (they converse with it or "
        "receive its output as if from a counterpart), as meant by AI Act Art. 50(1)?",
    ),
    "generates_synthetic_content": (
        ("generates_synthetic_content",),
        "Does the AI system generate synthetic audio, image, video or text content, as meant by "
        "AI Act Art. 50(2)?",
    ),
}
CLAIM_QUESTION = (
    "The provider claims the Art. 6(3) derogation for this Annex III system. Given its "
    "intended purpose, does the system only perform a narrow procedural task, improve a "
    "completed human activity, detect decision patterns without replacing the human "
    "assessment, or perform a preparatory task, AND does it not profile natural persons?"
)


class IrisLike(Protocol):
    async def ask(self, state: Any, questions: dict[str, Any]) -> dict[str, Any]: ...


# ---- the card -> a profile -----------------------------------------------------------------


def card_profile(card: dict[str, Any]) -> dict[str, Any]:
    """The activation inputs from a system card (``None`` = not declared)."""
    role = str(card.get("role") or "").strip().lower() or None
    raw_risk = str(card.get("risk_class") or "").strip().lower()
    risk = "high" if raw_risk.startswith("high") else (raw_risk or None)
    family, point = None, None
    m = _ANNEX_RE.search(str(card.get("annex_basis") or card.get("basis") or ""))
    if m:
        family = {"iii": "annex_iii", "i": "annex_i"}.get(m.group(1).lower())
        if family == "annex_iii" and m.group(2):
            point = m.group(2) + (f".{m.group(3).lower()}" if m.group(3) else "")
    features = card.get("features")
    feats = [str(f) for f in features] if isinstance(features, list) else None
    claim = next((card[k] for k in _CLAIM_KEYS if k in card), None)
    if isinstance(claim, dict):
        claim = claim.get("claimed")
    return {
        "role": role,
        "risk_class": risk,
        "basis": family,
        "annex_point": point,
        "features": feats,
        "claims_6_3": bool(claim) if claim is not None else False,
    }


def _in_force(row: dict[str, Any], family: str | None) -> str | None:
    dates = {k: str(v) for k, v in (row.get("in_force") or {}).items()}
    return dates.get(family or "") or dates.get("any") or (min(dates.values()) if dates else None)


# ---- deterministic activation ---------------------------------------------------------------


def activate_rows(
    card: dict[str, Any], catalogue: list[dict[str, Any]], *, on: Date | None = None
) -> list[dict[str, Any]]:
    """The rule pass: one map entry per catalogue row, borderline rows flagged."""
    on = on or datetime.now(UTC).date()
    p = card_profile(card)
    out: list[dict[str, Any]] = []
    for row in catalogue:
        cond = row.get("applies_if") or {}
        reasons: list[str] = []
        applicable = True
        borderline = False
        addressee = list(row.get("addressee") or [])
        if addressee and p["role"] not in addressee:
            applicable = False
            reasons.append(f"addressed to {'/'.join(addressee)}; the system role is {p['role']}")
        if cond.get("risk_class") and p["risk_class"] not in cond["risk_class"]:
            applicable = False
            reasons.append(f"needs risk class {'/'.join(cond['risk_class'])}")
        if cond.get("basis_any") and p["basis"] not in cond["basis_any"]:
            applicable = False
            reasons.append(f"needs basis {'/'.join(cond['basis_any'])}; got {p['basis']}")
        points = cond.get("annex_points_any") or []
        if points and p["annex_point"] not in points:
            applicable = False
            reasons.append(f"needs Annex III point {'/'.join(points)}; got {p['annex_point']}")
        gated = list(cond.get("features_any") or [])
        feature_group = None
        if gated and applicable:
            if p["features"] is None:
                feature_group = next(
                    (g for g, (keys, _) in FEATURE_QUESTIONS.items() if set(keys) & set(gated)),
                    None,
                )
                borderline = feature_group is not None
                applicable = False
                reasons.append(
                    f"needs a feature of {'/'.join(gated)}; the card declares no features"
                )
            elif not set(p["features"]) & set(gated):
                applicable = False
                reasons.append(f"needs a feature of {'/'.join(gated)}")
            else:
                reasons.append(f"feature {sorted(set(p['features']) & set(gated))[0]}")
        want = cond.get("exempt_6_3")
        claim_gated = want is not None
        if claim_gated and applicable:
            if p["claims_6_3"]:
                borderline = True  # applicable either way until the claim is verified
                reasons.append("Art. 6(3) derogation claimed, not verified")
            elif want is True:
                applicable = False
                reasons.append("applies only with an Art. 6(3) claim; none on the card")
        starts = _in_force(row, p["basis"])
        if applicable and not reasons:
            reasons.append("role, risk class and basis match")
        out.append(
            {
                "obligation_id": row["id"],
                "article": row.get("article"),
                "related": list(row.get("related") or []),
                "applicable": applicable,
                "reason": "; ".join(reasons),
                "in_force_date": starts,
                "in_force_now": bool(starts and Date.fromisoformat(starts) <= on),
                "verification_mode": row.get("verification_mode"),
                "checks": list(row.get("checks") or []),
                "decided_by": "rule",
                "borderline": borderline,
                "summary": row.get("summary"),
                "requirements": list(row.get("requirements") or []),
                "evidence_types": list(row.get("evidence_types") or []),
                "_feature_group": feature_group,
                "_claim_gate": want if claim_gated and p["claims_6_3"] else None,
            }
        )
    return out


# ---- Iris on the borderline rows ------------------------------------------------------------


def iris_questions(
    card: dict[str, Any], entries: list[dict[str, Any]]
) -> tuple[dict[str, Any], dict[str, Any]]:
    """``(state, questions)`` for the borderline rows (``{}`` questions = nothing to ask)."""
    questions: dict[str, Any] = {}
    if any(e["_claim_gate"] is not None for e in entries):
        questions["derogation_6_3_holds"] = {
            "type": "noul",
            "instructions": CLAIM_QUESTION,
            "criteria": {
                "true": "The derogation holds: the system is not high-risk.",
                "false": "The derogation does not hold: the system stays high-risk.",
            },
        }
    for group in sorted({e["_feature_group"] for e in entries if e["_feature_group"]}):
        questions[f"feature_{group}"] = {
            "type": "noul",
            "instructions": FEATURE_QUESTIONS[group][1],
            "criteria": {"true": "Yes, it does.", "false": "No, it does not."},
        }
    state = {
        "system": {
            k: card.get(k)
            for k in (
                "id",
                "name",
                "intended_purpose",
                "annex_basis",
                "risk_class",
                "role",
                "affected_persons",
                "human_oversight",
                "deployment",
            )
        }
    }
    return state, questions


def apply_iris(entries: list[dict[str, Any]], answers: dict[str, Any]) -> None:
    """Rewrite the borderline rows from Iris's yes/no probabilities (in place)."""
    claim = answers.get("derogation_6_3_holds")
    for e in entries:
        if e["_claim_gate"] is not None and isinstance(claim, dict):
            p = float(claim["noul"])
            holds = p >= _IRIS_THRESHOLD
            # want=False rows apply only without the derogation; want=True only with it.
            e["applicable"] = holds if e["_claim_gate"] else not holds
            e["reason"] = (
                f"Iris: the Art. 6(3) derogation {'holds' if holds else 'does not hold'} "
                f"(p={p:.2f})"
            )
            e["decided_by"] = "iris"
        group = e["_feature_group"]
        answer = answers.get(f"feature_{group}") if group else None
        if isinstance(answer, dict):
            p = float(answer["noul"])
            e["applicable"] = p >= _IRIS_THRESHOLD
            said = "yes" if e["applicable"] else "no"
            e["reason"] = f"Iris: {group.replace('_', ' ')} = {said} (p={p:.2f})"
            e["decided_by"] = "iris"


def _clean(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{k: v for k, v in e.items() if not k.startswith("_")} for e in entries]


async def fetch_catalogue(kb_version: str | None, regmem: RegMemory | None = None) -> list[dict]:
    """Every catalogue row at ``kb_version`` (reg-memory, no profile filter)."""
    regmem = regmem or RegMemory()
    body = await regmem._get(  # noqa: SLF001 - the shared reg-memory client, one more route
        "/v1/obligations", kb_version=kb_version, include_not_applicable="true"
    )
    return list(body.get("items") or []) if isinstance(body, dict) else []


async def resolve_obligation_map(
    card: dict[str, Any],
    kb_version: str | None,
    *,
    iris: IrisLike | None = None,
    catalogue: list[dict[str, Any]] | None = None,
    regmem: RegMemory | None = None,
    on: Date | None = None,
) -> list[dict[str, Any]]:
    """The obligation map of one system at ``kb_version`` (see the module docstring)."""
    rows = catalogue if catalogue is not None else await fetch_catalogue(kb_version, regmem)
    entries = activate_rows(card, rows, on=on)
    if iris is not None:
        state, questions = iris_questions(card, entries)
        if questions:
            try:
                answers = await iris.ask(state, questions)
                apply_iris(entries, answers)
            except Exception as exc:  # Iris is a second opinion: the rule default stands
                failure = type(exc).__name__ if not str(exc) else str(exc)[:80]
                for e in entries:
                    if e["borderline"]:
                        e["reason"] += f" (Iris unavailable: {failure}; rule default kept)"
                logger.warning(
                    "obligation_map_iris_failed",
                    "Iris could not decide the borderline obligations; rule defaults kept",
                    system_id=card.get("id"),
                    failure_reason=failure,
                )
    out = _clean(entries)
    logger.info(
        "obligation_map_resolved",
        "Obligation map resolved",
        system_id=card.get("id"),
        kb_version=kb_version,
        applicable=sum(1 for e in out if e["applicable"]),
        borderline=sum(1 for e in out if e["borderline"]),
        by_iris=sum(1 for e in out if e["decided_by"] == "iris"),
    )
    return out


def applicable_ids(entries: list[dict[str, Any]]) -> list[str]:
    return [e["obligation_id"] for e in entries if e["applicable"]]


__all__ = [
    "activate_rows",
    "applicable_ids",
    "apply_iris",
    "card_profile",
    "fetch_catalogue",
    "iris_questions",
    "resolve_obligation_map",
]
