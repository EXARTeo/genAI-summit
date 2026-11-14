"""reg-memory: the regulation store of the AI Act Governance Copilot.

Downloads the EU AI Act and supporting documents (catalog in
engine/catalog/sources.yaml), keeps every version on disk in one data volume
(raw bytes, extracted text, diffs, manifests, runs) and serves them over a
small internal API. Callers are other services of the stack, proven by
``X-Internal-Secret``; every route is rate-limited and logged.
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
from router.documents import router as documents_router
from router.health import router as health_router
from router.ingest import router as ingest_router
from router.sources import router as sources_router
from utils.ingest import cancel_all, start_ingest
from utils.state import get_store

configure_logging()
logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("service_startup", "reg-memory startup initiated")
    settings.store.data_dir.mkdir(parents=True, exist_ok=True)
    if settings.app.bootstrap_on_start and get_store().is_empty():
        run_id = start_ingest(None, False)
        logger.info("bootstrap_ingest_started", "Store empty: first ingest started", run_id=run_id)
    yield
    await cancel_all()
    logger.info("service_shutdown", "reg-memory shutdown completed")


# The interactive docs map every route, so they exist only in development/test.
API_DOCS_ENABLED = settings.app.is_local

app = FastAPI(
    title="reg-memory",
    description="Versioned store of the EU AI Act and supporting documents.",
    version=settings.app.version,
    docs_url="/docs" if API_DOCS_ENABLED else None,
    redoc_url="/redoc" if API_DOCS_ENABLED else None,
    openapi_url="/openapi.json" if API_DOCS_ENABLED else None,
    lifespan=lifespan,
)

register_exception_handlers(app)
# Global per-IP budget inside request logging (outermost), as in the backend.
app.add_middleware(IpBudgetMiddleware)
app.add_middleware(RequestLoggingMiddleware)

_INTERNAL = [Depends(get_caller)]
app.include_router(health_router)
app.include_router(sources_router, prefix="/v1/sources", tags=["Sources"], dependencies=_INTERNAL)
app.include_router(ingest_router, prefix="/v1/ingest", tags=["Ingest"], dependencies=_INTERNAL)
app.include_router(
    documents_router, prefix="/v1/documents", tags=["Documents"], dependencies=_INTERNAL
)
