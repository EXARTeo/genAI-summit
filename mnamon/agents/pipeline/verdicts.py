"""Per-obligation verdicts and sealing (plan 01 §5.1, §5.3, §7): code, no model.

* :func:`fallback_obligation_map`: the requirement list of ``load_context`` in the
  obligation-map shape, for when ``pipeline.obligations`` (reg-memory's catalogue)
  is unavailable.
* :func:`rows_for` + :func:`rule_verdict`: the test-result rows of one obligation
  and the verdict the organisation's thresholds give (``pass | partial | gap |
  inconclusive``; a CI that crosses the threshold is ``partial``).
* :func:`dossier_evidence`: for documentary obligations, which evidence types the
  system folder holds (present / missing), by file name.
* :func:`combine`: rule + Gemini assessor + Iris; a judge disagreement is
  ``inconclusive`` with ``needs_human``.
* :func:`severity`, :func:`seal`: gap ids ``G-<SYS>-<nn>``, severity by the
  in-force date (§7.3), the sha256 hash chain (the backend's ``finding_hash``),
  and the coverage invariant (exactly one verdict per obligation in scope).
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import date as Date
from datetime import timedelta
from typing import Any

#: Verdicts that open a gap (plan 01 §7.1).
GAP_VERDICTS = ("gap", "partial", "inconclusive")
#: Obligations whose breach directly affects people (bias in hiring, credit, oversight).
DIRECT_EFFECT = ("AIA.5", "AIA.9.9", "AIA.10", "AIA.14", "AIA.15")
#: Words of an evidence type that say nothing about which file it is.
_GENERIC = {"record", "records", "policy", "summary", "plan", "and", "the", "for"}
_OPS = {
    ">=": lambda v, t: v >= t,
    ">": lambda v, t: v > t,
    "<=": lambda v, t: v <= t,
    "<": lambda v, t: v < t,
    "==": lambda v, t: abs(v - t) < 1e-12,
}
TESTED_MODES = ("model_test", "system_test", "hybrid")


# ---------------------------------------------------------------- obligation map
def fallback_obligation_map(
    requirements: list[dict[str, Any]], today: str | None = None
) -> list[dict[str, Any]]:
    """``load_context``'s requirement list as obligation-map entries (reg-memory fallback)."""
    out = []
    for r in requirements:
        rid = str(r.get("id") or "")
        if not rid:
            continue
        testable = r.get("testability") == "model_and_data_test"
        source = r.get("source")
        article = source if isinstance(source, str) else (r.get("related") or [None])[0]
        starts = str(r.get("effective_valid_from") or "") or None
        out.append(
            {
                "obligation_id": rid.replace("REQ.", "OBL.", 1),
                "article": article,
                "related": [x for x in r.get("related") or [] if isinstance(x, str)],
                "applicable": True,
                "reason": "from the applicable requirements (obligation catalogue unavailable)",
                "in_force_date": starts,
                "in_force_now": bool(r.get("in_force"))
                if r.get("in_force") is not None
                else bool(starts and today and starts <= today),
                "verification_mode": "model_test" if testable else "documentary",
                "checks": [{"templates": list(r.get("test_templates") or [])}] if testable else [],
                "decided_by": "rule",
                "borderline": False,
                "summary": r.get("obligation"),
                "requirements": [rid],
                "evidence_types": [],
            }
        )
    return out


def in_scope(entries: list[dict[str, Any]], focus: list[str] | None) -> list[dict[str, Any]]:
    """Applicable entries, limited to ``focus`` (``audit.data.obligations``) when given."""
    wanted = {str(f) for f in focus or [] if f}
    return [
        e for e in entries if e.get("applicable") and (not wanted or e["obligation_id"] in wanted)
    ]


def is_tested(entry: dict[str, Any]) -> bool:
    return entry.get("verification_mode") in TESTED_MODES


def templates_of(entry: dict[str, Any]) -> set[str]:
    return {t for c in entry.get("checks") or [] for t in (c.get("templates") or [])}


