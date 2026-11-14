"""Which requirements apply to a system (the ``load_context`` query, PDF §12.5).

Inputs come from the system card: role (provider/deployer), risk class, risk
basis (``AIA.ANNEX_III.4.a`` or a family ``annex_iii`` / ``annex_i``), a date
and optional features (``interacts_with_persons``, ``generates_synthetic_content``,
...). Each match says whether it is already in force on that date.
"""

from __future__ import annotations

from datetime import date as Date
from typing import Any


def basis_family(basis: str | None) -> str | None:
    if not basis:
        return None
    b = basis.strip().upper()
    if "ANNEX_III" in b or b in {"ANNEX III", "ANNEX_III"}:
        return "annex_iii"
    if "ANNEX_I" in b or b in {"ANNEX I", "ANNEX_I"}:
        return "annex_i"
    return basis.strip().lower()


def applicable(
    requirements: list[dict[str, Any]],
    *,
    role: str | None = None,
    risk_class: str | None = None,
    basis: str | None = None,
    on: Date | None = None,
    features: list[str] | None = None,
) -> list[dict[str, Any]]:
    family = basis_family(basis)
    feats = set(features or [])
    out: list[dict[str, Any]] = []
    for r in requirements:
        cond = r.get("applies_if") or {}
        if role and r.get("actor") != role:
            continue
        if cond.get("risk_class") and (not risk_class or risk_class not in cond["risk_class"]):
            continue
        if cond.get("basis") and family and family not in cond["basis"]:
            continue
        if cond.get("features_any") and not feats & set(cond["features_any"]):
            continue
        by_basis = r.get("valid_from_by_basis") or {}
        valid_from = by_basis.get(family or "", r.get("valid_from"))
        in_force = None
        if on and valid_from:
            in_force = Date.fromisoformat(valid_from) <= on
        out.append({**r, "effective_valid_from": valid_from, "in_force": in_force})
    return out
