"""Deep-agent steps: one scoped deep agent per open-ended node, ONE validated result.

``StepRunner.run(step, brief, ...)`` builds a deepagents agent with

* the step's layered prompt (``pipeline/prompting.py``) and the system's
  ``MEMORY.md`` (read fresh, so a lesson recorded one step earlier is in it);
* only the tools the step needs (``STEP_TOOLS``): system files through the
  backend's internal API, reg-memory lookups pinned to the run's ``kb_version``,
  the sandbox, the system memory (``remember`` + ``read_memory``);
* the step's result model as a structured-output tool (``ToolStrategy``): a
  malformed result is a validation error the model reads and fixes.

The model is Gemini (``default`` or ``reasoning`` role per step). With
``AGENTS_FAKE_LLM`` it is a scripted stub that calls the result tool with the
step's deterministic fake output (``pipeline/fakes.py``), so a dry run goes
through the very same agent, middleware and traces.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from deepagents import create_deep_agent
from langchain.agents.structured_output import ToolStrategy
from langchain_core.messages import HumanMessage
from langchain_core.tools import BaseTool, StructuredTool
from pydantic import BaseModel, Field

from core.logging import get_logger
from harness.memory import MemoryBinding, build_index, entry_path
from harness.memory.store import MemoryStoreProtocol
from harness.models.fake import ScriptedChatModel, tool_call_message
from harness.models.gemini import ModelRole, build_chat_model, is_fake, model_spec
from harness.tools.remember.tool import build_remember_tool
from pipeline.clients import BackendInternal, PipelineHTTPError, RegMemory, SandboxRunner
from pipeline.prompting import compose_step_prompt, render_brief
from pipeline.schemas import STEP_RESULTS

logger = get_logger(__name__)

#: Which model role each step runs on (parameters, not prose: depth is the model).
STEP_ROLES: dict[str, ModelRole] = {
    "plan_scenarios": "reasoning",
    "scenario_review": "default",
    "draft_spec": "default",
    "analyse": "default",
    "critic": "reasoning",
    "report": "default",
    "change_judge": "reasoning",
}

#: The tool families each step gets (nothing else is bound).
STEP_TOOLS: dict[str, tuple[str, ...]] = {
    "plan_scenarios": ("files", "regulation", "memory"),
    "scenario_review": (),
    "draft_spec": ("files", "memory"),
    "analyse": ("files", "regulation", "sandbox", "memory"),
    "critic": ("files", "regulation", "sandbox", "memory"),
    "report": ("regulation", "memory"),
    "change_judge": ("regulation",),
}

#: Recursion cap of one step's agent loop (model + tool turns).
STEP_RECURSION_LIMIT = 60


@dataclass
class StepScope:
    """What one step's tools are bound to (all from the run, never from the model)."""

    audit_id: str
    system_id: str
    kb_version: str | None
    step: str
    backend: BackendInternal | None = None
    regmem: RegMemory | None = None
    sandbox: SandboxRunner | None = None
    sandbox_files: Mapping[str, str | bytes] | None = None
    memory_store: MemoryStoreProtocol | None = None
    run_id: str | None = None
    thread_id: str | None = None


def _dump(value: Any, limit: int = 12_000) -> str:
    text = value if isinstance(value, str) else json.dumps(value, default=str, ensure_ascii=False)
    return text if len(text) <= limit else text[:limit] + f"\n... [{len(text) - limit} more]"


class _PathArgs(BaseModel):
    path: str = Field(description="Path in the system folder, e.g. plugins/cv-ranker/plugin.yaml.")


class _PrefixArgs(BaseModel):
    prefix: str | None = Field(None, description="Only paths under this prefix, e.g. plugins/.")


class _ProvisionArgs(BaseModel):
    provision_id: str = Field(description="e.g. AIA.10.2.f or AIA.ANNEX_III.4.a")


class _SearchArgs(BaseModel):
    query: str = Field(description="Words to find in the regulation text.")


class _ExecArgs(BaseModel):
    command: str = Field(
        description="Shell command run in output/ of a fresh sandbox; the audit's files are in "
        "../input/ (plugin.yaml, data/, generation-spec.yaml, model-profile.json, "
        "test-results.json). synthkit and python (pandas, numpy, scipy) are installed."
    )


class _MemoryArgs(BaseModel):
    path: str = Field(description="An entry path from the memory index, /memory/audits/<id>/<n>.md")


