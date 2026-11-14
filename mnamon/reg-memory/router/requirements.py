from datetime import date as Date
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query

from core.security.rate_limit import read_rate_limit
from schema.kb import RequirementList, TestTemplateList
from utils.kb import requirements, test_templates

router = APIRouter(dependencies=[Depends(read_rate_limit)])
templates_router = APIRouter(dependencies=[Depends(read_rate_limit)])


@router.get("", response_model=RequirementList)
async def applicable_requirements(
    role: str | None = Query(None, max_length=40, description="provider | deployer | ..."),
    risk_class: str | None = Query(None, max_length=40, description="high | limited | ..."),
    basis: str | None = Query(None, max_length=80, description="AIA.ANNEX_III.4.a or annex_iii"),
    date: Annotated[Date | None, Query(description="in force on this date (default today)")] = None,
    feature: Annotated[list[str] | None, Query(description="e.g. interacts_with_persons")] = None,
    testability: Literal["model_and_data_test", "documentation", "process"] | None = None,
    kb_version: str | None = None,
) -> RequirementList:
    """The applicability query used by the agents' load_context."""
    return requirements(kb_version, role, risk_class, basis, date, feature, testability)


@templates_router.get("", response_model=TestTemplateList)
async def list_test_templates(kb_version: str | None = None) -> TestTemplateList:
    return test_templates(kb_version)
