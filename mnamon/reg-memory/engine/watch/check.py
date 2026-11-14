"""One watch check: re-fetch -> extract -> diff -> (changed?) candidate release + RegChange
-> notify, plus Firecrawl change tracking and discovery.

    <data>/watch/checks/<check_id>.json    one check record (status, per-step results)

Works without any key: change detection is our own sha256 diff of the fetched
bytes; Firecrawl change tracking (git-diff, per-source tag) is an extra signal
when ``FIRECRAWL_API_KEY`` is set.
"""

from __future__ import annotations

import asyncio
import json
import re
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from core.logging import get_logger
from core.settings import NotifySettings, WatchSettings
from engine.catalog.loader import Catalog
from engine.firecrawl import client as firecrawl
from engine.firecrawl.client import FirecrawlConfig
from engine.ingest import IngestConfig, run_ingest
from engine.kb.changes import build_change
from engine.kb.releases import KnowledgeBase
from engine.llm.gemini import Gemini
from engine.notify import notify_change
from engine.store import Store, _atomic_write, now_iso
from engine.watch import proposals
from engine.watch.discovery import discover

logger = get_logger(__name__)

CHECK_ID_RE = re.compile(r"^chk-[0-9TZ]+-[0-9a-f]{8}$")


@dataclass
class CheckDeps:
    store: Store
    catalog: Catalog
    client: httpx.AsyncClient
    ingest: IngestConfig
    firecrawl: FirecrawlConfig
    gemini: Gemini
    watch: WatchSettings
    notify: NotifySettings
    catalog_path: Path | None = None
    kb: KnowledgeBase = field(init=False)

    def __post_init__(self) -> None:
        self.kb = KnowledgeBase(self.store)


def new_check_id() -> str:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%f")  # sortable, sub-second
    return f"chk-{stamp}Z-{uuid.uuid4().hex[:8]}"


def check_path(store: Store, check_id: str) -> Path:
    if not CHECK_ID_RE.match(check_id):
        raise ValueError(f"invalid check id: {check_id!r}")
    return store.root / "watch" / "checks" / f"{check_id}.json"


def save_check(store: Store, record: dict[str, Any]) -> None:
    data = json.dumps(record, indent=2, ensure_ascii=False).encode("utf-8")
    _atomic_write(check_path(store, record["check_id"]), data)


def load_check(store: Store, check_id: str) -> dict[str, Any] | None:
    try:
        path = check_path(store, check_id)
    except ValueError:
        return None
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def list_checks(store: Store, limit: int = 20) -> list[dict[str, Any]]:
    folder = store.root / "watch" / "checks"
    if not folder.exists():
        return []
    paths = sorted(folder.glob("chk-*.json"), reverse=True)[:limit]
    return [json.loads(p.read_text(encoding="utf-8")) for p in paths]


async def _track(deps: CheckDeps, source_ids: list[str] | None) -> dict[str, Any]:
    """Firecrawl change tracking for the selected (or ``monitor: true``) sources."""
    if not deps.firecrawl.active:
        return {"status": "disabled: FIRECRAWL_API_KEY not set (own hash diff is used)"}
    if source_ids:
        targets = [deps.catalog.get(i) for i in source_ids]
    else:
        targets = [s for s in deps.catalog.sources if s.monitor and s.enabled]
    out: dict[str, Any] = {}
    for src in targets:
        if src is None or not src.url or src.fetcher == "cellar":
            continue
        try:
            out[src.id] = await firecrawl.track_change(
                deps.client, deps.firecrawl, src.url, tag=src.id
            )
        except firecrawl.FirecrawlError as exc:
            out[src.id] = {"status": "error", "error": str(exc)}
    return {"status": "active", "sources": out}


def _changed_docs(run: dict[str, Any]) -> list[str]:
    return [
        d["doc_id"]
        for r in run.get("results", [])
        for d in r.get("documents", [])
        if d.get("status") in {"new", "changed"}
    ]


