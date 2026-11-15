"""Sealed-finding DTOs (plan 01 §7.2): the pipeline's sealed verdicts, human
annotations and status events. Field names are snake_case, the same shape the
agents service posts, so writers and readers share one contract."""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from schema.audits import SLUG_PATTERN
from schema.base import UTCDateTime

Verdict = Literal[
    "pass", "partial", "gap", "inconclusive", "not_applicable", "not_assessable_by_testing"
]
Severity = Literal["critical", "high", "medium", "low"]
AnnotationKind = Literal["contest", "accept_risk", "remediation_planned", "comment"]
HASH_PATTERN = r"^[A-Za-z0-9:_-]{8,200}$"


class EvidenceRef(BaseModel):
    model_config = ConfigDict(extra="allow")

    path: str = Field(..., max_length=1000)
    sha256: str | None = Field(None, max_length=128)
    mlflow_run_id: str | None = Field(None, max_length=200)


class CitationRef(BaseModel):
    model_config = ConfigDict(extra="allow")

    provision_id: str = Field(..., max_length=200)
    kb_version: str | None = Field(None, max_length=100)


class FindingIn(BaseModel):
    """One sealed finding. Unknown fields (``article``, ``title``, ...) are kept in ``data``."""

    model_config = ConfigDict(extra="allow")

    id: str | None = Field(None, pattern=SLUG_PATTERN)
    obligation_id: str = Field(..., min_length=1, max_length=200)
    verdict: Verdict
    severity: Severity | None = None
    gap_id: str | None = Field(None, max_length=100)
    metrics_ref: Any = None
    evidence_refs: list[EvidenceRef] = Field(default_factory=list, max_length=500)
    citations: list[CitationRef] = Field(default_factory=list, max_length=500)
    kb_version: str | None = Field(None, max_length=100)
    reasoning: str | None = Field(None, max_length=50_000)
    counter_arguments: Any = None
    would_change_if: Any = None
    judges: dict[str, Any] = Field(default_factory=dict)
    critic: dict[str, Any] = Field(default_factory=dict)
    prev_hash: str | None = Field(None, pattern=HASH_PATTERN)
    hash: str | None = Field(None, pattern=HASH_PATTERN)


class AnnotationIn(BaseModel):
    kind: AnnotationKind
    body: str = Field(..., min_length=1, max_length=5_000)


class AnnotationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    finding_id: str
    kind: str
    body: str
    actor: str
    created_at: UTCDateTime


class StatusEventIn(BaseModel):
    status: str = Field(..., pattern=SLUG_PATTERN)
    superseded_by: str | None = Field(None, max_length=200)
    reason: str | None = Field(None, max_length=10_000)
    data: dict[str, Any] = Field(default_factory=dict)


class StatusEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    finding_id: str
    status: str
    superseded_by: str | None = None
    reason: str | None = None
    data: dict[str, Any] = Field(default_factory=dict)
    actor: str
    created_at: UTCDateTime


class FindingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    audit_id: str
    system_id: str
    obligation_id: str
    verdict: str
    severity: str | None = None
    gap_id: str | None = None
    metrics_ref: Any = None
    evidence_refs: list[Any] = Field(default_factory=list)
    citations: list[Any] = Field(default_factory=list)
    kb_version: str | None = None
    reasoning: str | None = None
    counter_arguments: Any = None
    would_change_if: Any = None
    judges: dict[str, Any] = Field(default_factory=dict)
    critic: dict[str, Any] = Field(default_factory=dict)
    data: dict[str, Any] = Field(default_factory=dict)
    prev_hash: str | None = None
    hash: str
    created_by: str
    created_at: UTCDateTime
    #: The latest status event's status, ``current`` when there is none.
    status: str = "current"
    stale: bool = False
    sealed: bool = True
    annotations: list[AnnotationOut] = Field(default_factory=list)
    status_events: list[StatusEventOut] = Field(default_factory=list)
