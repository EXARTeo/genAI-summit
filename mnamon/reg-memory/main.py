"""reg-memory: the regulation store of the AI Act Governance Copilot.

Downloads the EU AI Act and supporting documents (catalog in
engine/catalog/sources.yaml), keeps every version on disk in one data volume
(raw bytes, extracted text, diffs, manifests, runs), parses them into provisions
and interpretations, snapshots them with the requirements / test-template corpus
into kb releases, watches the sources (a RegChange for every provision-level
change) and serves all of it over a small internal API. Callers are other
services of the stack, proven by
``X-Internal-Secret``; every route is rate-limited and logged.
"""

import asyncio
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
from router.changes import router as changes_router
from router.demo import public_router as demo_public_router
from router.demo import router as demo_router
from router.documents import router as documents_router
from router.health import router as health_router
from router.ingest import router as ingest_router
from router.integrations import router as integrations_router
from router.obligations import router as obligations_router
from router.provisions import interpretations_router
from router.provisions import router as provisions_router
from router.releases import router as releases_router
from router.requirements import router as requirements_router
from router.requirements import templates_router
from router.sources import router as sources_router
from router.watch import router as watch_router
from router.webhooks import router as webhooks_router
from utils import watch
from utils.ingest import cancel_all

configure_logging()
logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("service_startup", "reg-memory startup initiated")
    settings.store.data_dir.mkdir(parents=True, exist_ok=True)
    # Empty store: first download + baseline release; text without a release: baseline only.
    bootstrap = asyncio.create_task(watch.bootstrap())
    watch.start_scheduler()
    yield
    bootstrap.cancel()
    await watch.stop_all()
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
app.include_router(
    provisions_router, prefix="/v1/provisions", tags=["Provisions"], dependencies=_INTERNAL
)
app.include_router(
    interpretations_router,
    prefix="/v1/interpretations",
    tags=["Provisions"],
    dependencies=_INTERNAL,
)
app.include_router(
    releases_router, prefix="/v1/releases", tags=["Releases"], dependencies=_INTERNAL
)
app.include_router(changes_router, prefix="/v1/changes", tags=["Changes"], dependencies=_INTERNAL)
app.include_router(
    requirements_router, prefix="/v1/requirements", tags=["Requirements"], dependencies=_INTERNAL
)
app.include_router(
    obligations_router, prefix="/v1/obligations", tags=["Requirements"], dependencies=_INTERNAL
)
app.include_router(
    templates_router, prefix="/v1/test-templates", tags=["Requirements"], dependencies=_INTERNAL
)
app.include_router(
    integrations_router, prefix="/v1/integrations", tags=["Watch"], dependencies=_INTERNAL
)
app.include_router(watch_router, prefix="/v1/watch", tags=["Watch"], dependencies=_INTERNAL)
app.include_router(demo_router, prefix="/v1/demo/mirror", tags=["Demo"], dependencies=_INTERNAL)
# Own auth (Firecrawl signature or X-Internal-Secret), see router/webhooks.py.
app.include_router(webhooks_router, prefix="/v1/webhooks", tags=["Watch"])
# The public demo page (what the demo source fetches).
app.include_router(demo_public_router, prefix="/demo/mirror", tags=["Demo"])
