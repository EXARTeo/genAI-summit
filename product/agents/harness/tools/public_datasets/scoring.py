"""Deterministic match scoring: public dataset vs one plugin's data dictionary.

Score in [0, 1] = weighted sum of: schema coverage (model fields mapped), protected
and proxy fields present, label match, task match, size, licence, recency. Every
part is in ``breakdown`` so the human sees why a candidate ranks where it does.
No LLM here; :mod:`rerank` may add an explanation on top.
"""

from __future__ import annotations

import difflib
import math
import re
from datetime import UTC, datetime
from typing import Any

from harness.tools.public_datasets.context import DOMAINS, domains_for
from harness.tools.public_datasets.models import Candidate, Column, Field, SystemContext

WEIGHTS = {
    "schema": 0.30,
    "protected": 0.15,
    "label": 0.15,
    "relevance": 0.10,
    "task": 0.10,
    "size": 0.05,
    "licence": 0.10,
    "recency": 0.05,
}
MATCH_THRESHOLD = 0.55

#: Common column names for our dictionary fields (on top of a field's own ``synonyms``).
SYNONYMS: dict[str, list[str]] = {
    "sex": ["sex", "gender", "personal status", "personal status and sex"],
    "age_band": ["age", "age years", "age group", "age band"],
    "age": ["age", "age years"],
    "nationality": [
        "nationality",
        "native country",
        "foreign worker",
        "citizenship",
        "country of birth",
    ],
    "monthly_income": ["income", "monthly income", "salary", "wage", "earnings"],
    "employment_years": ["employment", "present employment", "years employed", "employment since"],
    "credit_history_months": ["credit history length", "months since first credit"],
    "debt_to_income": ["installment commitment", "installment rate", "dti", "debt ratio"],
    "late_payments_12m": ["late payments", "delinquencies", "past due"],
    "loan_amount": ["credit amount", "loan amount", "amount"],
    "loan_term_months": ["duration", "loan term", "term", "duration months"],
    "employment_status": ["workclass", "employment status", "employment type"],
    "household_size": ["household size", "family size", "persons in household"],
    "dependents_under_18": ["dependents", "num dependents", "children", "people liable"],
    "disability": ["disability", "disabled", "handicap"],
    "region": ["region", "state", "area", "province"],
    "education_level": ["education", "education level", "degree", "highest degree"],
    "years_experience": ["experience", "years experience", "years of experience", "years code"],
    "career_gap_months": ["career gap", "employment gap"],
    "skills_match": ["skills", "skill match", "skills score"],
    "languages": ["languages", "num languages"],
    "postcode_region": ["postcode", "zip", "zipcode", "postal code", "residence area"],
}
LABEL_SYNONYMS: dict[str, list[str]] = {
    "repaid": ["class", "credit risk", "risk", "default", "good bad", "loan status", "target"],
    "decision": ["class", "approved", "decision", "target"],
    "qualified": ["hired", "selected", "shortlisted", "qualified", "class", "target"],
    "shortlist": ["hired", "selected", "shortlisted", "class", "target"],
    "fast_track": ["eligible", "income", "class", "target"],
    "eligible": ["eligible", "income", "class", "target"],
}
ALLOWED_LICENCES = {
    "cc0-1.0": "CC0-1.0",
    "cc0": "CC0-1.0",
    "cc-by-4.0": "CC-BY-4.0",
    "cc-by-3.0": "CC-BY-3.0",
    "cc-by-2.0": "CC-BY-2.0",
    "cc-by-sa-4.0": "CC-BY-SA-4.0",
    "cc-by-sa-3.0": "CC-BY-SA-3.0",
    "odbl": "ODbL-1.0",
    "odc-by": "ODC-By-1.0",
    "pddl": "PDDL-1.0",
    "mit": "MIT",
    "apache-2.0": "Apache-2.0",
    "public domain": "Public-Domain",
    "cdla-permissive-2.0": "CDLA-Permissive-2.0",
}
NUMERIC = {"numeric", "integer", "float"}
_BAND = re.compile(r"^\s*(\d+)\s*[-–]\s*(\d+)\s*$")
_POSITIVE = {"good", "yes", "1", "true", "repaid", "approved", "approve", "hired", "eligible"}
_NEGATIVE = {"bad", "no", "0", "false", "default", "rejected", "reject"}


def norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(text).lower()).strip()


def tokens(text: str) -> list[str]:
    return norm(text).split()


# -- licence -----------------------------------------------------------------------


