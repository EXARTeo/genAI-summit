"""Background ingest runs: one at a time (they share manifests), tracked by run id."""

from __future__ import annotations

import asyncio

from fastapi import HTTPException, status

from core.logging import get_logger
from core.settings import settings
from engine.ingest import IngestConfig, new_run_id, run_ingest
from schema.ingest import IngestRun
from utils import state

logger = get_logger(__name__)
_lock = asyncio.Lock()
_tasks: dict[str, asyncio.Task] = {}


async def _run(run_id: str, source_ids: list[str] | None, force: bool) -> None:
    async with _lock, state.client_factory() as client:
        try:
            await run_ingest(
                state.get_catalog(),
                state.get_store(),
                client,
                IngestConfig.from_settings(settings.fetch),
                source_ids=source_ids,
                force=force,
                run_id=run_id,
                catalog_path=settings.store.catalog_path,
            )
        except Exception:
            logger.exception("ingest_run_failed", "Ingest run failed", run_id=run_id)


def start_ingest(source_ids: list[str] | None, force: bool) -> str:
    if source_ids:
        catalog = state.get_catalog()
        unknown = [i for i in source_ids if not catalog.get(i)]
        if unknown:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT, f"unknown source ids: {unknown}"
            )
    run_id = new_run_id()
    task = asyncio.create_task(_run(run_id, source_ids, force))
    _tasks[run_id] = task
    task.add_done_callback(lambda _t: _tasks.pop(run_id, None))
    return run_id


def get_run(run_id: str) -> IngestRun:
    run = state.get_store().load_run(run_id)
    if run:
        return IngestRun(**run)
    if run_id in _tasks:  # waiting for the lock: not started yet
        return IngestRun(run_id=run_id, status="queued", started_at="")
    raise HTTPException(status.HTTP_404_NOT_FOUND, "run not found")


async def wait_all() -> None:
    """Await running ingests (tests, shutdown)."""
    if _tasks:
        await asyncio.gather(*list(_tasks.values()), return_exceptions=True)


async def cancel_all() -> None:
    for task in list(_tasks.values()):
        task.cancel()
    await wait_all()
