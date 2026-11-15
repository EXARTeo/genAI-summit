"""The classifier's code verifier (plan 02 §6.3) and the citation normaliser.

``classification_problems`` returns what is wrong with a proposal (empty = it
passes): citations that do not exist at the pinned kb, an inconsistent class /
route / basis, a 6(3) claim that cannot hold, a pre-check hint left unaddressed,
guidance cited as binding, no counter-argument. The run redoes the step once
with this list as feedback.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from classification.prechecks import KbCache
from classification.schemas import RiskCitation, RiskProposal

HIGH_RISK_ROUTES = {"art6_1_annex_i", "art6_2_annex_iii"}


def _cited(result: RiskProposal, prefix: str) -> bool:
    return any(c.id == prefix or c.id.startswith(prefix + ".") for c in result.citations)


def _citation_problems(
    result: RiskProposal, kb_ids: Mapping[str, Mapping[str, Any] | None]
) -> list[str]:
    problems = []
    for c in result.citations:
        node = kb_ids.get(c.id)
        if node is None:
            problems.append(f"citation {c.id} does not exist at the pinned kb_version")
            continue
        if c.id.startswith("INT."):
            if c.binding:
                problems.append(f"guidance citation {c.id} must be binding: false")
            if str(node.get("status") or "") == "draft" and c.status != "draft":
                problems.append(f"guidance citation {c.id} is a draft: mark it status: draft")
    return problems


def _class_problems(result: RiskProposal) -> list[str]:
    problems = []
    route, cls = result.route, result.risk_class
    if cls == "high_risk":
        if route not in HIGH_RISK_ROUTES:
            problems.append("high_risk needs route art6_1_annex_i or art6_2_annex_iii")
        if not result.annex_basis:
            problems.append("high_risk needs annex_basis")
    elif route in HIGH_RISK_ROUTES:
        problems.append(f"route {route} means risk_class high_risk")
    if route == "art6_2_annex_iii":
        basis = result.annex_basis_id or ""
        if not basis.startswith("AIA.ANNEX_III."):
            problems.append("an Annex III route needs annex_basis_id AIA.ANNEX_III.<point>")
        elif not _cited(result, basis):
            problems.append(f"an Annex III route must cite {basis}")
    if cls == "prohibited" and not _cited(result, "AIA.5.1"):
        problems.append("prohibited must cite an AIA.5.1.* point")
    if (route == "art5") != (cls == "prohibited"):
        problems.append("route art5 and risk_class prohibited go together")
    return problems


def _art63_problems(result: RiskProposal, pre: Mapping[str, Any]) -> list[str]:
    problems = []
    a63 = result.art6_3
    if a63.holds:
        if "yes" in {pre.get("profiling"), a63.profiling}:
            problems.append("Art. 6(3) never holds when the system profiles people")
        if not a63.condition:
            problems.append("Art. 6(3) holds: name the condition (a, b, c or d)")
        if not _cited(result, "AIA.6.3"):
            problems.append("Art. 6(3) holds: cite AIA.6.3")
        if result.risk_class == "high_risk":
            problems.append("Art. 6(3) holds, so risk_class cannot be high_risk")
        if not any(re.search(r"6\(4\)|AIA\.6\.4", s) for s in result.next_steps):
            problems.append("Art. 6(3) holds: next_steps must include the Art. 6(4) assessment")
    if result.route == "art6_3_exempt" and a63.holds is not True:
        problems.append("route art6_3_exempt needs art6_3.holds: true")
    return problems


def _hint_problems(result: RiskProposal, pre: Mapping[str, Any]) -> list[str]:
    problems = []
    screened = {c.provision_id: c for c in result.art5_screening}
    for flag in pre.get("art5_flags") or []:
        row = screened.get(flag["provision"])
        if row is None or not row.why.strip():
            problems.append(
                f"pre-check flag {flag['provision']} is not addressed in art5_screening"
            )
    considered = {c.provision_id: c for c in result.annex_iii_considered}
    for cand in pre.get("annex_iii_candidates") or []:
        row = considered.get(cand["provision"])
        if row is None or not row.why.strip():
            problems.append(
                f"Annex III candidate {cand['provision']} is not addressed in annex_iii_considered"
            )
    if (pre.get("annex_i") or {}).get("flag") and not (
        result.route == "art6_1_annex_i" or _cited(result, "AIA.6.1")
    ):
        problems.append("the Annex I product flag must be addressed (cite AIA.6.1)")
    if pre.get("ai_system_doubt") and not (
        result.route == "not_ai_system" or _cited(result, "AIA.3.1")
    ):
        problems.append("the description shows no learning or inference: address Art. 3(1)")
    return problems


def _transparency_problems(result: RiskProposal, pre: Mapping[str, Any]) -> list[str]:
    """Art. 50 rests on features the card declares, never on features the model assumes."""
    if pre.get("features"):
        return []
    problems = []
    if result.risk_class == "limited_risk" or result.route == "art50_only":
        problems.append(
            "limited_risk / art50_only needs an Art. 50 feature the card declares; it declares "
            "none, so a system exempt under Art. 6(3) or outside Annex III is minimal_risk"
        )
    if result.transparency.features:
        problems.append(
            "transparency.features must list only features the card declares (it declares none)"
        )
    return problems


def classification_problems(
    result: RiskProposal,
    kb_ids: Mapping[str, Mapping[str, Any] | None],
    pre: Mapping[str, Any],
) -> list[str]:
    """Plan 02 §6.3: every problem of a proposal (``kb_ids``: id -> kb node or None)."""
    problems = _citation_problems(result, kb_ids)
    problems += _class_problems(result)
    problems += _art63_problems(result, pre)
    problems += _hint_problems(result, pre)
    problems += _transparency_problems(result, pre)
    if not result.counter_arguments:
        problems.append("give at least one counter_argument")
    if not result.would_change_if:
        problems.append("give at least one would_change_if")
    return problems


def normalise_citations(result: RiskProposal, kb: KbCache) -> list[RiskCitation]:
    """Citations with the kb's facts (kb_version, binding, status), never the model's."""
    out = []
    for c in result.citations:
        node = kb.nodes.get(c.id) or {}
        guidance = c.id.startswith("INT.")
        status = str(node.get("status") or "final") if guidance else "final"
        out.append(
            c.model_copy(
                update={
                    "kb_version": str(node.get("kb_version") or kb.kb_version or c.kb_version),
                    "binding": (node.get("binding") is True) if guidance else True,
                    "status": status if status in {"final", "draft"} else "final",
                }
            )
        )
    return out


__all__ = ["classification_problems", "normalise_citations"]
