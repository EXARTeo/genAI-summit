"""Backend service: conversations, messages, attachments, agent runs and
their background sub-agent tasks.

The browser talks to this service; it
stores conversations in Postgres, starts runs on the agents service, consumes
their AG-UI event stream, and fans it out to the UI over WebSockets through a
Redis Streams event log. It also mirrors the agents service's background
tasks from Redis streams and wakes the orchestrator when they settle. No
login: callers are anonymous browser ids (``X-Client-Id``), rate-limited per
client and per IP.
"""

import asyncio
import subprocess  # noqa: S404 - runs alembic with a fixed argv
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi_pagination import add_pagination

from core.cache.integration import install_redis_sdk
from core.logging import (
    RequestLoggingMiddleware,
    configure_logging,
    get_logger,
    register_exception_handlers,
    scrub_url_credentials,
)
from core.settings import settings
from router import (
    attachments_router,
    conversations_router,
    inference_router,
    messages_router,
    search_router,
)
from router.admin import router as admin_router
from router.agents_catalog import router as agents_router
from router.audits import router as audits_router
from router.classifications import router as classifications_router
from router.findings import router as findings_router
from router.internal import router as internal_router
from router.internal_datasets import router as internal_datasets_router
from router.internal_findings import router as internal_findings_router
from router.internal_regulation import router as internal_regulation_router
from router.plugins import router as plugins_router
from router.register import router as register_router
from router.regulation import router as regulation_router
from router.systems import router as systems_router
from router.tasks import conversation_router as task_conversation_router
from router.tasks import router as tasks_router
from router.telegram import router as telegram_router
from utils.inference_runs import cleanup_orphaned_inference_runs, register_interrupt_hook
from utils.task_consumers import task_consumers
from utils.telegram_gates import notify_chat_interrupt, telegram_worker
from utils.tracing import shutdown_tracing

PACKAGE_ROOT = Path(__file__).resolve().parent

configure_logging()
logger = get_logger(__name__)


