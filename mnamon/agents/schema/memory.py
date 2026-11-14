"""DTOs of the internal, read-only memory view (``GET /internal/systems/{id}/memory``)."""

from datetime import datetime

from pydantic import BaseModel


class MemoryEntryOut(BaseModel):
    """One entry, with its provenance (which the agent never sees in the body)."""

    path: str
    auditId: str
    name: str
    summary: str
    contentMd: str
    step: str | None = None
    agentName: str | None = None
    sourceRunId: str | None = None
    sourceThreadId: str | None = None
    createdBy: str
    trustLevel: str
    createdAt: datetime
    updatedAt: datetime


class SystemMemoryOut(BaseModel):
    """A system's whole memory: the derived index and every entry, newest first."""

    systemId: str
    index: str
    entries: list[MemoryEntryOut]
