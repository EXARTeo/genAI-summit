"""Risk-classification DTOs (plan 02 §7-§8): the run row with its events, the
human decision, the obligations preview, and the agents' ``ClassificationResult``.

The result is validated loosely here (the agents service owns the strict model):
the fields the backend reads are typed, everything else is kept as returned.
"""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from schema.base import UTCDateTime

RiskClass = Literal["prohibited", "high_risk", "limited_risk", "minimal_risk", "out_of_scope"]
Route = Literal[
    "art5",
    "art6_1_annex_i",
    "art6_2_annex_iii",
    "art6_3_exempt",
    "art50_only",
    "none",
    "not_ai_system",
]
ClassificationStatus = Literal[
    "running", "proposed", "failed", "approved", "rejected", "stale", "superseded"
]


class _Loose(BaseModel):
    model_config = ConfigDict(extra="allow")


class Art63(_Loose):
    considered: bool = False
    condition: Literal["a", "b", "c", "d"] | None = None
    profiling: str | None = None
    holds: bool | None = None
    why: str | None = None


class Transparency(_Loose):
    features: list[str] = Field(default_factory=list)
    provisions: list[str] = Field(default_factory=list)


class Citation(_Loose):
    id: str
    kb_version: str | None = None
    quote: str | None = None
    binding: bool | None = None
    status: str | None = None


class ClassificationResult(_Loose):
    """The agents' answer (``POST /systems/{id}/classify``), §8.2."""

    risk_class: RiskClass
    route: Route
    annex_basis: str | None = None
    annex_basis_id: str | None = None
    role: Literal["provider", "deployer"] | None = None
    art6_3: Art63 | None = None
    transparency: Transparency | None = None
    citations: list[Citation] = Field(default_factory=list)
    kb_version: str | None = None
    needs_human: bool | None = None
    trace_id: str | None = None


class ClassificationIn(BaseModel):
    """Start a run; ``previousId`` = the run this one re-does (after a reject or stale)."""

    previousId: str | None = Field(None, max_length=200)


class DecisionIn(BaseModel):
    decision: Literal["approve", "reject"]
    reason: str | None = Field(None, max_length=2000)

    @model_validator(mode="after")
    def _reason_for_reject(self) -> "DecisionIn":
        if self.decision == "reject" and not (self.reason or "").strip():
            raise ValueError("A rejection needs a reason.")
        return self


class ClassificationEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    classificationId: str = Field(..., validation_alias="classification_id")
    systemId: str = Field(..., validation_alias="system_id")
    action: str
    actor: str
    reason: str | None = None
    data: dict[str, Any] = Field(default_factory=dict)
    at: UTCDateTime


class ClassificationOut(BaseModel):
    """One classifier run, its result (``null`` while running) and its event history."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    systemId: str = Field(..., validation_alias="system_id")
    status: ClassificationStatus
    kbVersion: str | None = Field(None, validation_alias="kb_version")
    dossierVersion: dict[str, Any] = Field(default_factory=dict, validation_alias="dossier_version")
    input: dict[str, Any] = Field(default_factory=dict)
    result: dict[str, Any] | None = None
    error: str | None = None
    traceId: str | None = Field(None, validation_alias="trace_id")
    previousId: str | None = Field(None, validation_alias="previous_id")
    createdBy: str = Field(..., validation_alias="created_by")
    createdAt: UTCDateTime = Field(..., validation_alias="created_at")
    updatedAt: UTCDateTime = Field(..., validation_alias="updated_at")
    events: list[ClassificationEventOut] = Field(default_factory=list)


class ObligationsPreviewOut(BaseModel):
    """The obligations reg-memory activates for the system's card (no audit needed).

    ``items`` are reg-memory's obligation rows as returned (``include_not_applicable``).
    ``classified: false`` = the card has no risk class yet (no items). ``kb_version``,
    ``query``, ``total`` and ``items`` keep reg-memory's ``ObligationList`` names.
    """

    systemId: str
    classificationId: str | None = None
    classificationStatus: str | None = None
    kb_version: str | None = None
    classified: bool = True
    prohibited: bool = False
    query: dict[str, Any] = Field(default_factory=dict)
    total: int = 0
    items: list[dict[str, Any]] = Field(default_factory=list)
