"""The scripted ``classify_risk`` output for ``AGENTS_FAKE_LLM=true`` (no Gemini call).

Reads the same brief the real step gets and answers like a careful model,
citing only ids that are in the brief, so the verifier, Iris and the dates run
for real on it: an Art. 5 flag -> prohibited; an Annex I product -> 6(1); an
Annex III candidate -> 6(3)(a) when the dossier describes only a narrow
structuring task and no profiling, else 6(2); Art. 50 features -> limited;
else minimal.
"""

from __future__ import annotations

from typing import Any

from classification.prechecks import annex_label
from classification.schemas import (
    Art63Assessment,
    CounterArgument,
    ProvisionCheck,
    RiskCitation,
    RiskProposal,
    Transparency,
    Uncertainty,
)

NARROW_WORDS = (
    "only structur",
    "structured format",
    "structured fields",
    "no ranking",
    "without ranking",
    "does not rank",
    "parser",
    "parses",
    "converts",
)


def _text(brief: dict[str, Any]) -> str:
    parts = [str(v) for v in (brief.get("system") or {}).values()]
    parts += [str(d.get("text") or "") for d in brief.get("documents") or []]
    return " ".join(parts).lower()


def classify_risk(brief: dict[str, Any]) -> RiskProposal:
    kb = str(brief.get("kb_version") or "")
    pre = brief.get("prechecks") or {}
    provisions = brief.get("provisions") or {}
    guidance = brief.get("related_guidance") or []
    flags = pre.get("art5_flags") or []
    candidates = pre.get("annex_iii_candidates") or []
    features = list(pre.get("features") or [])
    profiling = str(pre.get("profiling") or "unknown")
    narrow = profiling != "yes" and any(w in _text(brief) for w in NARROW_WORDS)
    role = "deployer" if pre.get("role_hint") == "deployer" else "provider"

    def cite(pid: str, quote: str = "") -> RiskCitation | None:
        if pid not in provisions:
            return None
        text = quote or str(provisions[pid].get("text") or "")
        return RiskCitation(id=pid, kb_version=kb, quote=text[:200])

    cites: list[RiskCitation | None] = [cite("AIA.3.3" if role == "provider" else "AIA.3.4")]
    if pre.get("ai_system_doubt"):
        cites.append(cite("AIA.3.1"))
    screening = [
        ProvisionCheck(provision_id=f["provision"], applies=i == 0, why=f"Matched {f['matched']}.")
        for i, f in enumerate(flags)
    ]
    considered = [
        ProvisionCheck(
            provision_id=c["provision"],
            applies=i == 0,
            why=f"Matched {c['matched']} in the description.",
        )
        for i, c in enumerate(candidates)
    ]
    a63 = Art63Assessment(considered=bool(candidates), profiling=profiling, why="")  # type: ignore[arg-type]
    basis = basis_id = None
    next_steps: list[str] = []
    counter = "The dossier may omit uses that change the class."
    change_to = "high_risk"
    if flags:
        cls, route = "prohibited", "art5"
        cites.append(cite(flags[0]["provision"]))
        why = f"The description matches the practice in {flags[0]['provision']}."
        next_steps.append("Do not place the system on the market; ask legal to confirm.")
        change_to = "high_risk"
    elif (pre.get("annex_i") or {}).get("flag"):
        cls, route = "high_risk", "art6_1_annex_i"
        basis = f"Annex I: {(pre.get('annex_i') or {}).get('product_law')}"
        cites.append(cite("AIA.6.1"))
        why = "It is a safety component of a product under Annex I law (Art. 6(1))."
        next_steps.append("Confirm the product needs third-party conformity assessment.")
        change_to = "minimal_risk"
    elif candidates:
        top = candidates[0]
        cites.append(cite(top["provision"]))
        if narrow:
            cls = "limited_risk" if features else "minimal_risk"
            route = "art6_3_exempt"
            a63 = Art63Assessment(
                considered=True,
                condition="a",
                profiling=profiling,  # type: ignore[arg-type]
                holds=True,
                why="It only structures input data and does not rank, filter or score people.",
            )
            cites += [cite("AIA.6.3"), cite("AIA.6.3.a")]
            for g in guidance:
                if top["provision"] in g.get("relates_to", []) or "AIA.6.3.a" in g.get(
                    "relates_to", []
                ):
                    cites.append(
                        RiskCitation(
                            id=g["id"],
                            kb_version=kb,
                            quote=str(g.get("title") or "")[:200],
                            binding=False,
                            status="draft" if g.get("status") == "draft" else "final",
                        )
                    )
                    break
            why = (
                f"{annex_label(top['point'])} is in play, but the system performs a narrow "
                "procedural task (Art. 6(3)(a)) and does not profile people."
            )
            next_steps += [
                "Document the Art. 6(4) assessment before placing on the market.",
                "Register the system under Art. 49(2).",
            ]
            counter = f"If it filters or ranks people, {annex_label(top['point'])} applies in full."
        else:
            cls, route = "high_risk", "art6_2_annex_iii"
            basis, basis_id = annex_label(top["point"]), top["provision"]
            cites.append(cite("AIA.6.2"))
            a63 = Art63Assessment(
                considered=True,
                profiling=profiling,  # type: ignore[arg-type]
                holds=False,
                why="It informs a decision about people; no 6(3) condition holds.",
            )
            why = f"It is used in the area of {basis} and no Art. 6(3) condition holds."
            next_steps.append("Plan the high-risk provider obligations (Art. 8-17).")
            counter = "If it only performs a narrow procedural task, Art. 6(3)(a) could apply."
            change_to = "minimal_risk"
    elif features:
        cls, route = "limited_risk", "art50_only"
        cites.append(cite("AIA.50.1"))
        why = "No Annex III or Art. 5 use; it interacts with people or generates content."
        change_to = "minimal_risk"
    else:
        cls, route = "minimal_risk", "none"
        why = "No Art. 5 practice, no Annex I product, no Annex III area, no Art. 50 feature."
    transparency = Transparency(
        features=features, provisions=["AIA.50.1"] if features and "AIA.50.1" in provisions else []
    )
    return RiskProposal(
        risk_class=cls,  # type: ignore[arg-type]
        route=route,  # type: ignore[arg-type]
        annex_basis=basis,
        annex_basis_id=basis_id,
        role=role,  # type: ignore[arg-type]
        role_reasoning=f"Hint from how the system was obtained: {pre.get('role_hint')}.",
        art5_screening=screening,
        annex_iii_considered=considered,
        art6_3=a63,
        transparency=transparency,
        reasoning=why,
        counter_arguments=[CounterArgument(argument=counter, would_change_to=change_to)],
        would_change_if=["The system ranks, filters or scores people."],
        uncertainties=[
            Uncertainty(
                question="Is the dossier complete about how outputs are used?",
                why_it_matters="Use in decisions about people changes the class.",
                ask="PM",
            )
        ],
        next_steps=next_steps,
        confidence=0.75,
        citations=[c for c in cites if c is not None],
    )


__all__ = ["classify_risk"]
