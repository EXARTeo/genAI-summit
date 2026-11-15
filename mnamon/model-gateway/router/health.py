from fastapi import APIRouter

from core.settings import settings
from schema.health import HealthResponse
from utils.models import registry

router = APIRouter()

# No simulated endpoints: every system is a real MLflow model.
SIMULATED_ENDPOINTS: list[str] = []


# Exempt from the per-IP budget and not logged (the container probe). Never
# loads a model: it reports what is cached so far.
@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(
        status="ok",
        version=settings.app.version,
        models=registry.status(),
        simulated=SIMULATED_ENDPOINTS,
    )
