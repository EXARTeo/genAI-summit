from fastapi import APIRouter

from core.settings import settings

router = APIRouter()


# Exempt from the per-IP budget and not logged (the container probe).
@router.get("/health", include_in_schema=False)
async def health() -> dict[str, str]:
    return {"status": "ok", "version": settings.app.version}