def licence_status(raw: str) -> tuple[str, str, float]:
    """``(normalised, status, score)``; status = allowed | non_commercial | check."""
    text = (raw or "").strip().lower().replace("_", "-")
    if not text or text in {"other", "unknown", "none", "public"}:
        label = "Public (unspecified)" if text == "public" else (raw or "unknown")
        return label, "check", 0.3
    parts = re.split(r"[-\s]+", text)
    if "nc" in parts or "noncommercial" in text.replace(" ", "") or "non-commercial" in text:
        return raw, "non_commercial", 0.0
    if "nd" in parts:
        return raw, "check", 0.2
    for key, label in ALLOWED_LICENCES.items():
        if text == key or text.startswith(key) or key in text:
            return label, "allowed", 1.0
    return raw, "check", 0.3


# -- column <-> field ------------------------------------------------------------------


def is_band_field(field: Field) -> bool:
    return bool(field.values) and all(_BAND.match(v) for v in field.values)


def _type_fit(field: Field, column: Column) -> tuple[float, str | None]:
    """How well the column's type serves the field, and the transform it needs."""
    ctype = column.type
    if ctype == "unknown":
        return 0.8, None
    if field.type in ("integer", "float"):
        return (1.0, None) if ctype in NUMERIC else (0.4, None)
    if field.type == "category":
        if ctype in NUMERIC and is_band_field(field):
            return 0.95, "bin"
        if ctype in ("category", "string", "boolean"):
            return 1.0, "value_map"
        return 0.5, None
    if field.type == "boolean":
        return (1.0, "value_map") if ctype in ("boolean", "category", "integer") else (0.5, None)
    return 0.8, None


def _name_score(field: Field, column: Column) -> float:
    col = norm(column.name)
    col_desc = norm(column.description)
    demo = norm(column.demographic)
    names = [norm(field.name)] + [norm(s) for s in field.synonyms + SYNONYMS.get(field.name, [])]
    best = 0.0
    for syn in names:
        if not syn:
            continue
        if col == syn:
            return 1.0
        syn_toks = syn.split()
        col_toks = col.split()
        if syn_toks and all(t in col_toks for t in syn_toks):
            best = max(best, 0.85)
        if col_desc and (col_desc == syn or f" {syn} " in f" {col_desc} "):
            best = max(best, 0.8)
        if demo and demo == syn:
            best = max(best, 0.8)
        best = max(best, difflib.SequenceMatcher(None, col, syn).ratio() * 0.8)
    return best


def value_map(field: Field, ref_values: list[str]) -> dict[str, str]:
    """Reference value -> dictionary value, by whole-token match (``female div`` -> female)."""
    out: dict[str, str] = {}
    targets = [(v, set(tokens(v))) for v in field.values]
    for raw in ref_values:
        toks = set(tokens(raw))
        hits = [v for v, vt in targets if vt and vt <= toks]
        if len(hits) == 1:
            out[str(raw)] = hits[0]
        elif field.type == "boolean":
            low = norm(raw)
            if low in _POSITIVE or low in {"y", "t"}:
                out[str(raw)] = "true"
            elif low in _NEGATIVE or low in {"n", "f", "none"}:
                out[str(raw)] = "false"
    return out


def match_columns(ctx: SystemContext, columns: list[Column]) -> dict[str, dict[str, Any]]:
    """Greedy best assignment field -> column (each column used once)."""
    pairs: list[tuple[float, str, int, str | None]] = []
    for fname in ctx.model_fields:
        field = ctx.fields[fname]
        for i, col in enumerate(columns):
            if col.is_target:
                continue
            fit, transform = _type_fit(field, col)
            score = _name_score(field, col) * fit
            if score >= MATCH_THRESHOLD:
                pairs.append((score, fname, i, transform))
    pairs.sort(key=lambda p: (-p[0], p[1], p[2]))
    used_f: set[str] = set()
    used_c: set[int] = set()
    out: dict[str, dict[str, Any]] = {}
    for score, fname, i, transform in pairs:
        if fname in used_f or i in used_c:
            continue
        used_f.add(fname)
        used_c.add(i)
        col = columns[i]
        entry: dict[str, Any] = {"column": col.name, "score": round(score, 3)}
        if col.description:
            entry["column_description"] = col.description[:120]
        if transform:
            entry["transform"] = transform
        if transform == "value_map":
            entry["values"] = value_map(ctx.fields[fname], col.values) if col.values else {}
            if not entry["values"]:
                entry["needs_value_map"] = True  # coded or unknown values: a human maps them
        out[fname] = entry
    return out


def label_match(ctx: SystemContext, cand: Candidate) -> tuple[float, dict[str, Any] | None]:
    target = next((c for c in cand.columns if c.is_target), None)
    if target is None and cand.target:
        target = next((c for c in cand.columns if c.name == cand.target), Column(cand.target))
    if target is None or not ctx.label_names:
        return 0.0, None
    tnorm = norm(target.name)
    best = 0.4  # a declared target exists; we can at least check against it
    for label in ctx.label_names:
        syns = [norm(label)] + [norm(s) for s in LABEL_SYNONYMS.get(label, [])]
        if tnorm in syns:
            best = max(best, 1.0 if tnorm == norm(label) else 0.8)
    entry: dict[str, Any] = {"column": target.name, "name": ctx.label_names[0]}
    mapping = {}
    for v in target.values:
        low = norm(v)
        if low in _POSITIVE:
            mapping[str(v)] = 1
        elif low in _NEGATIVE:
            mapping[str(v)] = 0
    if mapping:
        entry["values"] = mapping
    return best, entry


