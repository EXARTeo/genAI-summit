"""The engineer audit pipeline as a LangGraph ``StateGraph``.

Order (fixed by code, CLAUDE.md § The product)::

    load_context → profile_model → find_public_data → [gate public_data] →
    plan_scenarios → analyse_scenarios → [gate scenarios] → draft_spec →
    generate_data → analyse_datasets → [gate datasets] → run_tests →
    analyse → critic → report → finalize

* **Code nodes** (deterministic): the backend's internal API, reg-memory, and
  the sandbox runner with synthkit (``profile``, ``scenarios-check``,
  ``generate``, ``analyze``, ``run-tests``).
* **Deep-agent nodes** (``plan_scenarios``, ``draft_spec``, ``analyse``,
  ``critic``, ``report``): a scoped deep agent that returns ONE validated result
  model (``pipeline/steps.py``).
* **Verifiers** (``pipeline/verify.py``) send a failed output back to its step
  with the report, at most ``PIPELINE_MAX_AUTO_REDOS`` times.
* **Gates** pause on ``interrupt()``; the decision comes back through
  ``/resume`` (the backend's approvals). A rejection with a reason goes back to
  the step with the reason in its brief; the step's agent records the lesson
  with ``remember`` first. More than ``PIPELINE_MAX_REDOS`` rejections stop the
  audit as ``rejected``.

Every node writes its artifact through ``POST /internal/audits/{id}/artifacts``
and moves the audit's stage; each node is a Langfuse span (the run's callback
handler), and the graph is checkpointed after every node, so a restart resumes
where it stopped.
"""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import yaml
from ag_ui.core import EventType, StepFinishedEvent, StepStartedEvent
from langgraph.config import get_stream_writer
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from core.logging import get_logger
from core.settings import settings
from harness.agui.emitter import AGUIEmitter, encode
from harness.memory.store import MemoryStoreProtocol
from pipeline import fakes
from pipeline.clients import BackendInternal, ExecResult, RegMemory, SandboxRunner
from pipeline.state import AuditState
from pipeline.steps import StepRunner, StepScope
from pipeline.testplan import (
    analyze_command,
    build_test_plan,
    dumps_yaml,
    generate_command,
    loads_json,
    normalise_results,
    profile_command,
    run_tests_command,
    scenarios_check_command,
)
from pipeline.verify import (
    dataset_problems,
    evidence_problems,
    parse_spec,
    scenario_problems,
)

logger = get_logger(__name__)

#: The gates, the stage each waits in, the artifacts it reviews, the step a rejection redoes.
GATES: dict[str, dict[str, Any]] = {
    "public_data": {"stage": "find_public_data", "reviews": ["public_dataset_candidates"]},
    "scenarios": {
        "stage": "approve_scenarios",
        "reviews": ["scenarios", "scenario_analysis"],
        "redo": "plan_scenarios",
    },
    "datasets": {
        "stage": "approve_datasets",
        "reviews": ["generation_spec", "dataset_analysis"],
        "redo": "draft_spec",
    },
}
DECISIONS = {
    "approve": "approved",
    "approved": "approved",
    "reject": "rejected",
    "rejected": "rejected",
    "changes_requested": "changes_requested",
    "request_changes": "changes_requested",
}
_ANNEX_RE = re.compile(r"Annex\s+([IVX]+)\s*(\d+)?\s*(?:\(([a-z])\))?", re.IGNORECASE)

#: How a synthkit GenerationSpec looks (the draft_spec brief; from synthkit/spec.py).
SPEC_FORMAT = """\
version: 1
name: <target>.<purpose>
dictionary: data/data-dictionary.yaml
plugin: plugin.yaml
model_profile: model-profile.json        # boundary-aware sampling
n: 400                                   # base rows
generation: {mode: zero_shot}            # or reference_sample + reference: <public data.csv>
fields: {<field>: {conditional: {...}, provenance: llm_assumption}}   # overrides only
rules: [{id: S1, severity: hard, expr: "...", provenance: memory}]
strata: {by: [<protected field>], balance: true}
boundary: {share: 0.3, band: 0.15, pool: 5}
coverage: {cells: [<field>, <field>], min_per_cell: 20}
transforms:
  - {kind: twins, attribute: <field>, modes: [attribute_only, causal, proxy_only],
     proxies: [<field>], max_base: 150}
  - {kind: edge_cases, fields: [<field>, ...]}
  - {kind: perturbation, fields: [<monotone field>], delta: 1}
"""


def annex_basis(card: dict[str, Any]) -> str | None:
    """``"Annex III 4(a)"`` -> ``AIA.ANNEX_III.4.a`` (the reg-memory provision id)."""
    match = _ANNEX_RE.search(str(card.get("annex_basis") or ""))
    if not match:
        return None
    parts = ["AIA", f"ANNEX_{match.group(1).upper()}"]
    if match.group(2):
        parts.append(match.group(2))
    if match.group(3):
        parts.append(match.group(3).lower())
    return ".".join(parts)


def risk_class(card: dict[str, Any]) -> str | None:
    value = str(card.get("risk_class") or "").lower()
    return "high" if value.startswith("high") else (value or None)


