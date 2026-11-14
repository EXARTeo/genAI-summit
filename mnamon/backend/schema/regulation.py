"""Regulation DTOs: reg-memory as the frontend sees it (camelCase; mirrors
``mnamon/frontend/src/features/regulation/lib/types.ts``)."""

from typing import Any, Literal

from pydantic import BaseModel, Field

JudgeDecision = Literal[
    "no_impact", "reinterpret_existing_evidence", "rerun_tests", "new_tests_needed"
]


class DocVersionOut(BaseModel):
    version: int
    fetchedAt: str
    sha256: str
    status: Literal["new", "changed", "same", "failed"]
    bytes: int
    diff: dict[str, Any] | None = None


class RegSourceOut(BaseModel):
    id: str
    title: str
    kind: str
    binding: bool | Literal["internal"]
    status: str
    publisher: str
    url: str | None = None
    tags: list[str] = Field(default_factory=list)
    documents: int = 0
    versions: list[DocVersionOut] = Field(default_factory=list)


class DocTextOut(BaseModel):
    docId: str
    version: int
    text: str


class DocDiffOut(BaseModel):
    docId: str
    from_: int = Field(..., serialization_alias="from", validation_alias="from")
    to: int
    unified: str


class AffectedSystemOut(BaseModel):
    systemId: str
    systemName: str
    path: list[str] = Field(default_factory=list)
    findings: list[str] = Field(default_factory=list)
    decision: JudgeDecision
    confidence: float = 0.0
    reasoning: str = ""
    humanDecision: JudgeDecision | None = None
    rerunAuditId: str | None = None


class RegChangeOut(BaseModel):
    id: str
    sourceId: str
    title: str
    detectedAt: str
    changeType: Literal["editorial", "clarification", "scope_change", "new_obligation", "repeal"]
    provisions: list[str]
    fromVersion: int
    toVersion: int
    candidateKbVersion: str
    status: Literal["proposed", "accepted", "rejected"]
    summary: str
    affected: list[AffectedSystemOut]
    traceId: str | None = None
    #: Not in the UI type yet: reg-memory's impact index (requirement ids + via).
    impactedRequirements: list[dict[str, Any]] = Field(default_factory=list)
    #: ``pending`` until a per-system judge (or a human override) fills ``affected``.
    judge: Literal["pending", "done"] = "pending"
    decidedBy: str | None = None


class ChangeDecisionIn(BaseModel):
    status: Literal["accepted", "rejected"]
    reason: str | None = Field(None, max_length=4000)


class JudgeOverrideIn(BaseModel):
    decision: JudgeDecision


class ActivateIn(BaseModel):
    by: str | None = Field(None, max_length=200)


class CheckNowIn(BaseModel):
    source_ids: list[str] | None = Field(None, alias="sourceIds", max_length=50)
    wait: bool = False
    discovery: bool | None = None

    model_config = {"populate_by_name": True}


class RegChangeNotifyIn(BaseModel):
    """What reg-memory POSTs on a new RegChange (``engine/notify.py``)."""

    model_config = {"extra": "allow"}

    id: str = Field(..., min_length=1, max_length=200)
    from_kb_version: str | None = None
    to_kb_version: str | None = None
    created_at: str | None = None
    summary: str | None = None
    counts: dict[str, Any] | None = None
    change_types: dict[str, Any] | None = None
    impacted_requirements: list[dict[str, Any]] | None = None
    items: list[dict[str, Any]] = Field(default_factory=list)


class JudgementIn(BaseModel):
    """``PUT /internal/regulation/changes/{id}/judgement``: the agents' change judge result.

    ``affected`` entries are ``AffectedSystemOut``-shaped (``systemId``, ``systemName``,
    ``path``, ``findings``, ``decision``, ``confidence``, ``reasoning``, ``rerunAuditId``)
    plus ``counterArgument``, ``auditId``, ``artifactId``, ``decidedBy``.
    """

    affected: list[dict[str, Any]] = Field(default_factory=list, max_length=500)
    decidedBy: str = Field("gemini", max_length=64)  # noqa: N815
