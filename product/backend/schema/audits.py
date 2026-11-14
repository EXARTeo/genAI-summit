"""Audit DTOs: audits, their versioned artifacts and the human approvals."""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from schema.base import UTCDateTime

#: A free-form but tidy identifier (artifact kinds, gates, stages, names).
SLUG_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$"

ArtifactStatus = Literal["proposed", "approved", "rejected", "changes_requested", "superseded"]
Decision = Literal["approved", "rejected", "changes_requested"]
ReasonCategory = Literal[
    "wrong_fact",
    "wrong_interpretation",
    "missing_info",
    "wrong_metric",
    "unrealistic_data",
    "org_policy",
    "other",
]


class AuditIn(BaseModel):
    stage: str = Field("context", pattern=SLUG_PATTERN)
    data: dict[str, Any] = Field(default_factory=dict)


class AuditPatch(BaseModel):
    status: str | None = Field(None, pattern=SLUG_PATTERN)
    stage: str | None = Field(None, pattern=SLUG_PATTERN)
    data: dict[str, Any] | None = None


class ArtifactOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    auditId: str = Field(..., validation_alias="audit_id")
    kind: str
    name: str
    version: int
    status: str
    data: dict[str, Any] = Field(default_factory=dict)
    fileRefs: list[Any] = Field(default_factory=list, validation_alias="file_refs")
    parentId: str | None = Field(None, validation_alias="parent_id")
    createdBy: str = Field(..., validation_alias="created_by")
    createdAt: UTCDateTime = Field(..., validation_alias="created_at")
    updatedAt: UTCDateTime = Field(..., validation_alias="updated_at")


class ArtifactIn(BaseModel):
    """A new version of the (kind, name) slot; earlier live versions are superseded."""

    kind: str = Field(..., pattern=SLUG_PATTERN)
    name: str = Field("main", pattern=SLUG_PATTERN)
    data: dict[str, Any] = Field(default_factory=dict)
    fileRefs: list[Any] = Field(default_factory=list)
    parentId: str | None = None
    status: ArtifactStatus = "proposed"


class ArtifactPatch(BaseModel):
    status: ArtifactStatus | None = None
    data: dict[str, Any] | None = None


class ApprovalIn(BaseModel):
    gate: str = Field(..., pattern=SLUG_PATTERN)
    decision: Decision
    artifactId: str | None = None
    reasonCategory: ReasonCategory | None = None
    comment: str | None = Field(None, max_length=10_000)
    edits: dict[str, Any] = Field(default_factory=dict)


class ApprovalOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    auditId: str = Field(..., validation_alias="audit_id")
    artifactId: str | None = Field(None, validation_alias="artifact_id")
    gate: str
    decision: str
    reasonCategory: str | None = Field(None, validation_alias="reason_category")
    comment: str | None = None
    edits: dict[str, Any] = Field(default_factory=dict)
    decidedBy: str = Field(..., validation_alias="decided_by")
    at: UTCDateTime


class ApprovalResultOut(BaseModel):
    approval: ApprovalOut
    artifact: ArtifactOut | None = None


class AuditOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    systemId: str = Field(..., validation_alias="system_id")
    status: str
    stage: str
    createdBy: str | None = Field(None, validation_alias="created_by")
    data: dict[str, Any] = Field(default_factory=dict)
    createdAt: UTCDateTime = Field(..., validation_alias="created_at")
    updatedAt: UTCDateTime = Field(..., validation_alias="updated_at")


class AuditDetail(AuditOut):
    artifacts: list[ArtifactOut] = Field(default_factory=list)
    approvals: list[ApprovalOut] = Field(default_factory=list)
