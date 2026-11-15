"""The obligation catalogue (``corpus/obligations.yaml``, plan 01 §3.2): schema, load,
cross-checks against a release, and the deterministic activation used by
``GET /v1/obligations``.

Activation is the two-key method of professional AI Act gap analyses (role x
classification, then the in-force date) plus the Annex III point, system features
and the Art. 6(3) claim. The agents' ``pipeline/obligations.py`` applies the same
rules to a system card (and asks Iris on borderline rows); this one answers a query.
"""

from __future__ import annotations

from datetime import date as Date
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field, field_validator

from engine.kb.corpus import CORPUS_DIR

OBLIGATIONS_FILE = "obligations.yaml"

Addressee = Literal["provider", "deployer", "importer", "distributor", "authorised_representative"]
VerificationMode = Literal["model_test", "system_test", "hybrid", "documentary"]
BASIS_FAMILIES = ("annex_iii", "annex_i")


class ObligationAppliesIf(BaseModel):
    risk_class: list[str] = Field(default_factory=list)
    basis_any: list[str] = Field(default_factory=list)
    # Annex III points as "4.a", "5.b" (empty = every point).
    annex_points_any: list[str] = Field(default_factory=list)
    features_any: list[str] = Field(default_factory=list)
    # False = only without an Art. 6(3) claim, True = only with one, None = either way.
    exempt_6_3: bool | None = None


class ObligationCheck(BaseModel):
    metric_family: str
    templates: list[str] = Field(default_factory=list)
    threshold_source: str = "org_thresholds"


class Obligation(BaseModel):
    id: str = Field(pattern=r"^OBL\.AIA\.[0-9A-Za-z_.]+\.[a-z0-9-]+$")
    article: str
    related: list[str] = Field(default_factory=list)
    addressee: list[Addressee]
    applies_if: ObligationAppliesIf = Field(default_factory=ObligationAppliesIf)
    # basis family (annex_iii, annex_i) or "any" -> ISO date.
    in_force: dict[str, str]
    verification_mode: VerificationMode
    checks: list[ObligationCheck] = Field(default_factory=list)
    evidence_types: list[str] = Field(default_factory=list)
    requirements: list[str] = Field(default_factory=list)
    severity_rule: str = "by_in_force_date"
    summary: str
    provenance: str = "drafted_by_agent"
    review: Literal["pending", "accepted", "rejected"] = "pending"

    @field_validator("in_force", mode="before")
    @classmethod
    def _dates(cls, value: Any) -> Any:
        if not isinstance(value, dict) or not value:
            raise ValueError("in_force needs at least one basis -> date")
        out = {}
        for key, day in value.items():
            if key not in (*BASIS_FAMILIES, "any"):
                raise ValueError(f"in_force key {key!r} is not annex_iii, annex_i or any")
            out[key] = Date.fromisoformat(str(day)).isoformat()
        return out


def load_obligations(corpus_dir: Path = CORPUS_DIR) -> list[dict[str, Any]]:
    """The catalogue as validated plain dicts (``[]`` when the file is missing)."""
    path = Path(corpus_dir) / OBLIGATIONS_FILE
    if not path.exists():
        return []
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or []
    items = [Obligation.model_validate(o).model_dump() for o in raw]
    seen: set[str] = set()
    for o in items:
        if o["id"] in seen:
            raise ValueError(f"duplicate obligation id {o['id']}")
        seen.add(o["id"])
    return items


