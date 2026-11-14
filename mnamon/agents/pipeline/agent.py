"""``AuditPipelineAgent``: the audit pipeline as a registered LangGraph agent.

Slug ``audit-pipeline``. It runs two ways, both AG-UI:

* ``POST /agents/audit-pipeline/stream`` / ``/resume`` (the contract's run
  protocol), with ``config.context.system_id`` + ``audit_id``;
* ``POST /audits/{id}/run`` / ``/resume`` (``router/audits.py``): the backend
  starts and resumes an audit; the frames are consumed in the background.

The thread id of an audit is ``audit-<audit_id>`` (one durable thread per
audit), so a restart resumes from the last checkpoint. A gate pauses on
``interrupt()``, which streams as ``CUSTOM HITL_INTERRUPT`` like any other
approval.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Mapping
from typing import Any

from langgraph.graph import StateGraph
from langgraph.types import Command

from core.logging import get_logger
from harness.abstractions.langgraph_agent import LangGraphAgent
from harness.agui.emitter import encode, is_agui_events
from harness.checkpointer import get_runtime_pool
from harness.memory.store import SystemMemoryStore
from harness.models.gemini import ModelNotConfiguredError, is_configured
from harness.tools.public_datasets.tools import run_fetch, run_search
from pipeline.clients import BackendInternal, RegMemory, SandboxRunner
from pipeline.graph import AuditPipeline, PipelineDeps
from pipeline.steps import StepRunner

logger = get_logger(__name__)

AGENT_SLUG = "audit-pipeline"


def audit_thread_id(audit_id: str) -> str:
    return f"audit-{audit_id}"


def _memory_store() -> SystemMemoryStore | None:
    try:
        return SystemMemoryStore(get_runtime_pool())
    except Exception:  # no pool (tests without Postgres): the steps run without memory
        return None


def default_deps(context: Mapping[str, Any], trace_id: str | None, thread_id: str) -> PipelineDeps:
    audit_id = str(context["audit_id"])
    run_id = context.get("run_id")
    return PipelineDeps(
        backend_factory=lambda aid: BackendInternal(aid, run_id=run_id, trace_id=trace_id),
        regmem=RegMemory(),
        sandbox=SandboxRunner(
            user=str(context.get("client_id") or AGENT_SLUG), conversation=audit_thread_id(audit_id)
        ),
        memory_store=_memory_store(),
        steps=StepRunner(),
        public_search=run_search,
        public_fetch=run_fetch,
        run_id=run_id,
        thread_id=thread_id,
        trace_id=trace_id,
    )


class AuditPipelineAgent(LangGraphAgent):
    """The engineer audit pipeline (``pipeline/graph.py``) behind the agent run surface."""

    name = AGENT_SLUG
    agent_id = AGENT_SLUG
    label = "Audit pipeline"
    version = "1.0.0"
    description = (
        "Runs an EU AI Act audit of one system end to end: context, model profile, public data, "
        "scenarios, synthetic data, sandbox tests, findings, critic and reports, with human gates."
    )
    icon = "ShieldCheck"
    # A gated pipeline started by the audit features, never a chat partner.
    kind = "workflow"
    stream_mode: Any = ["custom", "updates"]

    def __init__(
        self, *, config: Mapping[str, Any] | None = None, deps: PipelineDeps | None = None
    ):
        super().__init__(config=config)
        if not self.context.get("system_id") or not self.context.get("audit_id"):
            raise ValueError("The audit pipeline needs context.system_id and context.audit_id.")
        trace = self.config.get("trace") if isinstance(self.config.get("trace"), Mapping) else {}
        thread_id = str(self.run_config.get("configurable", {}).get("thread_id") or "")
        self.deps = deps or default_deps(self.context, trace.get("trace_id"), thread_id)

    # LangGraphAgent's hooks: the graph is built whole by AuditPipeline.
    def register_agents(self) -> Any:
        return None

    def register_nodes(self) -> Any:
        return None

    def register_graph_nodes(self, graph: StateGraph) -> StateGraph:
        return graph

    def register_graph_edges(self, graph: StateGraph) -> StateGraph:
        return graph

    def build(self) -> None:
        if self.graph is None:
            self.graph = AuditPipeline(self.deps).build(self.memory_saver)

    def initial_state(self) -> dict[str, Any]:
        return {
            "audit_id": self.context["audit_id"],
            "system_id": self.context["system_id"],
            "status": "running",
        }

    async def _input(self, command: Command | None) -> Any:
        """A resume command; else continue a cut run; else start fresh."""
        if command is not None:
            return command
        if self.memory_saver is not None:
            snapshot = await self.compiled.aget_state(self.run_config)
            if snapshot.values and snapshot.next and not snapshot.interrupts:
                return None  # a run cut by a restart or an error: continue from the checkpoint
        return self.initial_state()

    async def astream(
        self, payload: Mapping[str, Any], *, command: Command | None = None
    ) -> AsyncIterator[bytes]:
        """Stream the pipeline as AG-UI frames (custom node events + gate interrupts)."""
        try:
            if not is_configured():
                raise ModelNotConfiguredError()
            await self.ensure_built()
            stream_input = await self._input(command)
            logger.info(
                "audit_pipeline_started",
                "Audit pipeline run started",
                audit_id=self.context.get("audit_id"),
                resumed=command is not None,
            )
            async for chunk in self.compiled.astream(
                stream_input, config=self._traced_config(), stream_mode=self.stream_mode
            ):
                mode, data = (
                    chunk if isinstance(chunk, tuple) and len(chunk) == 2 else (None, chunk)
                )
                if mode == "custom":
                    if isinstance(data, (bytes, str)):
                        yield data.encode("utf-8") if isinstance(data, str) else data
                    elif is_agui_events(data):
                        for event in data if isinstance(data, list) else [data]:
                            yield encode(event)
                    continue
                for frame in self.agui_normalizer.handle_chunk(chunk):
                    yield frame
            logger.info(
                "audit_pipeline_paused_or_done",
                "Audit pipeline run ended",
                audit_id=self.context.get("audit_id"),
            )
        except (BrokenPipeError, ConnectionResetError, asyncio.CancelledError):
            return
        except Exception as exc:
            yield self._encode_run_error(exc)


__all__ = ["AGENT_SLUG", "AuditPipelineAgent", "audit_thread_id", "default_deps"]
