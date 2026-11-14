"""``GET /agents``: the agents this service runs, so a UI can pick one."""

from fastapi import APIRouter, Depends, status

from core.logging import get_logger
from core.security.internal_trust import require_internal_caller
from schema.catalog import AgentManifest
from utils.agents import list_agent_manifests

logger = get_logger(__name__)

router = APIRouter()


@router.get(
    "/agents",
    response_model=list[AgentManifest],
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(require_internal_caller)],
)
async def get_available_agents() -> list[AgentManifest]:
    """Every registered agent, by name, with the default one marked."""
    manifests = list_agent_manifests()
    logger.info("agents_manifest_listed", "Served available agents", count=len(manifests))
    return manifests
