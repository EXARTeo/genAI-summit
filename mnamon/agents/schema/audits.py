"""Audit-pipeline DTOs: ``/audits/{id}/run``, ``/audits/{id}/resume``, ``/changes/{id}/judge``."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

ID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$"


class AuditRunIn(BaseModel):
    """Start (or continue) the pipeline of an audit the backend created."""

    system_id: str = Field(..., pattern=ID_PATTERN)
    trigger: str | None = Field(None, max_length=200)
    client_id: str | None = Field(None, max_length=128)
    trace: dict[str, Any] | None = None


class AuditResumeIn(BaseModel):
    """A human decision at a gate (the backend's approval, forwarded)."""

    system_id: str = Field(..., pattern=ID_PATTERN)
    gate: str = Field(..., pattern=ID_PATTERN)
    decision: Literal["approved", "rejected", "changes_requested", "approve", "reject"]
    reasonCategory: str | None = Field(None, max_length=64)  # noqa: N815 - the backend's casing
    comment: str | None = Field(None, max_length=10_000)
    edits: dict[str, Any] = Field(default_factory=dict)
    artifactId: str | None = None  # noqa: N815
    decidedBy: str | None = Field(None, max_length=200)  # noqa: N815
    trace: dict[str, Any] | None = None


class AuditRunOut(BaseModel):
    audit_id: str
    thread_id: str
    status: Literal["started", "resumed", "running"]


class AuditStateOut(BaseModel):
    audit_id: str
    thread_id: str
    running: bool
    next: list[str]
    pending_gate: dict[str, Any] | None
    status: str | None
    stage_artifacts: dict[str, Any]


class ChangeJudgeIn(BaseModel):
    """Judge a reg-memory RegChange for every affected system (or the listed ones)."""

    system_ids: list[str] | None = None
    rerun: bool = Field(False, description="Start a new audit where the judge says re-run.")
    change: dict[str, Any] | None = Field(
        None, description="The RegChange itself (default: fetched from reg-memory by id)."
    )
    systems: list[dict[str, Any]] | None = Field(
        None,
        description=(
            "Per system {system_id, name, card, findings}: the card the obligation map is "
            "resolved from and its current sealed findings (the backend sends them on accept)."
        ),
        max_length=500,
    )


class ChangeJudgementOut(BaseModel):
    system_id: str
    audit_id: str | None
    decision: str
    rationale: str
    strongest_counter_argument: str
    affected_findings: list[str]
    affected_requirements: list[str]
    confidence: float
    decided_by: str
    artifact_id: str | None = None
    rerun_audit_id: str | None = None
    #: The system's applicable obligations the change touched (the focused re-run's scope).
    affected_obligations: list[str] = Field(default_factory=list)
    #: Old findings marked ``stale`` (sealed status events or ``finding_status`` artifacts).
    stale_findings: list[str] = Field(default_factory=list)


class ChangeJudgeOut(BaseModel):
    change_id: str
    kb_version: str | None
    impacted_requirements: list[str]
    judgements: list[ChangeJudgementOut]