async def release_and_change(
    deps: CheckDeps, *, trigger: str, force: bool = False
) -> dict[str, Any]:
    """Build a candidate release; if it differs, diff it against the active one,
    store the RegChange and notify. The first release ever is the active baseline."""
    manifest, created = await asyncio.to_thread(
        deps.kb.build_release, deps.catalog, trigger=trigger
    )
    out: dict[str, Any] = {"kb_version": manifest["kb_version"], "created": created}
    if not created and not force:
        return out
    if manifest.get("parent") is None and deps.kb.active_version() is None:
        if deps.watch.auto_activate_first:
            deps.kb.activate(manifest["kb_version"], by="bootstrap")
            out["activated"] = True
        return out
    base = deps.kb.active_version() or manifest.get("parent")
    if base == manifest["kb_version"]:
        return out
    change = await build_change(deps.kb, base, manifest["kb_version"], deps.gemini, trigger=trigger)
    if change is None:
        return out
    out["change_id"] = change["id"]
    out["change_summary"] = change["summary"]
    notified = await notify_change(deps.client, change, deps.notify)
    out["notified"] = notified
    change["notified"] = notified
    _atomic_write(
        deps.kb.root / "changes" / f"{change['id']}.json",
        json.dumps(change, indent=2, ensure_ascii=False).encode("utf-8"),
    )
    return out


async def run_check(
    deps: CheckDeps,
    *,
    check_id: str,
    source_ids: list[str] | None = None,
    trigger: str = "manual",
    run_discovery: bool | None = None,
) -> dict[str, Any]:
    """The whole check; the record is saved after every step (pollable)."""
    full = not source_ids
    if run_discovery is None:
        run_discovery = full and deps.watch.discovery_enabled
    record: dict[str, Any] = {
        "check_id": check_id,
        "status": "running",
        "trigger": trigger,
        "started_at": now_iso(),
        "finished_at": None,
        "source_ids": source_ids or [],
        "changed_documents": [],
    }
    save_check(deps.store, record)
    try:
        run = await run_ingest(
            deps.catalog,
            deps.store,
            deps.client,
            deps.ingest,
            source_ids=source_ids,
            run_id=f"{check_id}-ingest",
            catalog_path=deps.catalog_path,
        )
        record["ingest_run_id"] = run["run_id"]
        record["changed_documents"] = _changed_docs(run)
        record["failed_sources"] = [
            r["source_id"] for r in run["results"] if r.get("status") == "failed"
        ]
        save_check(deps.store, record)

        record["firecrawl"] = await _track(deps, source_ids)
        save_check(deps.store, record)

        if run_discovery:
            sources = [s for s in deps.catalog.sources if s.discover]
            candidates, report = await discover(
                deps.store, sources, deps.client, deps.firecrawl, deps.watch.sparql_url
            )
            fresh = await proposals.add_candidates(
                deps.store.root, deps.catalog, candidates, deps.gemini
            )
            report["proposed"] = sum(1 for p in fresh if p["status"] == "proposed")
            report["ignored"] = sum(1 for p in fresh if p["status"] == "ignored")
            record["discovery"] = report
            save_check(deps.store, record)

        no_release = not deps.kb.versions()
        if record["changed_documents"] or no_release:
            try:
                record["release"] = await release_and_change(deps, trigger=check_id)
            except RuntimeError as exc:  # e.g. the AI Act text is not downloaded yet
                record["release"] = {"skipped": str(exc)}
        record["status"] = "done"
    except Exception as exc:
        logger.exception("watch_check_failed", "Watch check failed", check_id=check_id)
        record.update(status="failed", error=repr(exc))
    finally:
        record["finished_at"] = now_iso()
        save_check(deps.store, record)
        logger.info(
            "watch_check_finished",
            "Watch check finished",
            check_id=check_id,
            check_status=record["status"],
            changed=len(record["changed_documents"]),
        )
    return record