def obligation_for_requirement(
    entries: list[dict[str, Any]], requirement: str | None
) -> str | None:
    for e in entries:
        if requirement and requirement in (e.get("requirements") or []):
            return e["obligation_id"]
    return None


# ------------------------------------------------------------------- rule verdict
def rows_for(entry: dict[str, Any], tests: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Result rows that bear on ``entry``: named for it, or of one of its check templates."""
    oid, templates = entry["obligation_id"], templates_of(entry)
    reqs = set(entry.get("requirements") or [])
    return [
        t
        for t in tests
        if t.get("obligation_id") == oid
        or (t.get("template") in templates)
        or (reqs & set(t.get("requirements") or []))
    ]


def _fails_whole_ci(row: dict[str, Any]) -> bool:
    thr, ci = row.get("threshold") or {}, row.get("ci95")
    check = _OPS.get(str(thr.get("op")))
    if check is None or thr.get("value") is None:
        return False
    if not ci:
        return True
    return not any(check(float(b), float(thr["value"])) for b in ci)


def rule_verdict(rows: list[dict[str, Any]]) -> tuple[str, str]:
    """``(verdict, why)`` from the org thresholds the test rows were judged against."""
    if not rows:
        return "inconclusive", "no test of this obligation ran in this audit"
    usable = [r for r in rows if r.get("status") != "error"]
    if not usable:
        return "inconclusive", "every test of this obligation errored"
    judged = [r for r in usable if (r.get("threshold") or {}).get("op") is not None]
    if not judged:
        names = ", ".join(sorted({str(r.get("metric")) for r in usable}))[:200]
        return "inconclusive", f"no organisational threshold for {names}"
    fails = [r for r in judged if r.get("status") == "fail"]
    hard = [r for r in fails if _fails_whole_ci(r)]
    soft = [r for r in judged if r.get("status") == "inconclusive"] + [
        r for r in fails if r not in hard
    ]

    def show(rs: list[dict[str, Any]]) -> str:
        return "; ".join(
            f"{r.get('metric')}={r.get('value')} (CI {r.get('ci95')}, "
            f"threshold {(r.get('threshold') or {}).get('op')} "
            f"{(r.get('threshold') or {}).get('value')})"
            for r in rs[:4]
        )

    if hard:
        return "gap", f"fails the organisation's threshold: {show(hard)}"
    if soft:
        return "partial", f"the CI crosses the threshold or a subgroup fails: {show(soft)}"
    return "pass", f"every judged metric meets its threshold with its CI ({len(judged)} metrics)"


# ------------------------------------------------------------- documentary check
def dossier_evidence(entry: dict[str, Any], paths: list[str]) -> dict[str, list[str]]:
    """Evidence types of ``entry`` the system folder holds (by file name) and those it lacks."""
    present, missing = [], []
    lowered = [p.lower() for p in paths]
    for kind in entry.get("evidence_types") or []:
        words = [w for w in re.split(r"[_\-\s]+", str(kind).lower()) if len(w) > 2]
        words = [w for w in words if w not in _GENERIC] or words
        hit = next(
            (p for p, low in zip(paths, lowered, strict=True) if all(w in low for w in words)), None
        )
        (present if hit else missing).append(f"{kind}: {hit}" if hit else str(kind))
    return {"present": present, "missing": missing}


# ---------------------------------------------------------------------- combine
def combine(rule: str, gemini: str | None, iris: str | None) -> tuple[str, bool]:
    """``(verdict, needs_human)``: Gemini proposes, Iris decides independently, code compares."""
    proposed = gemini or rule
    if iris is None:
        return proposed, gemini is not None and gemini != rule
    if iris == proposed:
        return proposed, False
    return "inconclusive", True


def citation_problems(
    citations: list[dict[str, Any]], entry: dict[str, Any], known: dict[str, bool]
) -> list[str]:
    """A citation must exist at the pinned kb and belong to the article or its ``related``."""
    roots = [str(x) for x in [entry.get("article"), *(entry.get("related") or [])] if x]
    out = []
    for c in citations:
        pid = str(c.get("provision_id") or "")
        if not known.get(pid, False):
            out.append(f"{pid}: not found at the pinned kb_version")
        elif roots and not any(
            pid == r or pid.startswith(r + ".") or r.startswith(pid + ".") for r in roots
        ):
            out.append(f"{pid}: not part of {', '.join(roots)}")
    return out


# --------------------------------------------------------------------- severity
def severity(
    verdict: str, entry: dict[str, Any], today: Date, *, doc_gap: bool = False
) -> str | None:
    """Plan 01 §7.3: by verdict and the obligation's in-force date."""
    if doc_gap:
        return "low"
    if verdict not in GAP_VERDICTS:
        return None
    starts = entry.get("in_force_date")
    try:
        start = Date.fromisoformat(str(starts)[:10]) if starts else None
    except ValueError:
        start = None
    in_force = bool(entry.get("in_force_now")) or (start is not None and start <= today)
    soon = start is not None and start <= today + timedelta(days=183)
    article = str(entry.get("article") or "")
    if verdict == "gap":
        if in_force and any(article == p or article.startswith(p + ".") for p in DIRECT_EFFECT):
            return "critical"
        if in_force or soon:
            return "high"
        return "medium"
    return "medium" if (in_force or soon) else "low"


# ------------------------------------------------------------------------ seal
SEALED_FIELDS = (
    "obligation_id",
    "verdict",
    "severity",
    "gap_id",
    "metrics_ref",
    "evidence_refs",
    "citations",
    "kb_version",
    "reasoning",
    "counter_arguments",
    "would_change_if",
    "judges",
    "critic",
)


def finding_hash(finding: dict[str, Any], prev_hash: str | None) -> str:
    """The backend's hash (``utils/findings.finding_hash``): sha256(prev + canonical JSON)."""
    sealed = {k: finding.get(k) for k in SEALED_FIELDS}
    canonical = json.dumps(sealed, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(f"{prev_hash or ''}{canonical}".encode()).hexdigest()


def seal(
    proposed: list[dict[str, Any]], system_id: str, *, prev_hash: str | None = None
) -> list[dict[str, Any]]:
    """Gap ids in order, then the hash chain. ``proposed`` already carries severity."""
    out, n, prev = [], 0, prev_hash
    for item in proposed:
        finding = dict(item)
        is_gap = finding["verdict"] in GAP_VERDICTS or finding.get("documentation_gap")
        if is_gap:
            n += 1
            finding["gap_id"] = f"G-{system_id}-{n:02d}"
        else:
            finding["gap_id"] = None
        finding["prev_hash"] = prev
        finding["hash"] = finding_hash(finding, prev)
        prev = finding["hash"]
        out.append(finding)
    return out


def coverage_problems(scope: list[dict[str, Any]], findings: list[dict[str, Any]]) -> list[str]:
    """Exactly one verdict per obligation in scope, and nothing outside it."""
    wanted = [e["obligation_id"] for e in scope]
    counts: dict[str, int] = {}
    for f in findings:
        counts[f["obligation_id"]] = counts.get(f["obligation_id"], 0) + 1
    out = [f"{oid}: no verdict" for oid in wanted if oid not in counts]
    out += [f"{oid}: {c} verdicts" for oid, c in counts.items() if c > 1]
    out += [f"{oid}: not in scope" for oid in counts if oid not in set(wanted)]
    return out


#: Sealed verdict -> the finding artifact's older vocabulary (the UI reads it).
LEGACY_VERDICT = {
    "pass": "supports_compliance",
    "partial": "indicates_gap",
    "gap": "indicates_gap",
    "inconclusive": "inconclusive",
    "not_applicable": "not_assessable_by_testing",
    "not_assessable_by_testing": "not_assessable_by_testing",
}


__all__ = [
    "GAP_VERDICTS",
    "LEGACY_VERDICT",
    "citation_problems",
    "combine",
    "coverage_problems",
    "dossier_evidence",
    "fallback_obligation_map",
    "finding_hash",
    "in_scope",
    "is_tested",
    "obligation_for_requirement",
    "rows_for",
    "rule_verdict",
    "seal",
    "severity",
    "templates_of",
]