def _file_tools(scope: StepScope) -> list[BaseTool]:
    backend = scope.backend
    if backend is None:
        return []

    async def list_system_files(prefix: str | None = None) -> str:
        try:
            tree = await backend.tree(prefix)
        except PipelineHTTPError as exc:
            return f"Could not list files: {exc.public}."
        return "\n".join(f"{f.get('path')} (v{f.get('version')})" for f in tree) or "(no files)"

    async def read_system_file(path: str) -> str:
        try:
            text = await backend.read(path.lstrip("/").removeprefix(f"systems/{scope.system_id}/"))
        except PipelineHTTPError as exc:
            return f"Could not read {path}: {exc.public}."
        return _dump(text) if text is not None else f"{path} is a binary file."

    return [
        StructuredTool.from_function(
            coroutine=list_system_files,
            name="list_system_files",
            description="List the audited system's folder (system card, plugins, docs, evidence).",
            args_schema=_PrefixArgs,
        ),
        StructuredTool.from_function(
            coroutine=read_system_file,
            name="read_system_file",
            description="Read one file of the audited system's folder (each read is logged).",
            args_schema=_PathArgs,
        ),
    ]


def _regulation_tools(scope: StepScope) -> list[BaseTool]:
    regmem = scope.regmem
    if regmem is None:
        return []
    kb = scope.kb_version

    async def lookup_provision(provision_id: str) -> str:
        try:
            body = await regmem.provision(provision_id, kb)
        except PipelineHTTPError as exc:
            return f"Could not read {provision_id}: {exc.public}."
        keep = {k: body.get(k) for k in ("id", "title", "text", "valid_from", "kb_version")}
        keep["children"] = [c.get("id") for c in body.get("children") or []][:40]
        keep["interpretations"] = [
            {"id": i.get("id"), "summary": i.get("summary")}
            for i in (body.get("interpretations") or [])[:10]
        ]
        return _dump(keep)

    async def search_regulation(query: str) -> str:
        try:
            items = await regmem.search_provisions(
                q=query, kb_version=kb, limit=10, with_text=False
            )
        except PipelineHTTPError as exc:
            return f"Search failed: {exc.public}."
        return _dump([{"id": i.get("id"), "title": i.get("title")} for i in items]) or "[]"

    return [
        StructuredTool.from_function(
            coroutine=lookup_provision,
            name="lookup_provision",
            description=f"Verbatim text of one regulation provision at kb_version {kb}, with its "
            "children and the guidance that relates to it.",
            args_schema=_ProvisionArgs,
        ),
        StructuredTool.from_function(
            coroutine=search_regulation,
            name="search_regulation",
            description="Find provisions by words (ids and titles only; then lookup_provision).",
            args_schema=_SearchArgs,
        ),
    ]


def _sandbox_tools(scope: StepScope) -> list[BaseTool]:
    sandbox = scope.sandbox
    if sandbox is None or not sandbox.available:
        return []
    files = dict(scope.sandbox_files or {})

    async def sandbox_execute(command: str) -> str:
        try:
            result = await sandbox.run(command, files, timeout=300)
        except PipelineHTTPError as exc:
            return f"The sandbox could not run the command: {exc.public}."
        text_files = {
            name: result.text(name)[:4000]
            for name in result.files
            if name.endswith((".json", ".md", ".csv", ".txt", ".yaml"))
        }
        return _dump({**result.summary(4000), "text_files": text_files})

    return [
        StructuredTool.from_function(
            coroutine=sandbox_execute,
            name="sandbox_execute",
            description="Recompute or check a number in the isolated sandbox (no network). Use "
            "it to verify evidence, not to rerun the whole audit.",
            args_schema=_ExecArgs,
        )
    ]


def _memory_tools(scope: StepScope, binding: MemoryBinding) -> list[BaseTool]:
    store = scope.memory_store
    if store is None:
        return []

    async def read_memory(path: str) -> str:
        try:
            records = await store.list_system(scope.system_id)
        except Exception:
            return "Memory is unavailable right now."
        for record in records:
            if entry_path(record.audit_id, record.name) == path.strip():
                return record.content_md
        return f"No memory entry at {path}."

    return [
        build_remember_tool(binding=binding, store=store),
        StructuredTool.from_function(
            coroutine=read_memory,
            name="read_memory",
            description="Read one entry of this system's memory by its path in the index.",
            args_schema=_MemoryArgs,
        ),
    ]


