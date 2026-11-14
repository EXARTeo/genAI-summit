"""Search DTOs: one flat result row of the sidebar search panel."""

from typing import Literal

from pydantic import BaseModel

from schema.base import UTCDateTime


class WorkspaceSearchResult(BaseModel):
    """A match in the caller's conversations: a title, a message or a file name."""

    kind: Literal["conversation", "message", "file"]
    id: str
    conversationId: str
    agentSlug: str | None = None
    title: str
    subtitle: str | None = None
    snippet: str | None = None
    updatedAt: UTCDateTime | None = None
