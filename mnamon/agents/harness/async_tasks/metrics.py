"""Task metrics, as structured log events.

The agents service exposes no ``/metrics`` endpoint, so the two metrics are
log events whose fields are the values, aggregated wherever the logs go:

* ``async_tasks_active`` — a gauge: ``value`` is the number of runs this
  process is executing, logged on every change;
* ``async_task_run_seconds`` — a histogram's samples: ``seconds`` per finished
  run, with its ``status``, ``kind`` and ``depth``.

Ids only, never prompts or results.
"""

from __future__ import annotations

from core.logging import get_logger

logger = get_logger(__name__)


def record_active(value: int) -> None:
    """The ``async_tasks_active`` gauge."""
    logger.info("async_tasks_active", "Background task runs in this process", value=value)


def record_run_seconds(*, seconds: float, status: str, kind: str, task_id: str, depth: int) -> None:
    """One ``async_task_run_seconds`` sample."""
    logger.info(
        "async_task_run_seconds",
        "Background task run finished",
        seconds=round(seconds, 3),
        status=status,
        kind=kind,
        task_id=task_id,
        depth=depth,
    )


__all__ = ["record_active", "record_run_seconds"]
