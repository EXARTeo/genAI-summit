"""Watch glue: background checks (one at a time, with ingests), the scheduler and the
startup bootstrap (first download + the baseline release)."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import HTTPException, status

from core.logging import get_logger
from core.settings import settings
from engine.firecrawl.client import FirecrawlConfig
from engine.ingest import IngestConfig
from engine.llm.gemini import Gemini
from engine.notify import backend_active, telegram_active
from engine.store import now_iso
from engine.watch.check import (
    CheckDeps,
    list_checks,
    load_check,
    new_check_id,
    release_and_change,
    run_check,
)
from engine.watch.discovery import load_state
from utils import state

logger = get_logger(__name__)
_tasks: dict[str, asyncio.Task] = {}
_scheduler: asyncio.Task | None = None
_status: dict[str, Any] = {"last_scheduled_at": None, "next_run_at": None}


def _deps(client: Any) -> CheckDeps:
    return CheckDeps(
        store=state.get_store(),
        catalog=state.get_catalog(),
        client=client,
        ingest=IngestConfig.from_settings(settings.fetch),
        firecrawl=FirecrawlConfig.from_settings(settings.fetch),
        gemini=Gemini(settings.llm),
        watch=settings.watch,
        notify=settings.notify,
        catalog_path=settings.store.catalog_path,
    )


async def _run(
    check_id: str, source_ids: list[str] | None, trigger: str, discovery: bool | None
) -> dict[str, Any]:
    async with state.write_lock(), state.client_factory() as client:
        return await run_check(
            _deps(client),
            check_id=check_id,
            source_ids=source_ids,
            trigger=trigger,
            run_discovery=discovery,
        )


def start_check(
    source_ids: list[str] | None, *, trigger: str = "manual", discovery: bool | None = None
) -> tuple[str, asyncio.Task]:
    if source_ids:
        catalog = state.get_catalog()
        unknown = [i for i in source_ids if not catalog.get(i)]
        if unknown:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT, f"unknown source ids: {unknown}"
            )
    check_id = new_check_id()
    task = asyncio.create_task(_run(check_id, source_ids, trigger, discovery))
    _tasks[check_id] = task
    task.add_done_callback(lambda _t: _tasks.pop(check_id, None))
    return check_id, task


def get_check(check_id: str) -> dict[str, Any]:
    record = load_check(state.get_store(), check_id)
    if record:
        return record
    if check_id in _tasks:
        return {"check_id": check_id, "status": "queued"}
    raise HTTPException(status.HTTP_404_NOT_FOUND, "check not found")


async def build_release_now(force: bool = False) -> dict[str, Any]:
    async with state.write_lock(), state.client_factory() as client:
        try:
            return await release_and_change(_deps(client), trigger="api", force=force)
        except RuntimeError as exc:
            raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc


# ---- startup bootstrap and the scheduler -------------------------------------------------------


async def bootstrap() -> None:
    """Empty store: first full check (download + baseline release + discovery baseline).
    Text but no release yet: just build and activate the baseline."""
    store = state.get_store()
    try:
        if store.is_empty():
            if settings.app.bootstrap_on_start:
                _, task = start_check(None, trigger="bootstrap")
                await task
            return
        if not state.get_kb().versions():
            async with state.write_lock(), state.client_factory() as client:
                result = await release_and_change(_deps(client), trigger="bootstrap")
            logger.info("baseline_release", "Baseline release built", **result)
    except Exception:
        logger.exception("bootstrap_failed", "Bootstrap failed")


async def _schedule_loop(minutes: int) -> None:
    while True:
        next_at = datetime.now(UTC) + timedelta(minutes=minutes)
        _status["next_run_at"] = next_at.isoformat(timespec="seconds")
        await asyncio.sleep(minutes * 60)
        _status["last_scheduled_at"] = now_iso()
        try:
            _, task = start_check(None, trigger="schedule")
            await task
        except Exception:
            logger.exception("scheduled_check_failed", "Scheduled check failed")


def start_scheduler() -> None:
    global _scheduler
    minutes = settings.watch.interval_minutes
    if minutes > 0 and _scheduler is None:
        _scheduler = asyncio.create_task(_schedule_loop(minutes))
        logger.info("watch_scheduler_started", "Watch scheduler started", interval_minutes=minutes)


async def stop_all() -> None:
    global _scheduler
    tasks = list(_tasks.values()) + ([_scheduler] if _scheduler else [])
    for t in tasks:
        t.cancel()
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)
    _scheduler = None


async def wait_all() -> None:
    if _tasks:
        await asyncio.gather(*list(_tasks.values()), return_exceptions=True)


def watch_status() -> dict[str, Any]:
    store = state.get_store()
    return {
        "interval_minutes": settings.watch.interval_minutes,
        "scheduler": "on" if settings.watch.interval_minutes > 0 else "off",
        "discovery_enabled": settings.watch.discovery_enabled,
        "running": sorted(_tasks),
        "last_scheduled_at": _status["last_scheduled_at"],
        "next_run_at": _status["next_run_at"],
        "discovery_state": load_state(store.root),
        "recent_checks": [
            {
                k: c.get(k)
                for k in ("check_id", "status", "trigger", "started_at", "finished_at", "release")
            }
            for c in list_checks(store, limit=10)
        ],
    }


def integrations() -> dict[str, Any]:
    fc = FirecrawlConfig.from_settings(settings.fetch)
    gem = Gemini(settings.llm)
    webhook_secret = bool(settings.fetch.firecrawl_webhook_secret.get_secret_value())
    return {
        "gemini": {
            "active": gem.active,
            "model": gem.model,
            "used_for": ["change_type classification", "proposed-source triage"],
            "fallback": None if gem.active else "deterministic heuristics (GOOGLE_API_KEY not set)",
        },
        "firecrawl": {
            "active": fc.active,
            "features": {
                "scrape_change_tracking": fc.active,
                "search": fc.active,
                "map": fc.active,
                "challenge_fallback": fc.active,
                "webhook_signature": webhook_secret,
            },
            "fallback": None
            if fc.active
            else (
                "own sha256 diff for change detection; index-page link diff for discovery; "
                "search disabled (FIRECRAWL_API_KEY not set)"
            ),
        },
        "cellar_sparql": {
            "active": settings.watch.discovery_enabled,
            "url": settings.watch.sparql_url,
        },
        "telegram": {"active": telegram_active(settings.notify)},
        "backend_notify": {
            "active": backend_active(settings.notify),
            "url": settings.notify.backend_internal_url or None,
        },
        "watcher": {
            "interval_minutes": settings.watch.interval_minutes,
            "scheduler": "on" if settings.watch.interval_minutes > 0 else "off",
        },
        "demo_mirror": {"url": settings.watch.demo_mirror_url},
    }
