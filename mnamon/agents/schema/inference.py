"""Run DTOs: the ``/stream`` and ``/resume`` bodies (``docs/contracts/agents-contract.md``)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class Request(BaseModel):
    """``POST /agents/{slug}/stream``: the run's input messages and its config.

    ``messages`` are the contract's ``Message`` dicts (``id``, ``role``,
    ``content``, ``attachments``); ``config`` carries ``run_config``,
    ``context``, the optional ``fork_from`` and the optional ``trace``.
    """

    messages: list[dict[str, Any]]
    config: dict[str, Any]


class ResumeActionDecision(BaseModel):
    """One approve/reject decision for a single gated tool call in a batched
    HITL interrupt, index-aligned to the interrupt's ``action_requests``."""

    decision: Literal["approve", "reject"]
    reason: str | None = None


class ResumeItem(BaseModel):
    """One pending interrupt's decision inside a batched resume, keyed by its id."""

    interrupt_id: str = Field(min_length=1, max_length=128)
    decision: Literal["approve", "reject"]
    reason: str | None = None
    value: Any | None = None
    decisions: list[ResumeActionDecision] | None = None


class AgentResumeRequest(BaseModel):
    """``POST /agents/{slug}/resume``: answers for a run paused on HITL interrupt(s).

    The top-level fields carry the first decision. ``decisions`` is the
    per-action list of one batched interrupt; ``value`` carries structured
    answers (an ``ask_user`` reply's ``{"answers": [...]}``). ``interrupt_id``
    names the pending interrupt it answers, so a stale card can be 409'd
    instead of resolving the wrong one. ``resumes``, when present, is the whole
    request: several pending interrupts answered together, applied as
    ``Command(resume={interrupt_id: value, ...})``.
    """

    config: dict[str, Any]
    thread_id: str
    decision: Literal["approve", "reject"]
    reason: str | None = None
    value: Any | None = None
    interrupt_id: str | None = None
    decisions: list[ResumeActionDecision] | None = None
    resumes: list[ResumeItem] | None = Field(default=None, min_length=1, max_length=64)