def check_obligations(
    obligations: list[dict[str, Any]],
    provision_ids: set[str],
    template_ids: set[str],
    requirement_ids: set[str],
) -> list[str]:
    """Cross-reference warnings: unknown provisions, templates, requirements; requirements
    no obligation covers."""
    warnings: list[str] = []
    covered: set[str] = set()
    for o in obligations:
        for pid in [o["article"], *o["related"]]:
            if pid not in provision_ids:
                warnings.append(f"{o['id']}: unknown provision {pid}")
        for check in o["checks"]:
            for tid in check["templates"]:
                if tid not in template_ids:
                    warnings.append(f"{o['id']}: unknown test template {tid}")
        for rid in o["requirements"]:
            if rid not in requirement_ids:
                warnings.append(f"{o['id']}: unknown requirement {rid}")
            covered.add(rid)
    if obligations:
        for rid in sorted(requirement_ids - covered):
            warnings.append(f"requirement {rid} is covered by no obligation")
    return warnings


# ---- activation ---------------------------------------------------------------------------


def basis_parts(basis: str | None) -> tuple[str | None, str | None]:
    """``AIA.ANNEX_III.4.a`` / ``Annex III 4(a)`` / ``annex_iii`` -> (family, point)."""
    if not basis:
        return None, None
    b = basis.strip()
    upper = b.upper().replace(" ", "_")
    if "ANNEX_III" in upper:
        family = "annex_iii"
        tail = upper.split("ANNEX_III", 1)[1].strip("._")
    elif "ANNEX_I" in upper:
        family, tail = "annex_i", ""
    else:
        return b.lower(), None
    point = None
    if tail:
        tail = tail.replace("(", ".").replace(")", "").replace("_", ".").strip(".")
        bits = [t for t in tail.split(".") if t]
        if bits:
            point = ".".join([bits[0], *[x.lower() for x in bits[1:2]]])
    return family, point


def in_force_date(obligation: dict[str, Any], family: str | None) -> str | None:
    dates = obligation.get("in_force") or {}
    return dates.get(family or "") or dates.get("any") or (min(dates.values()) if dates else None)


def activate(
    obligation: dict[str, Any],
    *,
    role: str | None,
    risk_class: str | None,
    basis: str | None,
    features: list[str] | None,
    exempt_6_3: bool | None,
    on: Date,
) -> dict[str, Any]:
    """One catalogue row against a query -> ``{applicable, reason, in_force_date, in_force_now}``.

    ``None`` inputs are "not given": the condition is not checked (a catalogue browse)."""
    cond = obligation.get("applies_if") or {}
    family, point = basis_parts(basis)
    reasons: list[str] = []
    applicable = True
    if role and role not in obligation["addressee"]:
        applicable = False
        reasons.append(f"addressed to {'/'.join(obligation['addressee'])}, system role is {role}")
    if cond.get("risk_class") and risk_class and risk_class not in cond["risk_class"]:
        applicable = False
        reasons.append(f"needs risk class {'/'.join(cond['risk_class'])}, got {risk_class}")
    if cond.get("basis_any") and family and family not in cond["basis_any"]:
        applicable = False
        reasons.append(f"needs basis {'/'.join(cond['basis_any'])}, got {family}")
    if cond.get("annex_points_any") and point and point not in cond["annex_points_any"]:
        applicable = False
        reasons.append(f"needs Annex III point {'/'.join(cond['annex_points_any'])}, got {point}")
    gated = cond.get("features_any") or []
    if gated and features is not None and not set(features) & set(gated):
        applicable = False
        reasons.append(f"needs a feature of {'/'.join(gated)}")
    want = cond.get("exempt_6_3")
    if want is not None and exempt_6_3 is not None and bool(exempt_6_3) != want:
        applicable = False
        reasons.append(
            "applies only with an Art. 6(3) claim" if want else "Art. 6(3) derogation claimed"
        )
    starts = in_force_date(obligation, family)
    if applicable:
        reasons.append("conditions met")
    return {
        "applicable": applicable,
        "reason": "; ".join(reasons),
        "in_force_date": starts,
        "in_force_now": bool(starts and Date.fromisoformat(starts) <= on),
    }


__all__ = [
    "OBLIGATIONS_FILE",
    "Obligation",
    "activate",
    "basis_parts",
    "check_obligations",
    "in_force_date",
    "load_obligations",
]