def normalise_decision(value: Any) -> dict[str, Any]:
    """A gate's resume value (backend approval, AG-UI decision or plain string) -> one shape."""
    if isinstance(value, str):
        value = {"decision": value}
    if not isinstance(value, dict):
        value = {}
    edits = value.get("edits") if isinstance(value.get("edits"), dict) else {}
    raw = str(value.get("decision") or "").strip().lower()
    return {
        "decision": DECISIONS.get(raw, "rejected" if raw else "approved"),
        "reason": value.get("comment") or value.get("reason") or "",
        "category": value.get("reasonCategory") or value.get("reason_category") or "other",
        "selected": value.get("selected") or edits.get("selected"),
        "edits": edits,
        "decided_by": value.get("decidedBy") or value.get("decided_by"),
        "at": datetime.now(UTC).isoformat(),
    }


def profile_digest(profile: dict[str, Any] | None, top: int = 12) -> dict[str, Any]:
    """The part of model-profile.json a model needs (the full file is in the artifact)."""
    if not profile:
        return {}
    sensitivity = profile.get("sensitivity") or {}
    ranked = sorted(
        ((name, s) for name, s in sensitivity.items() if isinstance(s, dict)),
        key=lambda item: (
            -float(
                (item[1].get("permutation") or {}).get("mean_abs_delta")
                or item[1].get("mean_range")
                or 0
            )
        ),
    )
    return {
        "notes": profile.get("notes") or [],
        "output": profile.get("output"),
        "sensitivity": {
            name: {
                "moves_output": s.get("moves_output"),
                "mean_range": s.get("mean_range"),
                "flip_rate": s.get("flip_rate"),
            }
            for name, s in ranked[:top]
        },
        "protected": profile.get("protected"),
        "proxies": profile.get("proxies"),
        "monotonicity": profile.get("monotonicity"),
    }


def analysis_digest(analysis: dict[str, Any] | None) -> dict[str, Any]:
    if not analysis:
        return {}
    gates = analysis.get("gates") or {}
    return {
        "overall": analysis.get("overall"),
        "gates": {
            name: {"status": g.get("status"), "problems": (g.get("problems") or [])[:5]}
            for name, g in gates.items()
            if isinstance(g, dict)
        },
        "twin_validity": analysis.get("twin_validity"),
        "informativeness": analysis.get("informativeness"),
    }


@dataclass
class PipelineDeps:
    """What the nodes call; the agent wires the real ones, the tests their fakes."""

    backend_factory: Callable[[str], BackendInternal]
    regmem: RegMemory
    sandbox: SandboxRunner | None
    memory_store: MemoryStoreProtocol | None
    steps: StepRunner = field(default_factory=StepRunner)
    public_search: Callable[..., dict[str, Any]] | None = None
    public_fetch: Callable[..., dict[str, Any]] | None = None
    run_id: str | None = None
    thread_id: str | None = None
    trace_id: str | None = None
    today: Callable[[], str] = field(
        default_factory=lambda: lambda: datetime.now(UTC).date().isoformat()
    )


