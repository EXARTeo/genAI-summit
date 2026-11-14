"""``LangGraphAgent``: the base for an agent written as an explicit ``StateGraph``.

For a graph-shaped agent (fixed nodes and edges) rather than a deep agent. A
subclass registers its chains, nodes and edges; the base compiles the graph
against the durable checkpointer and streams it through ``BaseAgent.astream``.
Nodes stream AG-UI events by writing them to the ``custom`` stream mode
(``harness.agui.send``). A subclass is registered in
``utils.agents.PYTHON_AGENTS``.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping
from typing import Any

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import StateGraph
from pydantic import BaseModel

from core.logging import get_logger
from harness.abstractions.base_agent import BaseAgent
from harness.agui import AGUIEmitter, AGUIStreamNormalizer

logger = get_logger(__name__)


class LangGraphAgent(BaseAgent, ABC):
    """LangGraph-specific base that compiles a ``StateGraph`` and streams it.

    Subclasses override the registration hooks to initialise chains (agents),
    node callables, and edges before the graph is compiled.
    """

    stream_mode: Any = "custom"
    _log_domain: str = "langgraph"

    def __init__(self, *, config: Mapping[str, Any] | None = None) -> None:
        super().__init__(config=config)
        self.state: type[BaseModel] | None = None
        self.agents: Any = None
        self.nodes: Any = None
        self.graph: Any = None
        self.memory_saver: Any = None  # bound lazily at build time
        # AG-UI message ids and sub-agent bindings are keyed on the run (the
        # assistant message id), not the branch-scoped checkpoint thread.
        self.agui_emitter: AGUIEmitter = AGUIEmitter()
        self.agui_normalizer: AGUIStreamNormalizer = AGUIStreamNormalizer(
            thread_id=self.context.get("run_id")
            or self.run_config.get("configurable", {}).get("thread_id", "")
        )

    # ---------------------------------------------------------------------
    # Graph lifecycle
    # ---------------------------------------------------------------------
    @abstractmethod
    def register_agents(self) -> Any:
        """Instantiate LLM chains/helpers; the result is stored on ``self.agents``."""

    @abstractmethod
    def register_nodes(self) -> Any:
        """Create node callables (usually closing over ``self.agents``)."""

    @abstractmethod
    def register_graph_nodes(self, graph: StateGraph) -> StateGraph:
        """Attach node handlers to ``graph`` and return it."""

    @abstractmethod
    def register_graph_edges(self, graph: StateGraph) -> StateGraph:
        """Connect graph nodes with edges or conditional routes and return the graph."""

    def build(self) -> None:
        """Build the ``StateGraph`` once, compiled against ``self.memory_saver``.

        When no ``state`` and no nodes are defined, ``self.agents`` is the
        runnable itself.
        """
        if self.graph is not None:
            return
        logger.info("langgraph_build_started", "LangGraph build started", agent_slug=self.name)
        if self.memory_saver is None:
            self.memory_saver = InMemorySaver()
        if self.agents is None or self.nodes is None:
            self.agents = self.register_agents()
            self.nodes = self.register_nodes()
        if self.state is None and self.nodes is None:
            self.graph = self.agents
        else:
            graph = StateGraph(self.state)
            graph = self.register_graph_nodes(graph)
            graph = self.register_graph_edges(graph)
            self.graph = graph.compile(checkpointer=self.memory_saver)
        logger.info("langgraph_build_completed", "LangGraph build completed", agent_slug=self.name)

    async def ensure_built(self) -> None:
        """Bind the durable saver (when the run has a thread), then build. Idempotent."""
        if self.memory_saver is None:
            self.memory_saver = self._durable_checkpointer()
        self.build()

    @property
    def compiled(self) -> Any:
        """The compiled runnable produced by ``build()``. ``None`` until built."""
        return self.graph
