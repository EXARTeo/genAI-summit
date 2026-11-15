"""Deterministic history logic for the chat copilot: pins, diffs and "does audit X need a re-run?".

No model and no I/O: every function takes the bodies the backend and reg-memory
answered and returns plain dicts, so the tests drive them with recorded shapes.

* :func:`audit_pins` reads what an audit pinned (``data.pins`` first, then the
  older ``data.kb_version`` / the artifacts' stamped ``kb_version``).
* :func:`audit_provisions` maps each obligation (or requirement / finding) of an
  audit to the provisions it rests on: the ``obligation_map`` artifact, the
  ``context`` artifact's requirements and the findings' citations.
* :func:`release_chain` walks the kb releases from the active one back to the
  pinned one (``parent`` links), and :func:`changes_between` keeps the
  regulation changes on that chain.
* :func:`needs_rerun` intersects the changed provisions with the audit's
  provisions (a parent or child provision counts) and decides: any
  non-editorial change on a provision the audit relies on means a re-run.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

#: Change types that never force a re-run on their own (wording, formatting).
EDITORIAL = frozenset({"editorial"})

#: The most changed provisions / related items a result lists.
MAX_LISTED = 40


def _s(value: Any) -> str | None:
    return value if isinstance(value, str) and value.strip() else None


def _artifacts(audit: dict[str, Any], kind: str) -> list[dict[str, Any]]:
    """The live (latest version per name) artifacts of one kind."""
    latest: dict[str, dict[str, Any]] = {}
    for art in audit.get("artifacts") or []:
        if not isinstance(art, dict) or art.get("kind") != kind:
            continue
        if art.get("status") == "superseded":
            continue
        name = str(art.get("name") or "main")
        if name not in latest or int(art.get("version") or 0) > int(
            latest[name].get("version") or 0
        ):
            latest[name] = art
    return list(latest.values())


def live_artifacts(audit: dict[str, Any], kind: str) -> list[dict[str, Any]]:
    """Public alias of the live-artifact filter (findings, critic, obligation map)."""
    return _artifacts(audit, kind)


def audit_pins(audit: dict[str, Any]) -> dict[str, Any]:
    """``{kb_version, dossier_version, config_version, model_version, seeds, source}``."""
    data = audit.get("data") if isinstance(audit.get("data"), dict) else {}
    pins = audit.get("pins") if isinstance(audit.get("pins"), dict) else None
    pins = pins or (data.get("pins") if isinstance(data.get("pins"), dict) else None)
    out: dict[str, Any] = {}
    source = "pins"
    if pins:
        out.update({k: v for k, v in pins.items() if v not in (None, "", [], {})})
    kb = _s(out.get("kb_version")) or _s(data.get("kb_version"))
    if not _s(out.get("kb_version")):
        source = "audit.data" if kb else source
    if not kb:
        for art in audit.get("artifacts") or []:
            stamped = _s(((art or {}).get("data") or {}).get("kb_version"))
            if stamped and stamped != "unknown":
                kb, source = stamped, f"artifact:{art.get('kind')}"
                break
    if kb:
        out["kb_version"] = kb
    for key in ("dossier_version", "dossierVersion"):
        if key in data and "dossier_version" not in out:
            out["dossier_version"] = data[key]
    out["source"] = source if kb else "none"
    return out


def _obligation_rows(body: Any) -> list[dict[str, Any]]:
    """The rows of an obligation map, whatever list key it uses."""
    if isinstance(body, list):
        return [r for r in body if isinstance(r, dict)]
    if not isinstance(body, dict):
        return []
    for key in ("obligations", "items", "rows", "map"):
        rows = body.get(key)
        if isinstance(rows, list):
            return [r for r in rows if isinstance(r, dict)]
    return []


def _provision_ids(row: dict[str, Any]) -> set[str]:
    ids: set[str] = set()
    for key in ("provisions", "provision_ids", "related", "cites", "citations", "via"):
        value = row.get(key)
        if isinstance(value, str):
            ids.add(value)
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, str):
                    ids.add(item)
                elif isinstance(item, dict):
                    pid = _s(item.get("provision_id")) or _s(item.get("id"))
                    if pid:
                        ids.add(pid)
    for key in ("source", "provision", "provision_id", "basis", "article"):
        pid = _s(row.get(key))
        if pid and pid.startswith(("AIA.", "OMNIBUS.", "INT.")):
            ids.add(pid)
    return ids


def obligation_map_rows(audit: dict[str, Any]) -> list[dict[str, Any]]:
    """The obligation map artifact's rows (empty when the audit has none)."""
    for art in _artifacts(audit, "obligation_map"):
        rows = _obligation_rows(art.get("data") or {})
        if rows:
            return rows
    return []


def audit_provisions(audit: dict[str, Any]) -> dict[str, set[str]]:
    """``{obligation / requirement / finding id: {provision ids}}`` for one audit."""
    out: dict[str, set[str]] = {}

    def add(key: str | None, ids: Iterable[str]) -> None:
        clean = {i for i in ids if i}
        if key and clean:
            out.setdefault(key, set()).update(clean)

    for row in obligation_map_rows(audit):
        if row.get("applies") is False:
            continue
        key = _s(row.get("id")) or _s(row.get("obligation_id")) or _s(row.get("obligation"))
        add(key, _provision_ids(row))
    for art in _artifacts(audit, "context"):
        for req in (art.get("data") or {}).get("requirements") or []:
            if isinstance(req, dict):
                add(_s(req.get("id")), _provision_ids(req))
    for art in _artifacts(audit, "finding"):
        data = art.get("data") or {}
        fid = _s(data.get("id")) or _s(art.get("name"))
        ids = _provision_ids(data)
        add(f"finding:{fid}" if fid else None, ids)
        req = _s(data.get("obligation_id")) or _s(data.get("requirement"))
        add(req, ids)
    return out