class StepFailed(RuntimeError):
    """A deterministic step cannot continue; ``public_message`` reaches the audit."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.public_message = message


class AuditPipeline:
    """The nodes, closing over :class:`PipelineDeps`; :meth:`build` wires the graph."""

    def __init__(self, deps: PipelineDeps) -> None:
        self.deps = deps
        self.emitter = AGUIEmitter()

    # ------------------------------------------------------------- plumbing
    def _backend(self, state: AuditState) -> BackendInternal:
        return self.deps.backend_factory(state["audit_id"])

    def _emit(self, event: dict[str, Any]) -> None:
        try:
            writer = get_stream_writer()
        except RuntimeError:  # outside a streamed run (unit tests with ainvoke)
            return
        writer(encode(event))

    async def _start(self, state: AuditState, stage: str, *, status: str = "running") -> dict:
        """Move the audit's stage (best effort) and announce the step."""
        traces = dict(state.get("stage_traces") or {})
        if self.deps.trace_id:
            traces[stage] = self.deps.trace_id
        try:
            await self._backend(state).patch(
                stage=stage, status=status, data={"stageTraces": traces, "pipeline": "agents"}
            )
        except Exception:
            logger.warning("pipeline_stage_patch_failed", "Stage patch failed", stage=stage)
        self._emit(
            self.emitter.event(StepStartedEvent(type=EventType.STEP_STARTED, step_name=stage))
        )
        return {"stage_traces": {stage: self.deps.trace_id}} if self.deps.trace_id else {}

    def _finish(self, stage: str) -> None:
        self._emit(
            self.emitter.event(StepFinishedEvent(type=EventType.STEP_FINISHED, step_name=stage))
        )

    async def _artifact(
        self,
        state: AuditState,
        kind: str,
        data: dict[str, Any],
        *,
        name: str = "main",
        file_refs: list[Any] | None = None,
    ) -> str | None:
        stamped = {
            **data,
            "kb_version": state.get("kb_version"),
            "producedBy": "audit-pipeline",
            "traceId": self.deps.trace_id,
        }
        art = await self._backend(state).write_artifact(
            kind, stamped, name=name, file_refs=file_refs
        )
        self._emit(
            self.emitter.custom(
                "AUDIT_ARTIFACT",
                {"kind": kind, "name": name, "id": art.get("id"), "version": art.get("version")},
            )
        )
        return art.get("id")

    def _scope(
        self, state: AuditState, step: str, files: dict[str, Any] | None = None
    ) -> StepScope:
        return StepScope(
            audit_id=state["audit_id"],
            system_id=state["system_id"],
            kb_version=state.get("kb_version"),
            step=step,
            backend=self._backend(state),
            regmem=self.deps.regmem,
            sandbox=self.deps.sandbox,
            sandbox_files=files,
            memory_store=self.deps.memory_store,
            run_id=self.deps.run_id,
            thread_id=self.deps.thread_id,
        )

    def _sandbox(self) -> SandboxRunner:
        sandbox = self.deps.sandbox
        if sandbox is None or not sandbox.available:
            raise StepFailed(
                "The sandbox runner is not configured (SANDBOX_RUNNER_URL); "
                "model profiling and tests cannot run."
            )
        return sandbox

    async def _exec(
        self, state: AuditState, stage: str, command: str, files: dict[str, Any]
    ) -> ExecResult:
        result = await self._sandbox().run(command, files)
        logger.info(
            "pipeline_sandbox_call",
            "Sandbox call finished",
            stage=stage,
            exit_code=result.exit_code,
            killed_reason=result.killed_reason,
            duration_ms=result.duration_ms,
        )
        return result

    async def _public_files(self, state: AuditState) -> dict[str, str]:
        public = state.get("public_data") or {}
        folder = public.get("folder")
        if not folder:
            return {}
        backend = self._backend(state)
        out = {}
        for name in ("data.csv", "mapping.yaml"):
            text = await backend.read(f"{folder}{name}")
            if text is not None:
                out[f"{folder}{name}"] = text
        return out

    def _base_files(self, state: AuditState) -> dict[str, str]:
        files = dict(state.get("files") or {})
        if state.get("profile"):
            files["model-profile.json"] = json.dumps(state["profile"])
        spec = state.get("spec") or {}
        if spec.get("yaml"):
            files["generation-spec.yaml"] = spec["yaml"]
        return files

    # ---------------------------------------------------------------- nodes
    async def load_context(self, state: AuditState) -> dict[str, Any]:
        out = await self._start(state, "load_context")
        backend = self._backend(state)
        detail = await backend.audit()
        audit, system = detail.get("audit") or {}, detail.get("system") or {}
        system_id = system.get("id") or state["system_id"]
        tree = await backend.tree()
        paths = {f.get("path"): f.get("version") for f in tree}
        card_text = await backend.read("system-card.yaml") if "system-card.yaml" in paths else None
        card = yaml.safe_load(card_text or "") or (system.get("data") or {}).get("card") or {}
        plugins = sorted(
            {
                p.split("/")[1]
                for p in paths
                if p and p.startswith("plugins/") and p.endswith("/plugin.yaml")
            }
        )
        target_dir = self._pick_plugin(audit, plugins, paths)
        if target_dir is None:
            raise StepFailed(f"{system_id} has no plugin with a data dictionary to test.")
        files: dict[str, str] = {}
        read_log = []
        for rel in (
            "plugin.yaml",
            "README.md",
            "data/data-dictionary.yaml",
            "data/training-data.md",
            "data/sample.csv",
            "data/business-rules.md",
        ):
            path = f"plugins/{target_dir}/{rel}"
            if path in paths:
                text = await backend.read(path)
                if text is not None:
                    files[rel] = text
                    read_log.append({"path": path, "version": paths[path]})
        if card_text is not None:
            files["system-card.yaml"] = card_text
            read_log.append({"path": "system-card.yaml", "version": paths["system-card.yaml"]})
        plugin = yaml.safe_load(files.get("plugin.yaml") or "") or {}
        target = str(plugin.get("id") or f"{system_id}.{target_dir}")
        regmem = self.deps.regmem
        warnings: list[str] = []
        kb_version = (audit.get("data") or {}).get("kb_version")
        requirements: list[dict[str, Any]] = []
        templates: list[dict[str, Any]] = []
        try:
            kb_version = kb_version or await regmem.active_kb_version()
            body = await regmem.requirements(
                role=card.get("role") or "provider",
                risk_class=risk_class(card),
                basis=annex_basis(card),
                date=self.deps.today(),
                kb_version=kb_version,
            )
            kb_version = body.get("kb_version") or kb_version
            requirements = list(body.get("items") or [])
            templates = await regmem.test_templates(kb_version)
        except Exception as exc:  # the audit still runs; the gap is on the artifact
            warnings.append(f"reg-memory unavailable: {getattr(exc, 'public', type(exc).__name__)}")
        keep = (
            "id",
            "source",
            "related",
            "obligation",
            "modality",
            "testability",
            "test_templates",
            "effective_valid_from",
            "in_force",
        )
        reqs = [{k: r.get(k) for k in keep if k in r} for r in requirements]
        tmpl_keep = (
            "id",
            "title",
            "supports",
            "needs",
            "data_strategy",
            "metric",
            "pass_criterion",
            "limitations",
        )
        tmpls = [{k: t.get(k) for k in tmpl_keep if k in t} for t in templates]
        update: dict[str, Any] = {
            **out,
            "system_id": system_id,
            "kb_version": kb_version or "unknown",
            "card": card,
            "target": target,
            "plugin_dir": f"plugins/{target_dir}",
            "files": files,
            "requirements": reqs,
            "templates": tmpls,
            "status": "running",
        }
        art_id = await self._artifact(
            {**state, **update},  # type: ignore[arg-type]
            "context",
            {
                "system": {
                    k: card.get(k)
                    for k in (
                        "id",
                        "name",
                        "role",
                        "risk_class",
                        "annex_basis",
                        "intended_purpose",
                        "protected_attributes",
                        "org_thresholds",
                        "card_version",
                    )
                },
                "target": target,
                "plugins": plugins,
                "requirements": reqs,
                "testable": [
                    r["id"] for r in reqs if r.get("testability") == "model_and_data_test"
                ],
                "test_templates": [t.get("id") for t in tmpls],
                "files_read": read_log,
                "dossier_version": (audit.get("data") or {}).get("dossier_version"),
                "warnings": warnings,
            },
        )
        self._finish("load_context")
        return {**update, "artifacts": {"context": art_id}}

    @staticmethod
    def _pick_plugin(audit: dict[str, Any], plugins: list[str], paths: dict) -> str | None:
        wanted = (audit.get("data") or {}).get("target_plugin")
        candidates = [p for p in plugins if f"plugins/{p}/data/data-dictionary.yaml" in paths]
        if wanted:
            name = str(wanted).split(".")[-1]
            if name in candidates:
                return name
        # The decision-making model: a ranker/scorer/classifier before a parser.
        for keyword in ("rank", "scor", "classif", "model"):
            for p in candidates:
                if keyword in p:
                    return p
        return candidates[0] if candidates else None

    async def profile_model(self, state: AuditState) -> dict[str, Any]:
        out = await self._start(state, "profile_model")
        files = self._base_files(state)
        result = await self._exec(
            state, "profile_model", profile_command("data/sample.csv" in files), files
        )
        profile = loads_json(result.text("model-profile.json"))
        if not result.ok or not isinstance(profile, dict):
            raise StepFailed(
                "synthkit profile failed "
                f"(exit {result.exit_code}): {result.stderr[-400:] or result.stdout[-400:]}"
            )
        art_id = await self._artifact(
            state, "model_profile", {"profile": profile, "sandbox": result.summary(300)}
        )
        self._finish("profile_model")
        return {**out, "profile": profile, "artifacts": {"model_profile": art_id}}

    async def find_public_data(self, state: AuditState) -> dict[str, Any]:
        out = await self._start(state, "find_public_data")
        plugin_name = str(state.get("plugin_dir", "")).split("/")[-1]
        search = self.deps.public_search
        public: dict[str, Any] = {"mode": "zero_shot"}
        if not settings.pipeline.public_data_enabled or search is None:
            public["reason"] = "public dataset search is off"
        else:
            try:
                result = await asyncio.to_thread(search, state["audit_id"], plugin_name, top=5)
            except Exception as exc:
                result = {"error": type(exc).__name__}
            hit = next(iter(result.get("results") or []), None)
            if hit is None:
                public["reason"] = f"search failed: {result.get('error') or 'no result'}"
            else:
                public.update(
                    {
                        "artifact_id": hit.get("artifact_id"),
                        "candidates": hit.get("candidates") or [],
                        "recommendation": hit.get("recommendation"),
                    }
                )
                best = next(
                    (c for c in hit.get("candidates") or [] if (c.get("score") or 0) >= 0.5), None
                )
                public["gate"] = best is not None
                public["reason"] = (
                    f"best candidate {best.get('id')} ({best.get('score')})"
                    if best
                    else "no candidate scores >= 0.5: zero-shot from the data dictionary"
                )
        arts = (
            {"public_dataset_candidates": public.get("artifact_id")}
            if public.get("artifact_id")
            else {}
        )
        self._finish("find_public_data")
        return {**out, "public_data": public, "artifacts": arts}

    async def gate_public_data(self, state: AuditState) -> dict[str, Any]:
        public = dict(state.get("public_data") or {})
        if not public.get("gate"):
            return {
                "gates": {"public_data": {"decision": "skipped", "reason": public.get("reason")}}
            }
        decision = await self._gate(state, "public_data", {"candidates": public.get("candidates")})
        if decision["decision"] == "approved":
            chosen = decision.get("selected") or (public.get("recommendation") or {}).get(
                "candidate"
            )
            fetch = self.deps.public_fetch
            plugin_name = str(state.get("plugin_dir", "")).split("/")[-1]
            try:
                fetched = (
                    await asyncio.to_thread(fetch, state["audit_id"], chosen, plugin_name)
                    if fetch and chosen
                    else {"error": "nothing selected"}
                )
            except Exception as exc:
                fetched = {"error": type(exc).__name__}
            if fetched.get("error"):
                public.update(mode="zero_shot", reason=f"fetch failed: {fetched['error']}")
            else:
                folder = fetched.get("folder") or f"datasets/public/{fetched.get('slug')}/"
                public.update(
                    mode="reference_sample",
                    candidate=chosen,
                    folder=folder,
                    reference=f"{folder}data.csv",
                    fetched={
                        k: fetched.get(k)
                        for k in ("rows", "mapped_fields", "unmapped_fields", "sha256", "licence")
                    },
                )
        else:
            public.update(
                mode="zero_shot", reason=f"human: {decision.get('reason') or decision['decision']}"
            )
        return {"public_data": public, "gates": {"public_data": decision}}

    async def plan_scenarios(self, state: AuditState) -> dict[str, Any]:
        out = await self._start(state, "plan_scenarios")
        feedback = (state.get("feedback") or {}).get("plan_scenarios")
        brief = {
            "audit_id": state["audit_id"],
            "kb_version": state.get("kb_version"),
            "system": {
                k: (state.get("card") or {}).get(k)
                for k in (
                    "id",
                    "name",
                    "annex_basis",
                    "intended_purpose",
                    "protected_attributes",
                    "known_proxies",
                    "org_thresholds",
                    "human_oversight",
                )
            },
            "target": state.get("target"),
            "plugin_yaml": (state.get("files") or {}).get("plugin.yaml"),
            "data_dictionary": (state.get("files") or {}).get("data/data-dictionary.yaml"),
            "training_data": (state.get("files") or {}).get("data/training-data.md"),
            "requirements": state.get("requirements"),
            "test_templates": state.get("templates"),
            "model_profile": profile_digest(state.get("profile")),
            "public_data": {
                k: (state.get("public_data") or {}).get(k) for k in ("mode", "reason", "candidate")
            },
            "previous_plan": state.get("scenarios") if feedback else None,
        }
        plan = await self.deps.steps.run(
            "plan_scenarios",
            brief,
            self._scope(state, "plan_scenarios"),
            feedback=feedback,
            fake=lambda: fakes.plan_scenarios(dict(state)),
        )
        data = plan.model_dump(mode="json")
        art_id = await self._artifact(state, "scenarios", {**data, "yaml": dumps_yaml(data)})
        self._finish("plan_scenarios")
        return {**out, "scenarios": data, "artifacts": {"scenarios": art_id}}

    async def analyse_scenarios(self, state: AuditState) -> dict[str, Any]:
        out = await self._start(state, "analyse_scenarios")
        files = self._base_files(state)
        files["scenarios.yaml"] = dumps_yaml(state.get("scenarios") or {})
        result = await self._exec(
            state,
            "analyse_scenarios",
            scenarios_check_command("model-profile.json" in files),
            files,
        )
        analysis = loads_json(result.text("scenario-analysis.json")) or {}
        if not result.ok and not analysis:
            raise StepFailed(f"synthkit scenarios-check failed: {result.stderr[-400:]}")
        problems = scenario_problems(analysis)
        update: dict[str, Any] = {**out, "scenario_analysis": analysis}
        used = int((state.get("auto_redos") or {}).get("plan_scenarios", 0))
        if problems and used < settings.pipeline.max_auto_redos:
            update["route"] = "redo"
            update["auto_redos"] = {"plan_scenarios": used + 1}
            update["feedback"] = {
                "plan_scenarios": {
                    "source": "verifier",
                    "check": "synthkit scenarios-check",
                    "problems": problems,
                }
            }
        else:
            update["route"] = "next"
        art_id = await self._artifact(
            state,
            "scenario_analysis",
            {
                "analysis": analysis,
                "markdown": result.text("scenario-analysis.md"),
                "verifier": {"problems": problems, "action": update["route"]},
            },
        )
        update["artifacts"] = {"scenario_analysis": art_id}
        self._finish("analyse_scenarios")
        return update

    async def _gate(self, state: AuditState, gate: str, summary: dict[str, Any]) -> dict[str, Any]:
        spec = GATES[gate]
        artifacts = state.get("artifacts") or {}
        reviews = {kind: artifacts.get(kind) for kind in spec["reviews"] if artifacts.get(kind)}
        await self._start(state, spec["stage"], status="waiting_approval")
        payload = {
            "type": "audit_gate",
            "gate": gate,
            "audit_id": state["audit_id"],
            "stage": spec["stage"],
            "artifact_ids": reviews,
            "artifact_id": next(iter(reviews.values()), None),
            "decisions": ["approved", "changes_requested", "rejected"],
            "summary": summary,
        }
        decision = normalise_decision(interrupt(payload))
        logger.info(
            "pipeline_gate_decided", "Gate decided", gate=gate, decision=decision["decision"]
        )
        try:
            await self._backend(state).patch(status="running")
        except Exception:
            logger.warning("pipeline_stage_patch_failed", "Stage patch failed", stage=spec["stage"])
        self._finish(spec["stage"])
        return decision

    async def _gate_with_redo(self, state: AuditState, gate: str, summary: dict) -> dict[str, Any]:
        decision = await self._gate(state, gate, summary)
        redo = GATES[gate]["redo"]
        update: dict[str, Any] = {"gates": {gate: decision}}
        if decision["decision"] == "approved":
            update["route"] = "next"
            update["feedback"] = {redo: None}
            return update
        used = int((state.get("redos") or {}).get(redo, 0))
        if used >= settings.pipeline.max_redos:
            update["route"] = "stop"
            update["status"] = "rejected"
            return update
        update["route"] = "redo"
        update["redos"] = {redo: used + 1}
        update["auto_redos"] = {redo: 0}
        update["feedback"] = {
            redo: {
                "source": "human",
                "gate": gate,
                "decision": decision["decision"],
                "category": decision["category"],
                "reason": decision["reason"],
                "edits": decision.get("edits") or None,
                "attempt": used + 1,
            }
        }
        return update

    async def gate_scenarios(self, state: AuditState) -> dict[str, Any]:
        scenarios = (state.get("scenarios") or {}).get("scenarios") or []
        analysis = state.get("scenario_analysis") or {}
        return await self._gate_with_redo(
            state,
            "scenarios",
            {
                "scenarios": [
                    {k: s.get(k) for k in ("id", "requirement", "template", "metric")}
                    for s in scenarios
                ],
                "check": {
                    "status": analysis.get("status"),
                    "missing": (analysis.get("missing") or [])[:8],
                },
            },
        )

    async def draft_spec(self, state: AuditState) -> dict[str, Any]:
        out = await self._start(state, "draft_spec")
        feedback = (state.get("feedback") or {}).get("draft_spec")
        public = state.get("public_data") or {}
        brief = {
            "audit_id": state["audit_id"],
            "target": state.get("target"),
            "scenarios": (state.get("scenarios") or {}).get("scenarios"),
            "data_dictionary": (state.get("files") or {}).get("data/data-dictionary.yaml"),
            "training_data": (state.get("files") or {}).get("data/training-data.md"),
            "model_profile": profile_digest(state.get("profile")),
            "public_data": {k: public.get(k) for k in ("mode", "reference", "fetched", "reason")},
            "seed": settings.pipeline.seed,
            "spec_format": SPEC_FORMAT,
            "previous_spec": (state.get("spec") or {}).get("yaml") if feedback else None,
        }
        draft = await self.deps.steps.run(
            "draft_spec",
            brief,
            self._scope(state, "draft_spec"),
            feedback=feedback,
            fake=lambda: fakes.draft_spec(dict(state)),
        )
        spec, problems = parse_spec(draft.spec_yaml)
        data = draft.model_dump(mode="json")
        spec_doc = {
            **data,
            "yaml": draft.spec_yaml,
            "parsed": spec,
            "problems": problems,
            "seed": settings.pipeline.seed,
        }
        art_id = await self._artifact(state, "generation_spec", spec_doc)
        self._finish("draft_spec")
        return {**out, "spec": spec_doc, "artifacts": {"generation_spec": art_id}}

    def _spec_redo(
        self, state: AuditState, check: str, problems: list[str]
    ) -> dict[str, Any] | None:
        used = int((state.get("auto_redos") or {}).get("draft_spec", 0))
        if used >= settings.pipeline.max_auto_redos:
            return None
        return {
            "route": "redo",
            "auto_redos": {"draft_spec": used + 1},
            "feedback": {
                "draft_spec": {"source": "verifier", "check": check, "problems": problems}
            },
        }

    async def generate_data(self, state: AuditState) -> dict[str, Any]:
        out = await self._start(state, "generate_data")
        spec = state.get("spec") or {}
        problems = list(spec.get("problems") or [])
        result: ExecResult | None = None
        if spec.get("parsed") is not None:
            files = {**self._base_files(state), **await self._public_files(state)}
            result = await self._exec(
                state, "generate_data", generate_command(settings.pipeline.seed), files
            )
            if not result.ok:
                problems.append(
                    f"synthkit generate exit {result.exit_code}: {result.stderr[-600:]}"
                )
        if problems:
            redo = self._spec_redo(state, "synthkit generate", problems)
            if redo is None:
                raise StepFailed(f"The GenerationSpec is still invalid: {problems[0]}")
            await self._artifact(state, "dataset", {"status": "invalid_spec", "problems": problems})
            self._finish("generate_data")
            return {**out, **redo}
        if result is None:  # unreachable: no problems means generate ran
            raise StepFailed("synthkit generate did not run.")
        card = yaml.safe_load(result.text("DataCard.yaml") or "") or {}
        dataset = {
            "data_card": card,
            "sample_rows": result.text("sample-rows.csv"),
            "seed": settings.pipeline.seed,
            "sandbox": result.summary(300),
        }
        art_id = await self._artifact(
            state,
            "dataset",
            dataset,
            file_refs=[
                {"dataset_id": card.get("dataset_id"), "content_sha256": card.get("content_sha256")}
            ],
        )
        self._finish("generate_data")
        return {**out, "dataset": dataset, "route": "next", "artifacts": {"dataset": art_id}}

    async def analyse_datasets(self, state: AuditState) -> dict[str, Any]:
        out = await self._start(state, "analyse_datasets")
        files = {**self._base_files(state), **await self._public_files(state)}
        result = await self._exec(
            state,
            "analyse_datasets",
            analyze_command(settings.pipeline.seed, "model-profile.json" in files),
            files,
        )
        analysis = loads_json(result.text("dataset-analysis.json")) or {}
        if not analysis:
            raise StepFailed(
                f"synthkit analyze failed (exit {result.exit_code}): {result.stderr[-400:]}"
            )
        problems = dataset_problems(analysis)
        update: dict[str, Any] = {**out, "dataset_analysis": analysis, "route": "next"}
        if problems:
            redo = self._spec_redo(state, "synthkit analyze (blocking gates)", problems)
            if redo is not None:
                update.update(redo)
        art_id = await self._artifact(
            state,
            "dataset_analysis",
            {
                "analysis": analysis,
                "markdown": result.text("dataset-analysis.md"),
                "data_card": (state.get("dataset") or {}).get("data_card"),
                "verifier": {"problems": problems, "action": update["route"]},
            },
        )
        update["artifacts"] = {"dataset_analysis": art_id}
        self._finish("analyse_datasets")
        return update

    async def gate_datasets(self, state: AuditState) -> dict[str, Any]:
        spec = state.get("spec") or {}
        return await self._gate_with_redo(
            state,
            "datasets",
            {
                "dataset_id": ((state.get("dataset") or {}).get("data_card") or {}).get(
                    "dataset_id"
                ),
                "analysis": analysis_digest(state.get("dataset_analysis")),
                "assumptions": spec.get("assumptions"),
            },
        )

    async def run_tests(self, state: AuditState) -> dict[str, Any]:
        out = await self._start(state, "run_tests")
        seed = settings.pipeline.seed
        plan = build_test_plan(dict(state), seed)
        plan_id = await self._artifact(state, "test_plan", plan)
        files = {**self._base_files(state), **await self._public_files(state)}
        files["test-plan.yaml"] = dumps_yaml(plan)
        result = await self._exec(state, "run_tests", run_tests_command(seed), files)
        raw = loads_json(result.text("results/test-results.json"))
        # No results file: every planned test is an error row (the findings say inconclusive).
        results = normalise_results(raw if raw is not None else {"results": []}, plan)
        if raw is None:
            tail = (result.stderr or result.stdout)[-600:]
            results["error"] = f"synthkit run-tests exit {result.exit_code}: {tail}"
        runs = [t["mlflow_run_id"] for t in results["tests"] if t.get("mlflow_run_id")]
        res_id = await self._artifact(
            state,
            "test_result",
            {**results, "sandbox": result.summary(600)},
            file_refs=[f"mlflow:runs/{run}" for run in runs],
        )
        self._finish("run_tests")
        return {
            **out,
            "test_plan": plan,
            "test_results": results,
            "artifacts": {"test_plan": plan_id, "test_result": res_id},
        }

    async def analyse(self, state: AuditState) -> dict[str, Any]:
        out = await self._start(state, "analyse")
        feedback = (state.get("feedback") or {}).get("analyse")
        brief = {
            "audit_id": state["audit_id"],
            "kb_version": state.get("kb_version"),
            "target": state.get("target"),
            "org_thresholds": (state.get("card") or {}).get("org_thresholds"),
            "requirements": [
                r
                for r in state.get("requirements") or []
                if r.get("id")
                in {t.get("requirement") for t in (state.get("test_plan") or {}).get("tests") or []}
            ],
            "scenarios": (state.get("scenarios") or {}).get("scenarios"),
            "test_results": state.get("test_results"),
            "dataset_analysis": analysis_digest(state.get("dataset_analysis")),
            "data_card_limitations": ((state.get("dataset") or {}).get("data_card") or {}).get(
                "limitations"
            ),
            "plugin_known_limitations": (
                (yaml.safe_load((state.get("files") or {}).get("plugin.yaml") or "") or {}).get(
                    "expected_behaviour"
                )
                or {}
            ).get("known_limitations"),
        }
        files = {
            **self._base_files(state),
            "test-results.json": json.dumps(state.get("test_results")),
        }
        result = await self.deps.steps.run(
            "analyse",
            brief,
            self._scope(state, "analyse", files),
            feedback=feedback,
            fake=lambda: fakes.analyse(dict(state)),
        )
        findings = [f.model_dump(mode="json") for f in result.findings]  # type: ignore[attr-defined]
        problems = evidence_problems(findings, state.get("test_results") or {})
        used = int((state.get("auto_redos") or {}).get("analyse", 0))
        update: dict[str, Any] = {**out, "findings": findings, "route": "next"}
        if problems and used < settings.pipeline.max_auto_redos:
            update.update(
                route="redo",
                auto_redos={"analyse": used + 1},
                feedback={
                    "analyse": {
                        "source": "verifier",
                        "check": "evidence grounding",
                        "problems": problems,
                    }
                },
            )
            self._finish("analyse")
            return update
        ids = {}
        for finding in findings:
            finding["grounding_problems"] = [
                p for p in problems if p.startswith(f"{finding['id']}:")
            ]
            ids[finding["id"]] = await self._artifact(
                state,
                "finding",
                finding,
                name=finding["id"],
                file_refs=[
                    f"mlflow:runs/{e['mlflow_run_id']}"
                    for e in finding.get("evidence") or []
                    if e.get("mlflow_run_id")
                ],
            )
        update["artifacts"] = {"finding": ids}
        update["feedback"] = {"analyse": None}
        self._finish("analyse")
        return update

    async def critic(self, state: AuditState) -> dict[str, Any]:
        out = await self._start(state, "critic")
        findings = state.get("findings") or []
        brief = {
            "audit_id": state["audit_id"],
            "kb_version": state.get("kb_version"),
            "findings": findings,
            "test_results": state.get("test_results"),
            "dataset_analysis": analysis_digest(state.get("dataset_analysis")),
            "data_card_limitations": ((state.get("dataset") or {}).get("data_card") or {}).get(
                "limitations"
            ),
            "model_profile": profile_digest(state.get("profile")),
            "org_thresholds": (state.get("card") or {}).get("org_thresholds"),
        }
        files = {
            **self._base_files(state),
            "test-results.json": json.dumps(state.get("test_results")),
        }
        report = await self.deps.steps.run(
            "critic",
            brief,
            self._scope(state, "critic", files),
            fake=lambda: fakes.critic(dict(state)),
        )
        reviews = {r.finding_id: r.model_dump(mode="json") for r in report.reviews}  # type: ignore[attr-defined]
        adjusted = []
        finding_ids = dict((state.get("artifacts") or {}).get("finding") or {})
        for finding in findings:
            review = reviews.get(finding["id"])
            if review is None:
                adjusted.append(finding)
                continue
            new = {
                **finding,
                "verdict_before_critic": finding["verdict"],
                "confidence_before_critic": finding["confidence"],
                "verdict": review["adjusted_verdict"],
                "confidence": review["adjusted_confidence"],
                "critic": {
                    k: review[k] for k in ("call", "strongest_objection", "checked_evidence")
                },
            }
            adjusted.append(new)
            if review["call"] != "upheld" or new["verdict"] != finding["verdict"]:
                finding_ids[finding["id"]] = await self._artifact(
                    state, "finding", new, name=finding["id"]
                )
        art_id = await self._artifact(
            state,
            "critic",
            {
                **report.model_dump(mode="json"),
                "unreviewed": [f["id"] for f in findings if f["id"] not in reviews],
            },
        )
        self._finish("critic")
        return {
            **out,
            "findings": adjusted,
            "critic": report.model_dump(mode="json"),
            "artifacts": {"critic": art_id, "finding": finding_ids},
        }

    async def report(self, state: AuditState) -> dict[str, Any]:
        out = await self._start(state, "report")
        card = (state.get("dataset") or {}).get("data_card") or {}
        plugin = yaml.safe_load((state.get("files") or {}).get("plugin.yaml") or "") or {}
        brief = {
            "audit_id": state["audit_id"],
            "system_id": state.get("system_id"),
            "kb_version": state.get("kb_version"),
            "target": state.get("target"),
            "model": plugin.get("access"),
            "dataset": {
                "dataset_id": card.get("dataset_id"),
                "seed": settings.pipeline.seed,
                "content_sha256": card.get("content_sha256"),
            },
            "tests": [
                {
                    k: t.get(k)
                    for k in (
                        "id",
                        "requirement",
                        "metric",
                        "value",
                        "ci95",
                        "status",
                        "mlflow_run_id",
                    )
                }
                for t in (state.get("test_results") or {}).get("tests") or []
            ],
            "findings": state.get("findings"),
            "critic": state.get("critic"),
            "gates": state.get("gates"),
        }
        result = await self.deps.steps.run(
            "report", brief, self._scope(state, "report"), fake=lambda: fakes.report(dict(state))
        )
        data = result.model_dump(mode="json")
        art_id = await self._artifact(state, "report", data)
        self._finish("report")
        return {**out, "report": data, "artifacts": {"report": art_id}}

    async def finalize(self, state: AuditState) -> dict[str, Any]:
        status = "done"
        verdicts: dict[str, int] = {}
        for f in state.get("findings") or []:
            verdicts[f.get("verdict", "?")] = verdicts.get(f.get("verdict", "?"), 0) + 1
        try:
            await self._backend(state).patch(
                stage="report",
                status=status,
                data={"verdicts": verdicts, "finishedAt": datetime.now(UTC).isoformat()},
            )
        except Exception:
            logger.warning("pipeline_stage_patch_failed", "Final patch failed")
        return {"status": status}

    async def stop(self, state: AuditState) -> dict[str, Any]:
        """A gate's redo budget is spent: the audit ends as rejected."""
        try:
            await self._backend(state).patch(
                status="failed",
                data={"outcome": "rejected", "stoppedAt": datetime.now(UTC).isoformat()},
            )
        except Exception:
            logger.warning("pipeline_stage_patch_failed", "Stop patch failed")
        return {"status": "rejected"}

    # ---------------------------------------------------------------- graph
    def build(self, checkpointer: Any = None) -> Any:
        graph = StateGraph(AuditState)
        for name in NODE_ORDER:
            graph.add_node(name, getattr(self, name))
        graph.add_node("stop", self.stop)
        graph.add_edge(START, "load_context")
        graph.add_edge("load_context", "profile_model")
        graph.add_edge("profile_model", "find_public_data")
        graph.add_edge("find_public_data", "gate_public_data")
        graph.add_edge("gate_public_data", "plan_scenarios")
        graph.add_edge("plan_scenarios", "analyse_scenarios")
        graph.add_conditional_edges(
            "analyse_scenarios", _route, {"redo": "plan_scenarios", "next": "gate_scenarios"}
        )
        graph.add_conditional_edges(
            "gate_scenarios",
            _route,
            {"redo": "plan_scenarios", "next": "draft_spec", "stop": "stop"},
        )
        graph.add_edge("draft_spec", "generate_data")
        graph.add_conditional_edges(
            "generate_data", _route, {"redo": "draft_spec", "next": "analyse_datasets"}
        )
        graph.add_conditional_edges(
            "analyse_datasets", _route, {"redo": "draft_spec", "next": "gate_datasets"}
        )
        graph.add_conditional_edges(
            "gate_datasets", _route, {"redo": "draft_spec", "next": "run_tests", "stop": "stop"}
        )
        graph.add_edge("run_tests", "analyse")
        graph.add_conditional_edges("analyse", _route, {"redo": "analyse", "next": "critic"})
        graph.add_edge("critic", "report")
        graph.add_edge("report", "finalize")
        graph.add_edge("finalize", END)
        graph.add_edge("stop", END)
        return graph.compile(checkpointer=checkpointer)


def _route(state: AuditState) -> str:
    return state.get("route") or "next"


#: The nodes in pipeline order (gates included).
NODE_ORDER = (
    "load_context",
    "profile_model",
    "find_public_data",
    "gate_public_data",
    "plan_scenarios",
    "analyse_scenarios",
    "gate_scenarios",
    "draft_spec",
    "generate_data",
    "analyse_datasets",
    "gate_datasets",
    "run_tests",
    "analyse",
    "critic",
    "report",
    "finalize",
)

__all__ = [
    "GATES",
    "NODE_ORDER",
    "AuditPipeline",
    "PipelineDeps",
    "StepFailed",
    "annex_basis",
    "normalise_decision",
    "profile_digest",
]
