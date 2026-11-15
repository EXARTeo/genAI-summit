"""Reads of the knowledge base for the routers (provisions, releases, changes, requirements)."""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

from fastapi import HTTPException, status

from engine.kb.applicability import applicable
from engine.kb.changes import list_changes, load_change
from engine.kb.search import heading, label, search
from schema.kb import (
    ChangeList,
    ChangeSummary,
    InterpretationList,
    ProvisionList,
    Release,
    ReleaseList,
    RequirementList,
    SearchResult,
    TestTemplateList,
)
from utils.state import get_catalog, get_kb


def _version(kb_version: str | None) -> str:
    resolved = get_kb().resolve(kb_version)
    if resolved is None:
        detail = f"unknown kb_version {kb_version}" if kb_version else "no kb release yet"
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail)
    return resolved


# ---- provisions / interpretations ------------------------------------------------------------


def get_provision(provision_id: str, kb_version: str | None) -> dict[str, Any]:
    version = _version(kb_version)
    found = get_kb().provision_map(version).get(provision_id)
    if not found:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "provision not found")
    children = [p["id"] for p in get_kb().provisions(version) if p.get("parent") == provision_id]
    interps = [
        i["id"]
        for i in get_kb().interpretations(version)
        if any(r == provision_id or r.startswith(provision_id + ".") for r in i["relates_to"])
    ]
    title, inherited, title_from = heading(found, get_kb().provision_map(version))
    derived = {"label": label(found), "title": title, "title_inherited": inherited}
    if inherited:
        derived["title_from"] = title_from
    return {**found, **derived, "children": children, "interpretations": interps}


def search_regulation(
    kb_version: str | None, q: str, limit: int, instrument: str | None
) -> SearchResult:
    """Ranked provision hits (``engine.kb.search``), derived at read time from the release."""
    version = _version(kb_version)
    binding = {s.id: s.binding for s in get_catalog().sources}
    total, hits = search(
        get_kb().provisions(version), q, limit=limit, instrument=instrument, binding=binding
    )
    return SearchResult(kb_version=version, query=q, total=total, items=hits)


def search_provisions(
    kb_version: str | None,
    prefix: str | None,
    q: str | None,
    instrument: str | None,
    limit: int,
    offset: int,
    with_text: bool,
) -> ProvisionList:
    version = _version(kb_version)
    items = get_kb().provisions(version)
    if instrument:
        items = [p for p in items if p["instrument"] == instrument]
    if prefix:
        items = [p for p in items if p["id"] == prefix or p["id"].startswith(prefix + ".")]
    if q:
        needle = q.lower()
        items = [p for p in items if needle in p["text"].lower()]
    page = items[offset : offset + limit]
    if not with_text:
        page = [{k: v for k, v in p.items() if k != "text"} for p in page]
    return ProvisionList(kb_version=version, total=len(items), items=page)


def search_interpretations(
    kb_version: str | None, relates_to: str | None, source_id: str | None, limit: int
) -> InterpretationList:
    version = _version(kb_version)
    items = get_kb().interpretations(version)
    if relates_to:
        items = [
            i
            for i in items
            if any(r == relates_to or r.startswith(relates_to + ".") for r in i["relates_to"])
        ]
    if source_id:
        items = [i for i in items if i["source_id"] == source_id]
    page = [{k: v for k, v in i.items() if k != "text"} for i in items[:limit]]
    return InterpretationList(kb_version=version, total=len(items), items=page)


def get_interpretation(interp_id: str, kb_version: str | None) -> dict[str, Any]:
    found = get_kb().interpretation_map(_version(kb_version)).get(interp_id)
    if not found:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "interpretation not found")
    return found


# ---- releases --------------------------------------------------------------------------------


def list_releases() -> ReleaseList:
    kb = get_kb()
    return ReleaseList(active=kb.active_version(), items=[Release(**m) for m in kb.list_releases()])


def get_release(kb_version: str) -> Release:
    manifest = get_kb().load_manifest(kb_version)
    if not manifest:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "release not found")
    return Release(**manifest)


def activate_release(kb_version: str, by: str) -> Release:
    try:
        return Release(**get_kb().activate(kb_version, by=by))
    except KeyError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "release not found") from exc


# ---- changes ---------------------------------------------------------------------------------

_SUMMARY_KEYS = (
    "id",
    "from_kb_version",
    "to_kb_version",
    "created_at",
    "trigger",
    "status",
    "summary",
    "counts",
    "change_types",
    "notified",
)


def changes() -> ChangeList:
    items = []
    for c in list_changes(get_kb()):
        summary = {k: c.get(k) for k in _SUMMARY_KEYS}
        summary["impacted_requirements"] = len(c.get("impacted_requirements") or [])
        items.append(ChangeSummary(**summary))
    return ChangeList(items=items)


def get_change(change_id: str) -> dict[str, Any]:
    change = load_change(get_kb(), change_id)
    if not change:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "change not found")
    return change


# ---- requirements ----------------------------------------------------------------------------


def requirements(
    kb_version: str | None,
    role: str | None,
    risk_class: str | None,
    basis: str | None,
    on: date | None,
    features: list[str] | None,
    testability: str | None,
) -> RequirementList:
    version = _version(kb_version)
    on = on or datetime.now(UTC).date()
    items = applicable(
        get_kb().requirements(version),
        role=role,
        risk_class=risk_class,
        basis=basis,
        on=on,
        features=features,
    )
    if testability:
        items = [r for r in items if r["testability"] == testability]
    query = {
        "role": role,
        "risk_class": risk_class,
        "basis": basis,
        "date": on.isoformat(),
        "feature": features or [],
        "testability": testability,
    }
    return RequirementList(kb_version=version, query=query, total=len(items), items=items)


def test_templates(kb_version: str | None) -> TestTemplateList:
    version = _version(kb_version)
    return TestTemplateList(kb_version=version, items=get_kb().test_templates(version))
