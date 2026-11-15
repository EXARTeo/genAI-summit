"""The classifier's result contract (plan 02 §8.2).

:class:`RiskProposal` is what the Gemini step returns through its structured-output
tool (flat, explicit models, so Gemini's function-calling schema accepts them).
:class:`ClassificationResult` adds what code computes (kb, pre-checks, dates,
Iris, agreement, ``needs_human``). The backend and the frontend copy this shape.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

RiskClass = Literal["prohibited", "high_risk", "limited_risk", "minimal_risk", "out_of_scope"]
RiskRoute = Literal[
    "art5",
    "art6_1_annex_i",
    "art6_2_annex_iii",
    "art6_3_exempt",
    "art50_only",
    "none",
    "not_ai_system",
]
Profiling = Literal["yes", "no", "unknown"]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="ignore")


class RiskCitation(_Strict):
    id: str = Field(description="Provision (AIA.6.3, AIA.ANNEX_III.4.a) or guidance (INT....) id.")
    kb_version: str = ""
    quote: str = Field("", description="The words relied on, verbatim, at most 200 characters.")
    binding: bool = Field(True, description="false for guidance (INT.*).")
    status: Literal["final", "draft"] = "final"

    @field_validator("quote", mode="before")
    @classmethod
    def _short_quote(cls, value: object) -> object:
        return value[:200] if isinstance(value, str) else value


class ProvisionCheck(_Strict):
    provision_id: str
    applies: bool
    why: str


class Art63Assessment(_Strict):
    considered: bool
    condition: Literal["a", "b", "c", "d"] | None = None
    profiling: Profiling = "unknown"
    holds: bool | None = None
    why: str = ""


class Transparency(_Strict):
    features: list[str] = Field(default_factory=list)
    provisions: list[str] = Field(default_factory=list, description="AIA.50.1, AIA.50.2, ...")


class GpaiFlag(_Strict):
    is_gpai_model: bool = False
    built_on_gpai: bool = False
    note: str = ""


class CounterArgument(_Strict):
    argument: str
    would_change_to: str = Field(description="The class or route it would lead to.")


class Uncertainty(_Strict):
    question: str
    why_it_matters: str
    ask: Literal["PM", "legal", "engineer"]


class RiskProposal(_Strict):
    """What the ``classify_risk`` step returns (the agent's part of the result)."""

    risk_class: RiskClass
    route: RiskRoute
    annex_basis: str | None = Field(None, description='"Annex III 4(a)" or "Annex I: <act>".')
    annex_basis_id: str | None = Field(None, description="AIA.ANNEX_III.4.a or null.")
    role: Literal["provider", "deployer"]
    role_reasoning: str = Field(description="At most 60 words, citing Art. 3(3)/3(4)/25.")
    art5_screening: list[ProvisionCheck] = Field(default_factory=list)
    annex_iii_considered: list[ProvisionCheck] = Field(default_factory=list)
    art6_3: Art63Assessment
    transparency: Transparency = Field(default_factory=Transparency)
    gpai: GpaiFlag = Field(default_factory=GpaiFlag)
    reasoning: str = Field(description="At most 200 words.")
    counter_arguments: list[CounterArgument] = Field(default_factory=list)
    would_change_if: list[str] = Field(default_factory=list)
    uncertainties: list[Uncertainty] = Field(default_factory=list)
    next_steps: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0, le=1)
    citations: list[RiskCitation] = Field(default_factory=list)


class KeyDate(_Strict):
    what: str
    date: str | None
    provision_id: str
    amended_by: list[str] = Field(default_factory=list)


class IrisCheck(_Strict):
    choice: str
    probabilities: dict[str, float] = Field(default_factory=dict)
    confidence: float | None = None
    profiling: float | None = Field(None, description="P(the system profiles people).")
    agent_choice: str = ""


ClaimGroup = Literal[
    "annex_iii", "art5", "art6_3", "art50", "role", "annex_i", "assumption", "counter"
]


class IrisClaim(_Strict):
    """One article-level claim or premise of the agent, checked by Iris as a yes/no."""

    key: str = Field(description="Stable: annex_iii:AIA.ANNEX_III.4.a, art6_3:profiling, role...")
    group: ClaimGroup
    provision_id: str | None = None
    statement: str
    agent: bool = Field(description="What the agent holds (a counter-argument: false).")
    iris: float | None = Field(
        None, description="Iris's P(the statement is true); null = unchecked."
    )
    agrees: bool | None = None
    strong_disagreement: bool = False


class IrisSummary(_Strict):
    checked: int = 0
    agree: int = 0
    disagree: int = 0


class ClassificationResult(RiskProposal):
    """``POST /systems/{id}/classify``: the proposal + what code adds."""

    classification_id: str = ""
    system_id: str = ""
    kb_version: str | None = None
    prechecks: dict[str, Any] = Field(default_factory=dict)
    key_dates: list[KeyDate] = Field(default_factory=list)
    iris: IrisCheck | None = None
    iris_claims: list[IrisClaim] = Field(default_factory=list)
    iris_summary: IrisSummary = Field(default_factory=IrisSummary)
    agreement: bool | None = None
    needs_human: bool = False
    needs_human_reasons: list[str] = Field(default_factory=list)
    verifier_problems: list[str] = Field(default_factory=list)
    decided_by: Literal["gemini+iris", "gemini"] = "gemini"
    trace_id: str | None = None


__all__ = [
    "Art63Assessment",
    "ClassificationResult",
    "CounterArgument",
    "GpaiFlag",
    "IrisCheck",
    "IrisClaim",
    "IrisSummary",
    "KeyDate",
    "ProvisionCheck",
    "RiskCitation",
    "RiskProposal",
    "Transparency",
    "Uncertainty",
]
