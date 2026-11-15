"""model-gateway: the seed models behind production-style REST endpoints.

The audit agent tests AI systems the way it would in a real company: over the
network, through an authenticated, rate-limited API, not by loading model
files. This service makes the seed models (registered in MLflow with the alias
``champion``) look like that: bearer-token auth, a per-token rate limit,
optional latency, request ids and structured logs on every call.

- ``POST /v1/models/{name}/predict``: one model (signature-validated).
- ``POST /v1/systems/sys-001/screen``: the SYS-001 pipeline, parser -> ranker.

Models load lazily on first call; until MLflow has them, calls answer 503.
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
from core.security.rate_limit import IpBudgetMiddleware, token_rate_limit
from core.settings import settings
from router.health import router as health_router
from router.models import router as models_router
from router.systems import router as systems_router
from utils.latency import inject_latency

configure_logging()
logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(
        "service_startup",
        "model-gateway startup initiated",
        auth_configured=bool(settings.security.token.get_secret_value()),
        latency_ms=settings.app.latency_ms,
    )
    yield
    logger.info("service_shutdown", "model-gateway shutdown completed")


# The interactive docs map every route, so they exist only in development/test.
API_DOCS_ENABLED = settings.app.is_local

app = FastAPI(
    title="model-gateway",
    description="Seed models served as production-style REST endpoints.",
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

# Auth, then the per-token limit, then the simulated network latency.
_GATED = [Depends(get_caller), Depends(token_rate_limit), Depends(inject_latency)]
app.include_router(health_router)
app.include_router(models_router, prefix="/v1/models", tags=["Models"], dependencies=_GATED)
app.include_router(systems_router, prefix="/v1/systems", tags=["Systems"], dependencies=_GATED)
