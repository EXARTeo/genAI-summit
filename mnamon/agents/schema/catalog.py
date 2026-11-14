"""Catalog DTOs: the agent list a UI picks from, and the registry entry a slug resolves to."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel

#: ``chat``: the chat's agent picker lists it. ``workflow``: a pipeline the
#: product's features start (e.g. ``audit-pipeline``); a chat UI hides it.
AgentKind = Literal["chat", "workflow"]


class AgentManifest(BaseModel):
    """One agent as ``GET /agents`` lists it."""

    id: str
    slug: str
    name: str
    version: str | None = None
    type: str
    description: str
    icon: str
    #: Whether a chat may pick it (``chat``) or only a feature runs it (``workflow``).
    kind: AgentKind = "chat"
    #: The agent a new conversation starts with (``DEFAULT_AGENT_SLUG``).
    default: bool = False


@dataclass(frozen=True)
class AgentDefinition:
    """A registered agent: its manifest and the factory that builds it for one run."""

    slug: str
    manifest: dict[str, Any]
    factory: Callable[[dict[str, Any] | None], Any]
    #: The parsed ``AgentSpec`` of a declarative agent; None for a Python one.
    spec: Any = None

    def build(self, config: dict[str, Any] | None = None) -> Any:
        """Instantiate the agent for a run."""
        return self.factory(config)