def build_step_tools(scope: StepScope, binding: MemoryBinding) -> list[BaseTool]:
    families = STEP_TOOLS.get(scope.step, ())
    tools: list[BaseTool] = []
    if "files" in families:
        tools += _file_tools(scope)
    if "regulation" in families:
        tools += _regulation_tools(scope)
    if "sandbox" in families:
        tools += _sandbox_tools(scope)
    if "memory" in families:
        tools += _memory_tools(scope, binding)
    return tools


async def memory_index(store: MemoryStoreProtocol | None, system_id: str) -> str | None:
    """``MEMORY.md`` of the system, or None (no store, empty, or an outage: logged)."""
    if store is None:
        return None
    try:
        records = await store.list_system(system_id)
    except Exception:
        logger.warning("pipeline_memory_unavailable", "Memory unavailable", system_id=system_id)
        return None
    return build_index(system_id, records) if records else None


FakeOutput = Callable[[], BaseModel]


def fake_lesson(step: str, feedback: dict[str, Any]) -> dict[str, str]:
    """The ``remember`` call the scripted model makes after a human rejection."""
    category = str(feedback.get("category") or "other")
    reason = " ".join(str(feedback.get("reason") or "no reason given").split())
    return {
        "name": f"{step}-{category}".replace("_", "-"),
        "summary": f"{step}: {reason}"[:200],
        "content": f"A reviewer rejected {step} ({category}): {reason}. "
        "Apply this before proposing the step's result again.",
    }


class StepRunner:
    """Runs one deep-agent step and returns its validated result model."""

    def __init__(self, *, model_factory: Callable[[ModelRole], Any] | None = None) -> None:
        self.model_factory = model_factory or (lambda role: build_chat_model(role))

    def _model(
        self,
        step: str,
        schema: type[BaseModel],
        fake: FakeOutput | None,
        feedback: dict[str, Any] | None,
    ) -> Any:
        if is_fake():
            if fake is None:
                raise RuntimeError(f"no fake output for step {step!r}")
            script = []
            if feedback and feedback.get("source") == "human" and "memory" in STEP_TOOLS[step]:
                # What the real agent is told to do first: record the reviewer's lesson.
                script.append(tool_call_message("remember", fake_lesson(step, feedback)))
            script.append(tool_call_message(schema.__name__, fake().model_dump(mode="json")))
            spec = model_spec(STEP_ROLES.get(step, "default"))
            return ScriptedChatModel(model=spec, script=script)
        return self.model_factory(STEP_ROLES.get(step, "default"))

    async def run(
        self,
        step: str,
        brief: dict[str, Any],
        scope: StepScope,
        *,
        feedback: dict[str, Any] | None = None,
        fake: FakeOutput | None = None,
        config: Mapping[str, Any] | None = None,
    ) -> BaseModel:
        schema = STEP_RESULTS[step]
        binding = MemoryBinding(
            system_id=scope.system_id,
            audit_id=scope.audit_id,
            step=step,
            agent_name=f"pipeline:{step}",
            run_id=scope.run_id,
            thread_id=scope.thread_id,
            trust_level="agent",
        )
        index = await memory_index(scope.memory_store, scope.system_id)
        prompt = compose_step_prompt(step, memory_index=index, today=datetime.now(UTC).date())
        agent = create_deep_agent(
            model=self._model(step, schema, fake, feedback),
            tools=build_step_tools(scope, binding),
            system_prompt=prompt,
            response_format=ToolStrategy(schema),
            name=f"step-{step}",
        )
        run_config: dict[str, Any] = {
            "recursion_limit": STEP_RECURSION_LIMIT,
            "run_name": f"step:{step}",
            "tags": ["pipeline-step", step],
            "metadata": {"step": step, "model": model_spec(STEP_ROLES.get(step, "default"))},
        }
        if config and config.get("callbacks") is not None:
            run_config["callbacks"] = config["callbacks"]
        result = await agent.ainvoke(
            {"messages": [HumanMessage(content=render_brief(step, brief, feedback))]},
            config=run_config,
        )
        structured = result.get("structured_response") if isinstance(result, dict) else None
        if structured is None:
            raise StepResultMissing(step)
        return structured if isinstance(structured, schema) else schema.model_validate(structured)


class StepResultMissing(RuntimeError):
    """The step's agent ended without calling its result tool."""

    public_message = "A pipeline step ended without a result; it can be retried."

    def __init__(self, step: str) -> None:
        super().__init__(f"step {step} returned no structured result")
        self.step = step


__all__ = [
    "STEP_ROLES",
    "STEP_TOOLS",
    "StepResultMissing",
    "StepRunner",
    "StepScope",
    "build_step_tools",
    "memory_index",
]