def release_chain(releases: Iterable[dict[str, Any]], newest: str, oldest: str) -> list[str] | None:
    """kb versions after ``oldest`` up to and including ``newest`` (by ``parent``), or None."""
    parent = {
        str(r.get("kb_version")): _s(r.get("parent"))
        for r in releases
        if isinstance(r, dict) and r.get("kb_version")
    }
    chain: list[str] = []
    cursor: str | None = newest
    seen: set[str] = set()
    while cursor and cursor != oldest:
        if cursor in seen or cursor not in parent:
            return None
        seen.add(cursor)
        chain.append(cursor)
        cursor = parent[cursor]
    return list(reversed(chain)) if cursor == oldest else None


def changes_between(changes: Iterable[dict[str, Any]], chain: list[str]) -> list[dict[str, Any]]:
    """The regulation changes whose target release is on the chain, oldest first."""
    order = {kb: i for i, kb in enumerate(chain)}
    keep = [
        c for c in changes if isinstance(c, dict) and str(c.get("to_kb_version") or "") in order
    ]
    return sorted(keep, key=lambda c: order[str(c.get("to_kb_version"))])


def provision_rows(change: dict[str, Any]) -> list[dict[str, Any]]:
    """A change's (or a diff's) provisions, without the texts."""
    rows = change.get("provisions") if isinstance(change, dict) else None
    if not isinstance(rows, list):
        rows = change.get("items") if isinstance(change, dict) else None
    out: list[dict[str, Any]] = []
    for row in rows or []:
        if isinstance(row, str):
            out.append({"id": row})
        elif isinstance(row, dict) and row.get("id"):
            keep = {
                k: row.get(k)
                for k in ("id", "change", "change_type", "title", "path", "binding")
                if row.get(k) not in (None, "", [])
            }
            if change.get("id"):
                keep["reg_change"] = change.get("id")
            out.append(keep)
    return out


def touches(changed: str, cited: str) -> bool:
    """A changed provision touches a cited one when equal or one contains the other."""
    return changed == cited or changed.startswith(cited + ".") or cited.startswith(changed + ".")


def needs_rerun(
    *,
    audit_id: str,
    system_id: str | None,
    pinned: str | None,
    active: str | None,
    changed: list[dict[str, Any]],
    relied: dict[str, set[str]],
    judged: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """The re-run verdict for one audit (see the module docstring for the rule)."""
    base: dict[str, Any] = {
        "audit_id": audit_id,
        "system_id": system_id,
        "pinned_kb_version": pinned,
        "active_kb_version": active,
        "needs_rerun": False,
        "changed_provisions": [],
        "affected_obligations": [],
        "affected_findings": [],
        "related_reg_changes": [],
    }
    if not pinned:
        return {**base, "reason": "The audit pinned no kb_version, so it cannot be compared."}
    if not active:
        return {**base, "reason": "reg-memory has no active kb release to compare with."}
    if pinned == active:
        return {**base, "reason": f"The audit ran on the active kb_version {active}."}
    all_cited = set().union(*relied.values()) if relied else set()
    hits: dict[str, dict[str, Any]] = {}
    obligations: dict[str, set[str]] = {}
    for row in changed:
        pid = str(row.get("id") or "")
        matched = {c for c in all_cited if touches(pid, c)}
        if not matched:
            continue
        hits[pid] = {**row, "relied_on_as": sorted(matched)[:5]}
        for key, ids in relied.items():
            if ids & matched:
                obligations.setdefault(key, set()).add(pid)
    substantive = [h for h in hits.values() if h.get("change_type") not in EDITORIAL]
    rc_ids = sorted({str(h["reg_change"]) for h in hits.values() if h.get("reg_change")})
    related = []
    for rc in rc_ids:
        item: dict[str, Any] = {"id": rc}
        info = (judged or {}).get(rc) or {}
        item.update({k: v for k, v in info.items() if v not in (None, "", [])})
        related.append(item)
    oblig = sorted(k for k in obligations if not k.startswith("finding:"))
    findings = sorted(k.removeprefix("finding:") for k in obligations if k.startswith("finding:"))
    out = {
        **base,
        "needs_rerun": bool(substantive),
        "changed_provisions": sorted(hits.values(), key=lambda h: h["id"])[:MAX_LISTED],
        "changed_provisions_total": len(changed),
        "affected_obligations": [{"id": k, "via": sorted(obligations[k])[:10]} for k in oblig][
            :MAX_LISTED
        ],
        "affected_findings": findings[:MAX_LISTED],
        "related_reg_changes": related,
    }
    if not relied:
        out["reason"] = (
            f"kb moved {pinned} -> {active} ({len(changed)} provisions changed), but the audit "
            "has no obligation map, requirements or cited provisions to intersect."
        )
    elif substantive:
        ids = ", ".join(sorted(h["id"] for h in substantive)[:6])
        out["reason"] = (
            f"kb moved {pinned} -> {active}; {len(substantive)} non-editorial change(s) touch "
            f"provisions the audit relies on ({ids})."
        )
    elif hits:
        out["reason"] = (
            f"kb moved {pinned} -> {active}; only editorial changes touch the audit's provisions."
        )
    else:
        out["reason"] = (
            f"kb moved {pinned} -> {active} ({len(changed)} provisions changed); none touches "
            "the audit's obligations or cited provisions."
        )
    return out


__all__ = [
    "EDITORIAL",
    "audit_pins",
    "audit_provisions",
    "changes_between",
    "live_artifacts",
    "needs_rerun",
    "obligation_map_rows",
    "provision_rows",
    "release_chain",
    "touches",
]