def _run_alembic_upgrade() -> None:
    """Apply pending migrations (``alembic upgrade head``) in a subprocess.

    A subprocess, not in-process: alembic's env.py runs its own event loop,
    which deadlocks inside uvicorn's. The child inherits DATABASE_URL.
    """
    result = subprocess.run(  # noqa: S603 - fixed argv, no shell
        [
            sys.executable,
            "-m",
            "alembic",
            "-c",
            str(PACKAGE_ROOT / "alembic.ini"),
            "upgrade",
            "head",
        ],
        cwd=str(PACKAGE_ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    # Field names must not be `output` / `text` / `input`: those are in the
    # log redaction drop-list and would be logged empty.
    stdout = scrub_url_credentials(result.stdout.strip()) if result.stdout else ""
    stderr = scrub_url_credentials(result.stderr.strip()) if result.stderr else ""
    if stdout:
        logger.info("alembic_subprocess_stdout", "Alembic subprocess output", alembic_stdout=stdout)
    if result.returncode == 0:
        # Alembic writes normal progress to stderr.
        if stderr:
            logger.info(
                "alembic_subprocess_stderr", "Alembic subprocess stderr", alembic_stderr=stderr
            )
        return
    logger.error(
        "alembic_upgrade_failed",
        "Alembic upgrade head failed",
        exit_code=result.returncode,
        alembic_stderr=stderr or "<no stderr captured>",
    )
    tail = " | ".join(stderr.splitlines()[-3:]) if stderr else "no stderr captured"
    raise RuntimeError(f"alembic upgrade head failed with exit code {result.returncode}: {tail}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("service_startup", "Backend startup initiated")
    if settings.database.run_migrations_on_startup:
        logger.info("database_migrations_started", "Running alembic upgrade head")
        await asyncio.to_thread(_run_alembic_upgrade)
        logger.info("database_migrations_completed", "Alembic upgrade head completed")
    else:
        logger.warning(
            "database_migrations_skipped",
            "RUN_MIGRATIONS_ON_STARTUP=false — skipping alembic upgrade head",
        )
    # Runs that were streaming when the process died are marked failed (and
    # their run-finished hooks run), before the task loops start: the first
    # reconcile pass then sees the conversations as they really are.
    await cleanup_orphaned_inference_runs()
    logger.info("database_schema_ready", "Database schema is ready")
    task_consumers.start()
    # Telegram HITL: long polling (or webhook registration); a no-op without a token.
    register_interrupt_hook(notify_chat_interrupt)
    await telegram_worker.start()
    yield
    await telegram_worker.stop()
    await task_consumers.stop()
    # Flush buffered Langfuse spans (no-op when tracing is off); off the loop
    # because the SDK's flush blocks.
    await asyncio.to_thread(shutdown_tracing)
    logger.info("service_shutdown", "Backend shutdown completed")


# The interactive docs map every route, so they exist only in development/test.
API_DOCS_ENABLED = settings.app.env in {"development", "test"}

app = FastAPI(
    title="Backend",
    description="Conversations, messages, attachments and AG-UI agent runs.",
    version=settings.app.version,
    docs_url="/docs" if API_DOCS_ENABLED else None,
    redoc_url="/redoc" if API_DOCS_ENABLED else None,
    openapi_url="/openapi.json" if API_DOCS_ENABLED else None,
    lifespan=lifespan,
)

register_exception_handlers(app)
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.cors.allowed_origins),
    allow_credentials=settings.cors.allow_credentials,
    allow_methods=list(settings.cors.allow_methods),
    allow_headers=list(settings.cors.allow_headers or ()),
    expose_headers=list(settings.cors.expose_headers),
    max_age=settings.cors.max_age_seconds,
)
# Redis SDK: pool lifespan (wraps the one above), the global per-IP budget
# middleware and the DI cache. Between request logging (outermost) and CORS.
install_redis_sdk(app)
app.add_middleware(RequestLoggingMiddleware)

add_pagination(app)


@app.get("/health", include_in_schema=False)
async def health() -> dict[str, str]:
    return {"status": "ok", "version": settings.app.version}


app.include_router(conversations_router, prefix="/v1/conversations", tags=["Conversations"])
app.include_router(messages_router, prefix="/v1/messages", tags=["Messages"])
app.include_router(attachments_router, prefix="/v1/attachments", tags=["Attachments"])
app.include_router(inference_router, prefix="/v1/inference", tags=["Inference"])
app.include_router(search_router, prefix="/v1/search", tags=["Search"])
app.include_router(tasks_router, prefix="/v1/tasks", tags=["Tasks"])
app.include_router(task_conversation_router, prefix="/v1/conversations", tags=["Tasks"])
app.include_router(plugins_router, prefix="/v1/systems", tags=["Plugins"])
app.include_router(classifications_router, prefix="/v1/systems", tags=["Classifications"])
app.include_router(systems_router, prefix="/v1/systems", tags=["Systems"])
app.include_router(audits_router, prefix="/v1/audits", tags=["Audits"])
app.include_router(findings_router, prefix="/v1", tags=["Findings"])
app.include_router(register_router, prefix="/v1", tags=["Register"])
app.include_router(admin_router, prefix="/v1/admin", tags=["Admin"])
app.include_router(internal_router, prefix="/internal", tags=["Internal"])
app.include_router(internal_datasets_router, prefix="/internal", tags=["Internal"])
app.include_router(internal_findings_router, prefix="/internal", tags=["Internal"])
app.include_router(internal_regulation_router, prefix="/internal", tags=["Internal"])
app.include_router(regulation_router, prefix="/v1/regulation", tags=["Regulation"])
app.include_router(agents_router, prefix="/v1/agents", tags=["Agents"])
app.include_router(telegram_router, prefix="/telegram", tags=["Telegram"])
