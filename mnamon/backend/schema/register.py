"""Findings-register DTOs: a system's state per obligation across audits.

snake_case, like the sealed findings, so the agents service reads the same shape.
"""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from schema.base import UTCDateTime

RegisterState = Literal["open", "closed", "resolved", "monitoring"]


class RegisterEvent(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    at: str
    audit_id: str | None = None
    actor: str
    # opened | first_seen | still_open | verdict_changed | resolved | regressed |
    # closed | reopened | checked
    kind: str
    from_: str | None = Field(None, alias="from")
    to: str | None = None
    verdict: str | None = None
    note: str | None = None


class RegisterItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    system_id: str
    obligation_id: str
    state: str
    verdict: str
    severity: str | None = None
    article: str | None = None
    title: str | None = None
    gap_id: str | None = None
    first_seen_audit_id: str
    last_seen_audit_id: str
    last_finding_id: str | None = None
    opened_at: UTCDateTime | None = None
    closed_by: str | None = None
    close_reason: str | None = None
    closed_at: UTCDateTime | None = None
    created_at: UTCDateTime
    updated_at: UTCDateTime
    #: The register status the last audit gave this item
    #: (new | still_open | resolved | regressed | accepted_risk | unchanged).
    last_status: str | None = None
    #: The last finding's reasoning (clipped) and evidence paths.
    last_reasoning: str | None = None
    last_evidence: list[str] = Field(default_factory=list)


class RegisterItemDetail(RegisterItemOut):
    history: list[dict[str, Any]] = Field(default_factory=list)


class RegisterSummary(BaseModel):
    total: int = 0
    by_state: dict[str, int] = Field(default_factory=dict)
    by_verdict: dict[str, int] = Field(default_factory=dict)
    open_gaps: int = 0
    needs_review: int = 0
    accepted_risks: int = 0
    resolved: int = 0
    monitoring: int = 0


class RegisterOut(BaseModel):
    system_id: str
    summary: RegisterSummary
    items: list[RegisterItemDetail]


class CloseIn(BaseModel):
    reason: str = Field(..., min_length=1, max_length=5_000)


class ReopenIn(BaseModel):
    reason: str | None = Field(None, max_length=5_000)


class RebuildOut(BaseModel):
    reset: bool
    audits_applied: list[str] = Field(default_factory=list)
    items: int = 0
