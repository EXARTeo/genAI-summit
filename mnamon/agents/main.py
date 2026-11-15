"""The agents service: runs the agents and streams AG-UI to the backend.

The app factory, its lifespan and ``/health``. The lifespan opens Langfuse
(opt-in), the ``agent_runtime`` database (created when missing) with the
durable checkpointer and the stores' tables, and, with
``ASYNC_SUBAGENTS_ENABLED``, the background-task runner (recovering the runs a
restart cut). Routes: ``router/``.
"""

import asyncio
from contextlib import asynccontextmanager, suppress
from typing import Any

from fastapi import FastAPI

from core.logging import (
    RequestLoggingMiddleware,
    configure_logging,
    get_logger,
    register_exception_handlers,
    shutdown_logging,
)
from core.settings import settings
from harness.async_tasks.client import set_protocol_app
from harness.async_tasks.events import TaskStreamPublisher
from harness.async_tasks.runner import TaskRunner, set_task_runner
from harness.async_tasks.store import AsyncTaskStore
from harness.checkpointer import init_durable_checkpointer
from harness.observability import init_langfuse, shutdown_langfuse
from router.agent_protocol import router as agent_protocol_router
from router.audits import router as audits_router
from router.catalog import router as catalog_router
from router.classifications import router as classifications_router
from router.inference import router as inference_router
from router.memory import router as memory_router
from router.tasks import router as tasks_router

configure_logging()
logger = get_logger(__name__)


def _make_loop_exception_handler(old_handler: Any = None) -> Any:
    """An event-loop handler that drops disconnect noise and logs the rest."""

    def handler(loop: asyncio.AbstractEventLoop, context: dict[str, Any]) -> None:
        ex = context.get("exception")
        # A client that went away is how a cancelled run ends: not an error.
        if isinstance(ex, (asyncio.CancelledError, BrokenPipeError, ConnectionResetError)):
            return
        # LangGraph callback noise on cancellation.
        msg = context.get("message", "")
        text = f"{msg} {context.get('handle') or context.get('task')!r}"
        if isinstance(ex, TypeError) and "NoneType" in str(ex) and "langgraph" in text:
            return
        logger.error(
            "event_loop_exception",
            "Unhandled event loop exception",
            exc_info=bool(ex),
            exception_type=type(ex).__name__ if ex is not None else None,
            loop_message=msg or None,
        )
        if old_handler is not None:
            old_handler(loop, context)
            return
        loop.default_exception_handler(context)

    return handler


@asynccontextmanager
async def _lifespan(app: FastAPI):
    loop = asyncio.get_running_loop()
    old = loop.get_exception_handler()
    loop.set_exception_handler(_make_loop_exception_handler(old))
    pool = None
    task_runner: TaskRunner | None = None
    try:
        logger.info("service_startup", "Agents service startup initiated")
        # A no-op without LANGFUSE_BASE_URL + keys; a client that cannot start
        # leaves tracing off, never the service.
        init_langfuse()
        # Fail fast and loud when agent_runtime is unreachable: cross-turn
        # resume depends on it.
        await init_durable_checkpointer(app)
        pool = app.state.checkpointer_pool
        task_store = AsyncTaskStore(pool)
        if settings.checkpointer.setup_on_startup:
            await task_store.setup()
        if settings.async_tasks.enabled:
            task_runner = TaskRunner(task_store, TaskStreamPublisher())
            set_task_runner(task_runner)
            # Runs a restart cut settle as errors; their parents are told.
            await task_runner.recover()
        yield
    finally:
        if task_runner is not None:
            set_task_runner(None)
            await task_runner.shutdown()
        if pool is not None:
            await pool.close()
        # Last, once the runs have stopped: flush their queued spans. The flush
        # blocks (bounded by the exporter's timeout), so it runs off-loop.
        with suppress(RuntimeError):
            await asyncio.to_thread(shutdown_langfuse)
        loop.set_exception_handler(old)
        logger.info("service_shutdown", "Agents service shutdown completed")
        shutdown_logging()


app = FastAPI(lifespan=_lifespan, title="Agents Service")
register_exception_handlers(app)
app.add_middleware(RequestLoggingMiddleware)
# Async sub-agents call /ap through this app in process (harness.async_tasks.client).
set_protocol_app(app)


@app.get("/health", include_in_schema=False)
async def health() -> dict[str, str]:
    """Liveness for the container healthcheck (no caller check, no I/O)."""
    return {"status": "ok"}


app.include_router(agent_protocol_router)
app.include_router(audits_router)
app.include_router(catalog_router)
app.include_router(classifications_router)
app.include_router(inference_router)
app.include_router(memory_router)
app.include_router(tasks_router)
