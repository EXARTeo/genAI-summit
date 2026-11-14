"""sandbox-runner: runs the agents' ``execute`` commands in a throwaway workdir.

``POST /v1/exec`` (contract: product/agents/harness/filesystem/sandbox_backend.py)
writes the call's input/ and output/ files into a fresh temp dir, runs the
command under time/memory/output/disk limits and returns the streams plus every
new or changed output/ file. The image ships ``synthkit`` (deterministic
synthetic test data: profile → generate → analyze) and the ML stack the seed
models need. Callers prove themselves with ``X-Internal-Proxy-Secret``.
"""

from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI

from core.logging import (
    RequestLoggingMiddleware,
    configure_logging,
    get_logger,
    register_exception_handlers,
)
from core.security.client import get_caller
from core.security.rate_limit import IpBudgetMiddleware
from core.settings import settings
from router.exec import router as exec_router
from router.health import router as health_router

configure_logging()
logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings.exec.work_root.mkdir(parents=True, exist_ok=True)
    logger.info("service_startup", "sandbox-runner started")
    yield
    logger.info("service_shutdown", "sandbox-runner stopped")


API_DOCS_ENABLED = settings.app.is_local

app = FastAPI(
    title="sandbox-runner",
    description="Runs commands for the agents service in an isolated, limited workdir.",
    version=settings.app.version,
    docs_url="/docs" if API_DOCS_ENABLED else None,
    redoc_url="/redoc" if API_DOCS_ENABLED else None,
    openapi_url="/openapi.json" if API_DOCS_ENABLED else None,
    lifespan=lifespan,
)

register_exception_handlers(app)
app.add_middleware(IpBudgetMiddleware)
app.add_middleware(RequestLoggingMiddleware)

app.include_router(health_router)
app.include_router(
    exec_router, prefix="/v1/exec", tags=["Exec"], dependencies=[Depends(get_caller)]
)