def _task_score(ctx: SystemContext, cand: Candidate) -> float:
    ours = ctx.task.lower()
    theirs = cand.task.lower()
    if not theirs or theirs == "unknown":
        return 0.5
    if "class" in ours and "class" in theirs:
        return 1.0
    if "regress" in ours and "regress" in theirs:
        return 1.0
    return 0.3


def _relevance(ctx: SystemContext, cand: Candidate) -> float:
    """Domain words (Annex III point / card keywords) in the dataset's name and description."""
    words: set[str] = set()
    for d in domains_for(ctx):
        for phrase in DOMAINS[d]["queries"] + DOMAINS[d]["keywords"]:
            words |= {w for w in tokens(phrase) if len(w) > 3}
    if not words:
        return 0.5
    name = set(tokens(cand.name))
    text = set(tokens(cand.description[:1500]))
    hits = 2 * len(words & name) + len(words & text)
    return round(min(1.0, hits / 3.0), 3)


def _coverage(fields: list[str], mapping: dict[str, dict[str, Any]]) -> float:
    """Share of fields mapped; a mapping that still needs a value map counts half."""
    if not fields:
        return 0.0
    got = sum(0.5 if mapping[f].get("needs_value_map") else 1.0 for f in fields if f in mapping)
    return got / len(fields)


def _size_score(n: int | None) -> float:
    if not n:
        return 0.3
    return round(min(1.0, math.log10(max(n, 1)) / 3.0), 3)  # 1000+ rows = 1


def _recency_score(updated: str) -> float:
    m = re.search(r"(19|20)\d{2}", updated or "")
    if not m:
        return 0.5
    age = datetime.now(UTC).year - int(m.group(0))
    return round(max(0.2, 1.0 - age / 30.0), 3)


def score_candidate(ctx: SystemContext, cand: Candidate) -> dict[str, Any]:
    mapping = match_columns(ctx, cand.columns)
    model_fields = ctx.model_fields
    sensitive = ctx.protected + ctx.proxies
    schema = _coverage(model_fields, mapping)
    protected = _coverage(sensitive, mapping) if sensitive else 0.5
    label, label_entry = label_match(ctx, cand)
    licence, lic_status, lic_score = licence_status(cand.licence)
    breakdown = {
        "schema": round(schema, 3),
        "protected": round(protected, 3),
        "label": round(label, 3),
        "relevance": _relevance(ctx, cand),
        "task": _task_score(ctx, cand),
        "size": _size_score(cand.n_rows),
        "licence": lic_score,
        "recency": _recency_score(cand.updated),
    }
    if not cand.columns:  # web hit with no schema: cannot be matched, listed for a human
        breakdown["schema"] = breakdown["protected"] = 0.0
    score = sum(WEIGHTS[k] * v for k, v in breakdown.items())
    flags: list[str] = []
    if lic_status == "non_commercial":
        flags.append("licence_non_commercial")
        score *= 0.5
    elif lic_status == "check":
        flags.append("licence_unclear")
    if not cand.columns:
        flags.append("schema_unknown")
    if cand.n_rows is not None and cand.n_rows < 300:
        flags.append("small")
    return {
        "id": cand.id,
        "slug": cand.slug,
        "plugin": ctx.plugin,
        "source": cand.source,
        "name": cand.name,
        "url": cand.url,
        "score": round(score, 4),
        "breakdown": breakdown,
        "licence": {"raw": cand.licence, "normalised": licence, "status": lic_status},
        "n_rows": cand.n_rows,
        "n_columns": len(cand.columns),
        "task": cand.task,
        "updated": cand.updated,
        "mapping": mapping,
        "label": label_entry,
        "gaps": [f for f in model_fields if f not in mapping],
        "protected_missing": [f for f in sensitive if f not in mapping],
        "flags": flags,
        "fetchable": bool(cand.download),
        "query": cand.query,
        "description": cand.description[:400],
        "citation": cand.citation,
    }


def rank(ctx: SystemContext, candidates: list[Candidate], top: int = 10) -> list[dict[str, Any]]:
    seen: set[str] = set()
    scored = []
    for cand in candidates:
        if cand.id in seen:
            continue
        seen.add(cand.id)
        scored.append(score_candidate(ctx, cand))
    scored.sort(key=lambda s: (-s["score"], s["id"]))
    return scored[:top]
