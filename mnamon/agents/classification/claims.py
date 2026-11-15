"""Article-level claims Iris checks one by one (yes/no), next to the overall class.

Code builds the claims from the agent's :class:`RiskProposal`, the pre-checks and
the brief's provisions: every Annex III point, Art. 5 practice, Art. 6(3)
condition, Art. 50 paragraph, the role, the Annex I route, the premises the
conclusion rests on and every counter-argument (which the agent rejected). Each
becomes one ``noul`` question under a safe key (``c01``, ``c02``...) in the same
single ``iris.ask`` call; the answers are mapped back here.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from classification.schemas import IrisClaim, IrisSummary, RiskProposal

#: Most claims sent to Iris in one call.
MAX_CLAIMS = 20
#: Iris P(true) below this on an agent "true" (or above 1 - this on a "false") is strong.
STRONG_MARGIN = 0.25

ART63_CONDITIONS = {
    "a": "narrow procedural task",
    "b": "improve the result of a previously completed human activity",
    "c": "detect decision-making patterns without replacing human assessment",
    "d": "preparatory task to an assessment",
}
ART50_PARAGRAPHS = {
    "AIA.50.1": "interacts directly with natural persons",
    "AIA.50.2": "generates synthetic audio, image, video or text content",
    "AIA.50.3": "emotion recognition or biometric categorisation",
    "AIA.50.4": "generates or manipulates deep fakes",
}
PROFILING_STATEMENT = "The system profiles natural persons (GDPR Art. 4(4))"


def _point(pid: str) -> str:
    """``AIA.ANNEX_III.4.a`` -> ``4(a)``; ``AIA.5.1.f`` -> ``5(1)(f)``."""
    parts = pid.removeprefix("AIA.").removeprefix("ANNEX_III.").split(".")
    return parts[0] + "".join(f"({p})" for p in parts[1:])


def build_claims(
    proposal: RiskProposal, pre: Mapping[str, Any], provisions: Mapping[str, Any]
) -> list[IrisClaim]:
    """The claims in priority order, capped at :data:`MAX_CLAIMS` (Iris fields empty)."""
    out: list[IrisClaim] = []

    def add(key: str, group: str, statement: str, agent: bool, pid: str | None = None) -> None:
        out.append(
            IrisClaim(key=key, group=group, provision_id=pid, statement=statement, agent=agent)  # type: ignore[arg-type]
        )

    a63 = proposal.art6_3
    if a63.considered:
        if a63.condition:
            what = ART63_CONDITIONS[a63.condition]
            add(
                "art6_3:condition",
                "art6_3",
                f"The Art. 6(3)({a63.condition}) condition ({what}) holds",
                bool(a63.holds),
                f"AIA.6.3.{a63.condition}",
            )
        else:
            add(
                "art6_3:condition",
                "art6_3",
                "One of the Art. 6(3)(a)-(d) conditions holds",
                bool(a63.holds),
                "AIA.6.3",
            )
    add("art6_3:profiling", "art6_3", PROFILING_STATEMENT, a63.profiling == "yes", "AIA.6.3")

    def annex_iii(applies: bool) -> None:
        for row in proposal.annex_iii_considered:
            if row.applies is applies:
                add(
                    f"annex_iii:{row.provision_id}",
                    "annex_iii",
                    f"Annex III {_point(row.provision_id)} applies to this system",
                    row.applies,
                    row.provision_id,
                )

    annex_iii(True)

    add(
        "role",
        "role",
        "The organisation is the provider of this system (Art. 3(3)), not only a deployer",
        proposal.role == "provider",
        "AIA.3.3",
    )
    if (pre.get("annex_i") or {}).get("flag") or proposal.route == "art6_1_annex_i":
        add(
            "annex_i",
            "annex_i",
            "The system is a safety component of a product under Annex I law",
            proposal.route == "art6_1_annex_i",
            "AIA.6.1",
        )

    for row in proposal.art5_screening:
        add(
            f"art5:{row.provision_id}",
            "art5",
            f"The system engages in the practice of Art. {_point(row.provision_id)}",
            row.applies,
            row.provision_id,
        )

    declared = set(proposal.transparency.provisions)
    in_play = {"AIA.50.1", "AIA.50.2"} | set(provisions) | declared
    for pid, what in ART50_PARAGRAPHS.items():
        if pid in in_play:
            add(
                f"art50:{pid}",
                "art50",
                f"Art. {_point(pid)} applies ({what})",
                pid in declared,
                pid,
            )

    annex_iii(False)
    add(
        "assumption:ai_system",
        "assumption",
        "The system is an AI system under Art. 3(1)",
        proposal.route != "not_ai_system",
        "AIA.3.1",
    )
    if proposal.route == "art6_3_exempt":
        add(
            "assumption:no_ranking",
            "assumption",
            "The system does not rank, score, filter or reject people",
            True,
            "AIA.6.3",
        )

    for i, counter in enumerate(proposal.counter_arguments, start=1):
        add(f"counter:{i}", "counter", f"This counter-argument holds: {counter.argument}", False)
    return out[:MAX_CLAIMS]


def claim_key(index: int) -> str:
    return f"c{index + 1:02d}"


def claim_questions(claims: list[IrisClaim]) -> dict[str, dict[str, Any]]:
    """One ``noul`` question per claim under ``c01``, ``c02``... (parameters, not prose)."""
    return {
        claim_key(i): {
            "type": "noul",
            "instructions": (
                f"Claim [{c.provision_id or c.group}]: {c.statement}. "
                "Is it true for this `system`, judged from `system` and `provisions`?"
            ),
        }
        for i, c in enumerate(claims)
    }


def fold_answers(claims: list[IrisClaim], answers: Mapping[str, Any]) -> list[IrisClaim]:
    """The claims with Iris's P(true), agreement and strong disagreement filled in."""
    out = []
    for i, claim in enumerate(claims):
        raw = (answers.get(claim_key(i)) or {}).get("noul")
        if not isinstance(raw, (int, float)):
            out.append(claim)
            continue
        p = max(0.0, min(1.0, float(raw)))
        strong = (claim.agent and p < STRONG_MARGIN) or (not claim.agent and p > 1 - STRONG_MARGIN)
        out.append(
            claim.model_copy(
                update={
                    "iris": p,
                    "agrees": (p >= 0.5) == claim.agent,
                    "strong_disagreement": strong,
                }
            )
        )
    return out


def summarise(claims: list[IrisClaim]) -> IrisSummary:
    checked = [c for c in claims if c.agrees is not None]
    agree = sum(1 for c in checked if c.agrees)
    return IrisSummary(checked=len(checked), agree=agree, disagree=len(checked) - agree)


def claim_reasons(claims: list[IrisClaim]) -> list[str]:
    """One ``needs_human`` reason per strong disagreement (a weak one adds none)."""
    return [
        f"Iris disagrees: {c.statement} (P={c.iris:.2f})"
        for c in claims
        if c.strong_disagreement and c.iris is not None
    ]


def profiling_p(claims: list[IrisClaim]) -> float | None:
    return next((c.iris for c in claims if c.key == "art6_3:profiling"), None)


__all__ = [
    "MAX_CLAIMS",
    "build_claims",
    "claim_questions",
    "claim_reasons",
    "fold_answers",
    "profiling_p",
    "summarise",
]
