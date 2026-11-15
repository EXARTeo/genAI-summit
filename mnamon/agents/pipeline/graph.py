"""The engineer audit pipeline as a LangGraph ``StateGraph``.

Order (fixed by code, CLAUDE.md § The product)::

    load_context → pin → ground_obligations → profile_model → plan_scenarios →
    analyse_scenarios → [gate scenarios] → find_public_data → [gate public_data] →
    draft_spec → generate_data → analyse_datasets → [gate datasets] →
    run_inference → analyse_results → assess_obligations → critic → seal →
    report → finalize

Plan 01 (obligation-driven): ``pin`` records kb / dossier / config / the concrete
model version / seeds on the audit; ``ground_obligations`` builds the system's
obligation map (``pipeline/obligations.py``, the requirement list as fallback)
and every scenario names an obligation; ``run_inference`` only calls the model
and saves the raw predictions (hashed, MLflow); ``analyse_results`` computes
the metrics from those saved files (synthkit) and lets the analyst run its own
code over them; ``assess_obligations`` gives every obligation in scope a rule
verdict, a Gemini explanation and an independent Iris verdict (disagreement =
``inconclusive`` + needs_human); ``seal`` hash-chains exactly one finding per
obligation. Any unrecoverable node failure writes an incomplete-audit report.

The public data search runs after the scenarios are approved, so it looks for
datasets that carry what those scenarios need (their fields, protected
attributes and use cases).

* **Code nodes** (deterministic): the backend's internal API, reg-memory, and
  the sandbox runner with synthkit (``profile``, ``scenarios-check``,
  ``generate``, ``analyze``, ``run-tests``).
* **Deep-agent nodes** (``plan_scenarios``, ``draft_spec``, ``analyse``,
  ``critic``, ``report``): a scoped deep agent that returns ONE validated result
  model (``pipeline/steps.py``).
* **Verifiers** (``pipeline/verify.py``) send a failed output back to its step
  with the report, at most ``PIPELINE_MAX_AUTO_REDOS`` times.
* **Decision model** (``pipeline/decision.py``): in ``analyse_scenarios`` Oumi
  *Iris* (Gemini as fallback) reviews each scenario (``relevant |
  needs_change | not_relevant``); ``needs_change`` goes back to
  ``plan_scenarios`` within the same redo budget, ``not_relevant`` is flagged
  for the human at the gate.
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
import base64
import hashlib
import json
import os
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import httpx
import yaml
from ag_ui.core import EventType, StepFinishedEvent, StepStartedEvent
from langgraph.config import get_stream_writer
from langgraph.errors import GraphBubbleUp
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from core.logging import get_logger
from core.settings import settings
from harness.agui.emitter import AGUIEmitter, encode
from harness.memory.store import MemoryStoreProtocol
from pipeline import fakes
from pipeline.clients import (
    BackendInternal,
    ExecResult,
    PipelineHTTPError,
    RegMemory,
    SandboxRunner,
)
from pipeline.decision import DecisionModel, IrisClient
from pipeline.scenario_review import SCENARIO_REVIEW, review_brief, review_context
from pipeline.schemas import ScenarioReview, VerdictJudgement
from pipeline.state import AuditState
from pipeline.steps import StepRunner, StepScope
from pipeline.testplan import (
    DATA_REL,
    INFERENCE_REL,
    TEMPLATE_IDS,
    analyze_saved_command,
    build_test_plan,
    dumps_yaml,
    generate_saved_command,
    loads_json,
    metrics_command,
    normalise_results,
    profile_command,
    run_inference_command,
    scenarios_check_command,
)
from pipeline.verdict_review import VERDICT_JUDGE, judge_brief
from pipeline.verdicts import (
    LEGACY_VERDICT,
    citation_problems,
    combine,
    coverage_problems,
    dossier_evidence,
    fallback_obligation_map,
    in_scope,
    is_tested,
    obligation_for_requirement,
    rows_for,
    rule_verdict,
    severity,
    templates_of,
)
from pipeline.verdicts import seal as seal_findings
from pipeline.verify import (
    dataset_problems,
    normalise_spec,
    parse_spec,
    scenario_problems,
)

try:  # Agent B's obligation catalogue client (plan 01 §3.3); the requirement list is the fallback
    from pipeline.obligations import resolve_obligation_map
except ImportError:  # pragma: no cover - only before that module lands
    resolve_obligation_map = None

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
#: Scenario reviews the decision model runs at once.
REVIEW_CONCURRENCY = 4
_ANNEX_RE = re.compile(r"Annex\s+([IVX]+)\s*(\d+)?\s*(?:\(([a-z])\))?", re.IGNORECASE)
_MODEL_URI = re.compile(r"^models:/([^@/]+)(?:@([^/]+)|/(\d+))?$")
#: MLflow's REST API (the model registry) as the agents service reaches it.
MLFLOW_URL = os.environ.get("MLFLOW_TRACKING_URI", "http://mlflow:5000").rstrip("/")

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
    iris: IrisClient | None = None  # None = from settings (OUMI_*)
    #: A focused re-run's delta report (``utils.change_judge.delta_for_audit``), at the end.
    delta: Callable[[str], Any] | None = None
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
            "focus": [str(x) for x in (audit.get("data") or {}).get("obligations") or [] if x],
            "change_id": (audit.get("data") or {}).get("change_id"),
            "dossier_paths": sorted(p for p in paths if p),
            "dossier_version": (audit.get("data") or {}).get("dossier_version"),
            "config_version": paths.get(f"plugins/{target_dir}/plugin.yaml"),
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
            scenarios = (state.get("scenarios") or {}).get("scenarios") or []
            try:
                result = await asyncio.to_thread(
                    search, state["audit_id"], plugin_name, top=5, scenarios=scenarios
                )
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
        update = await self._public_data_decision(state)
        # An audit started under the old order (public data before the scenarios)
        # resumes here without a plan: plan the scenarios first (best effort).
        has_plan = bool((state.get("scenarios") or {}).get("scenarios"))
        return {**update, "route": "next" if has_plan else "plan"}

    async def _public_data_decision(self, state: AuditState) -> dict[str, Any]:
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
            "obligations": [
                {
                    k: e.get(k)
                    for k in ("obligation_id", "article", "summary", "checks", "requirements")
                }
                for e in state.get("scope") or []
                if is_tested(e)
            ],
            "requirements": state.get("requirements"),
            "test_templates": state.get("templates"),
            "model_profile": profile_digest(state.get("profile")),
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
        data["scenarios"] = self._attach_obligations(state, data.get("scenarios") or [])
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
        plan = dict(state.get("scenarios") or {})
        reviews = await self._review_scenarios(state)
        if reviews:
            plan["scenarios"] = [
                {**sc, "review": reviews[sc.get("id")]} if sc.get("id") in reviews else sc
                for sc in plan.get("scenarios") or []
            ]
            update["scenarios"] = plan
            update["artifacts"] = {
                "scenarios": await self._artifact(
                    state, "scenarios", {**plan, "yaml": dumps_yaml(plan)}
                )
            }
        needs_change = [
            {"id": sid, "suggested_change": r.get("suggested_change"), "model": r.get("model")}
            for sid, r in reviews.items()
            if r.get("verdict") == "needs_change"
        ]
        flagged = sorted(sid for sid, r in reviews.items() if r.get("verdict") == "not_relevant")
        review_problems = [
            f"{c['id']}: {c['model']} review says needs_change: {c['suggested_change']}"
            for c in needs_change
        ]
        used = int((state.get("auto_redos") or {}).get("plan_scenarios", 0))
        if (problems or needs_change) and used < settings.pipeline.max_auto_redos:
            update["route"] = "redo"
            update["auto_redos"] = {"plan_scenarios": used + 1}
            checks = ["synthkit scenarios-check"] if problems else []
            checks += ["decision-model scenario review"] if needs_change else []
            update["feedback"] = {
                "plan_scenarios": {
                    "source": "verifier",
                    "check": " + ".join(checks),
                    "problems": [*problems, *review_problems],
                    "scenario_reviews": needs_change or None,
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
                "verifier": {
                    "problems": [*problems, *review_problems],
                    "action": update["route"],
                    "flagged": flagged,
                },
                "review": {
                    "model": settings.pipeline.scenario_review_model,
                    "verdicts": {sid: r.get("verdict") for sid, r in reviews.items()},
                    "by": {sid: r.get("model") for sid, r in reviews.items()},
                    "needs_change": [c["id"] for c in needs_change],
                    "flagged": flagged,
                },
            },
        )
        update["artifacts"] = {**(update.get("artifacts") or {}), "scenario_analysis": art_id}
        self._finish("analyse_scenarios")
        return update

    async def _review_scenarios(self, state: AuditState) -> dict[str, dict[str, Any]]:
        """Scenario id -> ``review`` (``SCENARIO_REVIEW_MODEL``; fail-open per scenario)."""
        mode = settings.pipeline.scenario_review_model
        scenarios = (state.get("scenarios") or {}).get("scenarios") or []
        if mode == "off" or not scenarios:
            return {}
        model = DecisionModel(
            "iris" if mode == "iris" else "gemini",
            steps=self.deps.steps,
            iris=self.deps.iris,
            trace_id=self.deps.trace_id,
        )
        context = review_context(dict(state), profile_digest(state.get("profile")).get("proxies"))
        scope = self._scope(state, "scenario_review")
        gate = asyncio.Semaphore(REVIEW_CONCURRENCY)

        async def one(scenario: dict[str, Any]) -> tuple[Any, dict[str, Any] | None]:
            async with gate:
                try:
                    decision = await model.decide(
                        SCENARIO_REVIEW, review_brief(context, scenario), ScenarioReview, scope
                    )
                except Exception as exc:  # advisory: an unreviewed scenario still reaches the gate
                    logger.warning(
                        "scenario_review_failed",
                        "Scenario review failed",
                        scenario=scenario.get("id"),
                        failure_reason=type(exc).__name__,
                    )
                    return scenario.get("id"), None
            return scenario.get("id"), {
                "model": decision.model,
                **decision.result.model_dump(mode="json"),
            }

        results = await asyncio.gather(*(one(sc) for sc in scenarios))
        return {sid: review for sid, review in results if sid and review}

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
                    {
                        **{k: s.get(k) for k in ("id", "requirement", "template", "metric")},
                        "review": (s.get("review") or {}).get("verdict"),
                    }
                    for s in scenarios
                ],
                "flagged": [
                    s.get("id")
                    for s in scenarios
                    if (s.get("review") or {}).get("verdict") == "not_relevant"
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
        spec_yaml, code_fixes = normalise_spec(
            draft.spec_yaml,
            (state.get("files") or {}).get("data/data-dictionary.yaml"),
            has_profile=bool(state.get("profile")),
        )
        spec, problems = parse_spec(spec_yaml)
        data = draft.model_dump(mode="json")
        spec_doc = {
            **data,
            "spec_yaml": spec_yaml,
            "yaml": spec_yaml,
            "parsed": spec,
            "problems": problems,
            "code_fixes": code_fixes,
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
                state, "generate_data", generate_saved_command(settings.pipeline.seed), files
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
        card_yaml = result.text("generated/DataCard.yaml") or ""
        card = yaml.safe_load(card_yaml) or {}
        parquet = result.files.get("generated/dataset.parquet")
        if parquet is None:
            raise StepFailed("synthkit generate wrote no dataset.parquet.")
        sha = hashlib.sha256(parquet).hexdigest()
        dataset = {
            "data_card": card,
            "sample_rows": result.text("sample-rows.csv"),
            "seed": settings.pipeline.seed,
            "path": f"{DATA_REL}/dataset.parquet",
            "sha256": sha,
            "bytes": len(parquet),
            "sandbox": result.summary(300),
        }
        art_id = await self._artifact(
            state,
            "dataset",
            dataset,
            file_refs=[
                {
                    "dataset_id": card.get("dataset_id"),
                    "content_sha256": card.get("content_sha256"),
                    "path": dataset["path"],
                    "sha256": sha,
                }
            ],
        )
        self._finish("generate_data")
        saved = {
            **dataset,
            "parquet_b64": base64.b64encode(parquet).decode("ascii"),
            "data_card_yaml": card_yaml,
        }
        return {**out, "dataset": saved, "route": "next", "artifacts": {"dataset": art_id}}

    async def analyse_datasets(self, state: AuditState) -> dict[str, Any]:
        out = await self._start(state, "analyse_datasets")
        files: dict[str, str | bytes] = {
            **self._base_files(state),
            **await self._public_files(state),
            **self._data_files(state),
        }
        result = await self._exec(
            state,
            "analyse_datasets",
            analyze_saved_command(settings.pipeline.seed, "model-profile.json" in files),
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
                "dataset_sha256": (state.get("dataset") or {}).get("sha256"),
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

    # ------------------------------------------------- pin + obligations (plan 01 P3, P1)
    async def pin(self, state: AuditState) -> dict[str, Any]:
        """Pin kb, dossier, config, the concrete model version and the seeds; write them back."""
        out = await self._start(state, "pin")
        plugin = yaml.safe_load((state.get("files") or {}).get("plugin.yaml") or "") or {}
        model = await resolve_model_version(plugin.get("access") or {})
        seed = settings.pipeline.seed
        pins = {
            "kb_version": state.get("kb_version"),
            "dossier_version": state.get("dossier_version"),
            "config_version": state.get("config_version"),
            "config_path": f"{state.get('plugin_dir')}/plugin.yaml",
            "model_version": model.get("version"),
            "model": model,
            "seeds": {"generation": seed, "bootstrap": seed, "perturbation": seed},
            "focus": state.get("focus") or None,
            "pinned_at": datetime.now(UTC).isoformat(),
        }
        try:
            await self._backend(state).patch(
                data={"pins": pins, "kb_version": state.get("kb_version")}
            )
        except Exception:
            logger.warning("pipeline_pins_patch_failed", "Could not write the pins")
        art_id = await self._artifact(state, "pins", pins)
        self._finish("pin")
        return {**out, "pins": pins, "artifacts": {"pins": art_id}}

    async def ground_obligations(self, state: AuditState) -> dict[str, Any]:
        """The system's obligation map at the pinned kb (catalogue + rules + Iris on borderline)."""
        out = await self._start(state, "ground_obligations")
        card = state.get("card") or {}
        kb = state.get("kb_version")
        source, warning = "catalogue", None
        entries: list[dict[str, Any]] = []
        if resolve_obligation_map is not None:
            try:
                entries = await resolve_obligation_map(
                    card, kb, iris=self.deps.iris or IrisClient(), regmem=self.deps.regmem
                )
            except Exception as exc:
                warning = f"obligation catalogue unavailable: {type(exc).__name__}"
        else:
            warning = "obligation catalogue module not installed"
        if not entries:
            source = "requirements_fallback"
            entries = fallback_obligation_map(
                state.get("requirements") or [], today=self.deps.today()
            )
        scope = in_scope(entries, state.get("focus"))
        if state.get("focus") and not scope:
            warning = f"none of the focused obligations {state.get('focus')} applies"
        data = {
            "source": source,
            "warning": warning,
            "focus": state.get("focus") or None,
            "entries": entries,
            "applicable": [e["obligation_id"] for e in entries if e.get("applicable")],
            "in_scope": [e["obligation_id"] for e in scope],
            "tested": [e["obligation_id"] for e in scope if is_tested(e)],
            "documentary": [e["obligation_id"] for e in scope if not is_tested(e)],
            "by_iris": [e["obligation_id"] for e in entries if e.get("decided_by") == "iris"],
        }
        data["yaml"] = dumps_yaml({"obligations": entries})
        data["sha256"] = hashlib.sha256(data["yaml"].encode()).hexdigest()
        art_id = await self._artifact(state, "obligation_map", data)
        self._finish("ground_obligations")
        return {
            **out,
            "obligation_map": entries,
            "scope": scope,
            "artifacts": {"obligation_map": art_id},
        }

    def _attach_obligations(self, state: AuditState, scenarios: list[dict]) -> list[dict]:
        """Every scenario names a tested obligation in scope (code fills a missing one)."""
        tested = [e for e in state.get("scope") or [] if is_tested(e)]
        ids = {e["obligation_id"] for e in tested}
        out = []
        for sc in scenarios:
            oid = sc.get("obligation_id")
            if oid not in ids:
                template = TEMPLATE_IDS.get(str(sc.get("template")), sc.get("test_template"))
                oid = obligation_for_requirement(tested, sc.get("requirement")) or next(
                    (e["obligation_id"] for e in tested if template in templates_of(e)),
                    next(iter(sorted(ids)), None),
                )
            out.append({**sc, "obligation_id": oid})
        return out

    # ------------------------------------------------------- execute (raw, then analyse)
    def _data_files(self, state: AuditState) -> dict[str, str | bytes]:
        """The saved dataset (``input/data/generated/``), the same bytes every call."""
        dataset = state.get("dataset") or {}
        if not dataset.get("parquet_b64"):
            return {}
        files: dict[str, str | bytes] = {
            f"{DATA_REL}/dataset.parquet": base64.b64decode(dataset["parquet_b64"])
        }
        if dataset.get("data_card_yaml"):
            files[f"{DATA_REL}/DataCard.yaml"] = dataset["data_card_yaml"]
        return files

    def _inference_files(self, state: AuditState) -> dict[str, str | bytes]:
        inference = state.get("inference") or {}
        if not inference.get("predictions_b64"):
            return {}
        return {
            f"{INFERENCE_REL}/predictions.parquet": base64.b64decode(inference["predictions_b64"]),
            f"{INFERENCE_REL}/run.json": json.dumps(inference.get("run") or {}),
        }

    async def run_inference(self, state: AuditState) -> dict[str, Any]:
        """Call the model through modelaccess and SAVE the raw predictions (no metrics)."""
        out = await self._start(state, "run_inference")
        seed = settings.pipeline.seed
        plan = build_test_plan(dict(state), seed)
        plan_id = await self._artifact(state, "test_plan", plan)
        files: dict[str, str | bytes] = {**self._base_files(state), **self._data_files(state)}
        if f"{DATA_REL}/dataset.parquet" not in files:
            raise StepFailed("No saved dataset to run inference on; regenerate the data.")
        files["test-plan.yaml"] = dumps_yaml(plan)
        result = await self._exec(state, "run_inference", run_inference_command(seed), files)
        predictions = result.files.get(f"{INFERENCE_REL}/predictions.parquet")
        run = loads_json(result.text(f"{INFERENCE_REL}/run.json"))
        if not result.ok or predictions is None or not isinstance(run, dict):
            tail = (result.stderr or result.stdout)[-600:]
            raise StepFailed(f"synthkit run-inference failed (exit {result.exit_code}): {tail}")
        sha = hashlib.sha256(predictions).hexdigest()
        inference = {
            "run": run,
            "predictions_sha256": sha,
            "predictions_b64": base64.b64encode(predictions).decode("ascii"),
            "mlflow_run_id": run.get("mlflow_run_id"),
            "model_version": (run.get("model") or {}).get("version"),
        }
        art_id = await self._artifact(
            state,
            "inference",
            {
                "run": run,
                "predictions": {"path": f"{INFERENCE_REL}/predictions.parquet", "sha256": sha},
                "sandbox": result.summary(300),
                "note": "Raw predictions saved and hashed before any analysis (plan 01 P4).",
            },
            file_refs=[
                {"path": f"{INFERENCE_REL}/predictions.parquet", "sha256": sha},
                *([f"mlflow:runs/{run['mlflow_run_id']}"] if run.get("mlflow_run_id") else []),
            ],
        )
        self._finish("run_inference")
        return {
            **out,
            "test_plan": plan,
            "inference": inference,
            "artifacts": {"test_plan": plan_id, "inference": art_id},
        }

    async def analyse_results(self, state: AuditState) -> dict[str, Any]:
        """synthkit metrics over the saved predictions, then the analyst's own code over them."""
        out = await self._start(state, "analyse_results")
        seed = settings.pipeline.seed
        plan = state.get("test_plan") or {}
        files: dict[str, str | bytes] = {
            **self._base_files(state),
            **self._data_files(state),
            **self._inference_files(state),
            "test-plan.yaml": dumps_yaml(plan),
        }
        result = await self._exec(state, "analyse_results", metrics_command(seed), files)
        raw = loads_json(result.text("results/test-results.json"))
        results = normalise_results(raw if raw is not None else {"results": []}, plan)
        if raw is None:
            tail = (result.stderr or result.stdout)[-600:]
            results["error"] = f"synthkit metrics exit {result.exit_code}: {tail}"
        results["predictions_sha256"] = (state.get("inference") or {}).get("predictions_sha256")
        runs = [t["mlflow_run_id"] for t in results["tests"] if t.get("mlflow_run_id")]
        res_id = await self._artifact(
            state,
            "test_result",
            {**results, "sandbox": result.summary(600)},
            file_refs=sorted({f"mlflow:runs/{run}" for run in runs}),
        )
        # The analyst: own code over the saved files (advisory; the metrics above are code).
        tests_digest = [
            {
                k: t.get(k)
                for k in ("id", "test_id", "obligation_id", "metric", "value", "ci95", "status")
            }
            for t in results["tests"]
        ]
        brief = {
            "audit_id": state["audit_id"],
            "target": state.get("target"),
            "org_thresholds": (state.get("card") or {}).get("org_thresholds"),
            "scenarios": [
                {k: s.get(k) for k in ("id", "obligation_id", "template", "metric", "protected")}
                for s in (state.get("scenarios") or {}).get("scenarios") or []
            ],
            "tests": tests_digest,
            "files": sorted(files),
        }
        scope = self._scope(
            state, "analyse_results", {**files, "test-results.json": json.dumps(raw or {})}
        )
        analysis: dict[str, Any] = {"status": "done"}
        try:
            report = await self.deps.steps.run(
                "analyse_results",
                brief,
                scope,
                fake=lambda: fakes.analyse_results(brief),
            )
            analysis.update(report.model_dump(mode="json"))
        except GraphBubbleUp:
            raise
        except Exception as exc:
            analysis.update(status="analyst_failed", error=type(exc).__name__)
        analysis["mismatches"] = headline_mismatches(analysis.get("headline") or [], results)
        analysis["code"] = scope.exec_log
        art_id = await self._artifact(state, "analysis", analysis)
        self._finish("analyse_results")
        return {
            **out,
            "test_results": results,
            "analysis": analysis,
            "artifacts": {"test_result": res_id, "analysis": art_id},
        }

    # ---------------------------------------------------------------- judge (plan 01 §5)
    async def _known_provisions(self, ids: set[str], kb: str | None) -> dict[str, bool]:
        known: dict[str, bool] = {}
        for pid in sorted(i for i in ids if i):
            try:
                body = await self.deps.regmem.provision(pid, kb)
                known[pid] = isinstance(body, dict) and bool(body.get("id") or body.get("text"))
            except Exception:
                known[pid] = False
        return known

    async def assess_obligations(self, state: AuditState) -> dict[str, Any]:
        """Rule verdict (code) + Gemini assessor + an independent Iris verdict, compared."""
        out = await self._start(state, "assess_obligations")
        if not state.get("scope"):  # an audit started before the obligation map existed
            grounded = await self.ground_obligations(state)
            state = {**state, "scope": grounded["scope"]}  # type: ignore[assignment]
            out = {**out, "scope": grounded["scope"], "obligation_map": grounded["obligation_map"]}
        kb = state.get("kb_version")
        tests = (state.get("test_results") or {}).get("tests") or []
        paths = state.get("dossier_paths") or []
        tested, proposed = [], []
        for entry in state.get("scope") or []:
            rows = rows_for(entry, tests) if is_tested(entry) else []
            if rows:
                verdict, why = rule_verdict(rows)
                tested.append({"entry": entry, "rows": rows, "rule": verdict, "why": why})
            elif is_tested(entry) and entry.get("verification_mode") != "hybrid":
                proposed.append(self._untested(entry, kb))
            else:
                proposed.append(self._documentary(entry, paths, kb))
        assessments = await self._gemini_assess(state, tested)
        judgements = await self._iris_judge(state, tested)
        cited = {
            str(c.get("provision_id"))
            for a in assessments.values()
            for c in a.get("citations") or []
        } | {str(t["entry"].get("article")) for t in tested if t["entry"].get("article")}
        known = await self._known_provisions(cited, kb)
        for t in tested:
            proposed.append(self._tested_verdict(t, assessments, judgements, known, kb))
        order = {e["obligation_id"]: n for n, e in enumerate(state.get("scope") or [])}
        proposed.sort(key=lambda v: order.get(v["obligation_id"], 0))
        art_id = await self._artifact(
            state,
            "verdicts",
            {
                "status": "proposed",
                "verdicts": proposed,
                "needs_human": [v["obligation_id"] for v in proposed if v.get("needs_human")],
            },
        )
        self._finish("assess_obligations")
        return {**out, "verdicts": proposed, "artifacts": {"verdicts": art_id}}

    @staticmethod
    def _untested(entry: dict[str, Any], kb: str | None) -> dict[str, Any]:
        why = "no scenario of this audit tested it: the evidence cannot show it either way"
        article = entry.get("article")
        return {
            "obligation_id": entry["obligation_id"],
            "entry": entry,
            "verdict": "inconclusive",
            "reasoning": f"Inconclusive: {why}.",
            "counter_arguments": [],
            "would_change_if": ["A scenario for this obligation runs and meets its threshold."],
            "citations": [{"provision_id": article, "kb_version": kb}] if article else [],
            "judges": {"rule": {"verdict": "inconclusive", "why": why}},
            "rows": [],
            "needs_human": False,
        }

    @staticmethod
    def _documentary(entry: dict[str, Any], paths: list[str], kb: str | None) -> dict[str, Any]:
        evidence = dossier_evidence(entry, paths)
        missing = bool(evidence["missing"])
        article = entry.get("article")
        return {
            "obligation_id": entry["obligation_id"],
            "entry": entry,
            "verdict": "not_assessable_by_testing",
            "documentation_gap": missing,
            "dossier_evidence": evidence,
            "reasoning": (
                f"{entry.get('verification_mode') or 'documentary'} obligation: shown by "
                "documents, not by a model test. Dossier evidence present: "
                f"{', '.join(evidence['present']) or 'none'}; missing: "
                f"{', '.join(evidence['missing']) or 'none'}."
            ),
            "counter_arguments": [
                "A file name is not proof of its content; a human must review it."
            ],
            "would_change_if": ["The missing evidence is added to the system folder."]
            if missing
            else [],
            "citations": [{"provision_id": article, "kb_version": kb}] if article else [],
            "judges": {"rule": {"verdict": "not_assessable_by_testing", "why": "documentary"}},
            "rows": [],
            "needs_human": False,
        }

    async def _gemini_assess(
        self, state: AuditState, tested: list[dict[str, Any]]
    ) -> dict[str, dict[str, Any]]:
        if not tested:
            return {}
        brief = {
            "audit_id": state["audit_id"],
            "kb_version": state.get("kb_version"),
            "org_thresholds": (state.get("card") or {}).get("org_thresholds"),
            "declared_metrics": (state.get("card") or {}).get("declared_metrics"),
            "obligations": [
                {
                    **{
                        k: t["entry"].get(k)
                        for k in ("obligation_id", "article", "related", "summary")
                    },
                    "rule_verdict": t["rule"],
                    "rule_reason": t["why"],
                    "tests": [_row_digest(r) for r in t["rows"][:12]],
                }
                for t in tested
            ],
        }
        try:
            result = await self.deps.steps.run(
                "assess", brief, self._scope(state, "assess"), fake=lambda: fakes.assess(brief)
            )
        except GraphBubbleUp:
            raise
        except Exception as exc:
            logger.warning(
                "pipeline_assess_failed", "Assessor failed", failure_reason=type(exc).__name__
            )
            return {}
        return {
            a.obligation_id: a.model_dump(mode="json")
            for a in result.assessments  # type: ignore[attr-defined]
        }

    async def _iris_judge(
        self, state: AuditState, tested: list[dict[str, Any]]
    ) -> dict[str, dict[str, Any]]:
        model = DecisionModel(
            "iris", steps=self.deps.steps, iris=self.deps.iris, trace_id=self.deps.trace_id
        )
        scope = self._scope(state, "verdict_judge")
        gate = asyncio.Semaphore(REVIEW_CONCURRENCY)

        async def one(t: dict[str, Any]) -> tuple[str, dict[str, Any] | None]:
            oid = t["entry"]["obligation_id"]
            async with gate:
                try:
                    decision = await model.decide(
                        VERDICT_JUDGE, judge_brief(t["entry"], t["rows"]), VerdictJudgement, scope
                    )
                except GraphBubbleUp:
                    raise
                except Exception as exc:
                    logger.warning(
                        "pipeline_verdict_judge_failed",
                        "Independent verdict failed",
                        obligation_id=oid,
                        failure_reason=type(exc).__name__,
                    )
                    return oid, None
            return oid, {
                **decision.result.model_dump(mode="json"),
                "model": decision.model,
                "fallback": decision.fallback,
                "failure": decision.failure,
            }

        results = await asyncio.gather(*(one(t) for t in tested))
        return {oid: j for oid, j in results if j}

    @staticmethod
    def _tested_verdict(
        t: dict[str, Any],
        assessments: dict[str, dict[str, Any]],
        judgements: dict[str, dict[str, Any]],
        known: dict[str, bool],
        kb: str | None,
    ) -> dict[str, Any]:
        entry, oid = t["entry"], t["entry"]["obligation_id"]
        gemini = assessments.get(oid)
        iris = judgements.get(oid)
        verdict, needs_human = combine(
            t["rule"], (gemini or {}).get("verdict"), (iris or {}).get("verdict")
        )
        citations = [
            {"provision_id": c.get("provision_id"), "kb_version": kb}
            for c in (gemini or {}).get("citations") or []
        ]
        problems = citation_problems(citations, entry, known)
        bad = {p.split(":")[0] for p in problems}
        citations = [c for c in citations if c["provision_id"] not in bad]
        article = entry.get("article")
        if not citations and article and known.get(str(article)):
            citations = [{"provision_id": article, "kb_version": kb}]
        reasoning = (gemini or {}).get("reasoning") or (
            f"Rule verdict: {t['why']}. Thresholds are the organisation's, not the AI Act's."
        )
        if needs_human:
            reasoning += (
                f" Judges disagree (rule {t['rule']}, Gemini {(gemini or {}).get('verdict')}, "
                f"Iris {(iris or {}).get('verdict')}): inconclusive until a human decides."
            )
        return {
            "obligation_id": oid,
            "entry": entry,
            "verdict": verdict,
            "needs_human": needs_human,
            "reasoning": reasoning,
            "counter_arguments": (gemini or {}).get("counter_arguments") or [],
            "would_change_if": (gemini or {}).get("would_change_if") or [],
            "citations": citations,
            "citation_problems": problems,
            "judges": {
                "rule": {"verdict": t["rule"], "why": t["why"]},
                "gemini": {"verdict": (gemini or {}).get("verdict")}
                if gemini
                else {"verdict": None, "error": "assessor gave no verdict"},
                "iris": iris or {"verdict": None, "error": "no independent verdict"},
            },
            "rows": [r.get("id") for r in t["rows"]],
            "mlflow_runs": sorted(
                {r["mlflow_run_id"] for r in t["rows"] if r.get("mlflow_run_id")}
            ),
        }

    async def critic(self, state: AuditState) -> dict[str, Any]:
        """The critic tries to overturn each verdict; grounds per verdict, ``overall`` required."""
        out = await self._start(state, "critic")
        verdicts = state.get("verdicts") or []
        tests = {t.get("id"): t for t in (state.get("test_results") or {}).get("tests") or []}
        brief = {
            "audit_id": state["audit_id"],
            "kb_version": state.get("kb_version"),
            "org_thresholds": (state.get("card") or {}).get("org_thresholds"),
            "dataset_analysis": analysis_digest(state.get("dataset_analysis")),
            "data_card_limitations": ((state.get("dataset") or {}).get("data_card") or {}).get(
                "limitations"
            ),
            "verdicts": [
                {
                    "obligation_id": v["obligation_id"],
                    "verdict": v["verdict"],
                    "needs_human": v.get("needs_human"),
                    "judges": {k: (j or {}).get("verdict") for k, j in v["judges"].items()},
                    "reasoning": str(v.get("reasoning") or "")[:800],
                    "tests": [_row_digest(tests[r]) for r in v.get("rows") or [] if r in tests][:8],
                }
                for v in verdicts
                if v["verdict"] != "not_assessable_by_testing"
            ],
        }
        reviews: dict[str, dict[str, Any]] = {}
        overall, error = "", None
        if brief["verdicts"]:
            try:
                report = await self.deps.steps.run(
                    "critic",
                    brief,
                    self._scope(state, "critic"),
                    fake=lambda: fakes.critic(brief),
                )
                reviews = {r.obligation_id: r.model_dump(mode="json") for r in report.reviews}  # type: ignore[attr-defined]
                overall = report.overall  # type: ignore[attr-defined]
            except GraphBubbleUp:
                raise
            except Exception as exc:
                error = type(exc).__name__
        adjusted = []
        for v in verdicts:
            review = reviews.get(v["obligation_id"])
            new = dict(v)
            if v["verdict"] == "not_assessable_by_testing":
                new["critic"] = {"upheld": True, "objection": "", "grounds": "documentary"}
            elif review is None:
                new["critic"] = {
                    "upheld": True,
                    "objection": "",
                    "grounds": f"not reviewed by the critic{f' ({error})' if error else ''}",
                }
            else:
                new["critic"] = {
                    "upheld": bool(review["upheld"]),
                    "objection": review.get("objection") or "",
                    "grounds": review.get("grounds") or "",
                }
                if not review["upheld"]:
                    new["verdict_before_critic"] = v["verdict"]
                    new["verdict"] = review.get("adjusted_verdict") or "inconclusive"
                    new["needs_human"] = True
            adjusted.append(new)
        art_id = await self._artifact(
            state,
            "critic",
            {
                "reviews": list(reviews.values()),
                "overall": overall or f"The critic did not run ({error})."
                if error
                else overall or "No tested verdict to review.",
                "overturned": [
                    v["obligation_id"] for v in adjusted if "verdict_before_critic" in v
                ],
                "unreviewed": [
                    v["obligation_id"]
                    for v in verdicts
                    if v["verdict"] != "not_assessable_by_testing"
                    and v["obligation_id"] not in reviews
                ],
                "error": error,
            },
        )
        self._finish("critic")
        return {
            **out,
            "verdicts": adjusted,
            "critic": {"overall": overall, "reviews": list(reviews.values()), "error": error},
            "artifacts": {"critic": art_id},
        }

    async def seal(self, state: AuditState) -> dict[str, Any]:
        """One sealed verdict per obligation in scope: severity, gap ids, hash chain, stored."""
        out = await self._start(state, "seal")
        kb = state.get("kb_version")
        today = datetime.fromisoformat(self.deps.today()).date()
        inference = state.get("inference") or {}
        dataset = state.get("dataset") or {}
        res_art = (state.get("artifacts") or {}).get("test_result")
        proposed = []
        for v in state.get("verdicts") or []:
            entry = v["entry"]
            refs: list[dict[str, Any]] = []
            if v.get("rows"):
                if inference.get("predictions_sha256"):
                    refs.append(
                        {
                            "path": f"{INFERENCE_REL}/predictions.parquet",
                            "sha256": inference["predictions_sha256"],
                            "mlflow_run_id": inference.get("mlflow_run_id"),
                        }
                    )
                if dataset.get("sha256"):
                    refs.append(
                        {"path": f"{DATA_REL}/dataset.parquet", "sha256": dataset["sha256"]}
                    )
                refs += [
                    {"path": f"mlflow:runs/{run}", "sha256": None, "mlflow_run_id": run}
                    for run in v.get("mlflow_runs") or []
                ]
            for present in (v.get("dossier_evidence") or {}).get("present") or []:
                refs.append({"path": present.split(": ", 1)[-1], "sha256": None})
            proposed.append(
                {
                    "obligation_id": v["obligation_id"],
                    "verdict": v["verdict"],
                    "severity": severity(
                        v["verdict"], entry, today, doc_gap=bool(v.get("documentation_gap"))
                    ),
                    "metrics_ref": {"artifact_id": res_art, "rows": v.get("rows") or []}
                    if v.get("rows")
                    else None,
                    "evidence_refs": refs,
                    "citations": v.get("citations") or [],
                    "kb_version": kb,
                    "reasoning": v.get("reasoning"),
                    "counter_arguments": v.get("counter_arguments") or [],
                    "would_change_if": v.get("would_change_if") or [],
                    "judges": v.get("judges") or {},
                    "critic": v.get("critic") or {},
                    # Not hashed, kept by the backend in ``data``:
                    "article": entry.get("article"),
                    "title": entry.get("summary"),
                    "in_force_date": entry.get("in_force_date"),
                    "verification_mode": entry.get("verification_mode"),
                    "needs_human": bool(v.get("needs_human")),
                    "documentation_gap": bool(v.get("documentation_gap")),
                    "dossier_evidence": v.get("dossier_evidence"),
                    "verdict_before_critic": v.get("verdict_before_critic"),
                    "citation_problems": v.get("citation_problems") or [],
                }
            )
        sealed = seal_findings(proposed, str(state.get("system_id")))
        problems = coverage_problems(state.get("scope") or [], sealed)
        if problems:
            raise StepFailed(f"Coverage invariant broken: {'; '.join(problems[:5])}")
        stored, endpoint = 0, True
        backend = self._backend(state)
        for finding in sealed:
            if not endpoint:
                break
            try:
                await backend.seal_finding(finding)
                stored += 1
            except PipelineHTTPError as exc:
                if exc.status in (404, 405):
                    endpoint = False
                    logger.warning("pipeline_findings_endpoint_missing", "No findings endpoint")
                else:
                    raise
        ids = {}
        for n, finding in enumerate(sealed, start=1):
            ids[finding["obligation_id"]] = await self._artifact(
                state,
                "finding",
                legacy_finding(finding, n, (state.get("test_results") or {}).get("tests") or []),
                name=finding["obligation_id"],
                file_refs=[r["path"] for r in finding["evidence_refs"] if r.get("path")],
            )
        art_id = await self._artifact(
            state,
            "seal",
            {
                "count": len(sealed),
                "stored_in_findings_table": stored,
                "head_hash": sealed[-1]["hash"] if sealed else None,
                "gaps": [
                    {k: f.get(k) for k in ("gap_id", "obligation_id", "verdict", "severity")}
                    for f in sealed
                    if f.get("gap_id")
                ],
                "coverage": {"in_scope": len(state.get("scope") or []), "sealed": len(sealed)},
            },
        )
        self._finish("seal")
        return {
            **out,
            "sealed": sealed,
            "findings": [legacy_finding(f, n, []) for n, f in enumerate(sealed, start=1)],
            "artifacts": {"finding": ids, "seal": art_id},
        }

    async def report(self, state: AuditState) -> dict[str, Any]:
        out = await self._start(state, "report")
        sealed = state.get("sealed") or []
        card = (state.get("dataset") or {}).get("data_card") or {}
        brief = {
            "audit_id": state["audit_id"],
            "system_id": state.get("system_id"),
            "target": state.get("target"),
            "pins": state.get("pins"),
            "dataset": {
                "dataset_id": card.get("dataset_id"),
                "sha256": (state.get("dataset") or {}).get("sha256"),
                "predictions_sha256": (state.get("inference") or {}).get("predictions_sha256"),
                "inference_mlflow_run": (state.get("inference") or {}).get("mlflow_run_id"),
            },
            "findings": [
                {
                    k: f.get(k)
                    for k in (
                        "obligation_id",
                        "article",
                        "verdict",
                        "severity",
                        "gap_id",
                        "reasoning",
                        "counter_arguments",
                        "needs_human",
                        "dossier_evidence",
                    )
                }
                for f in sealed
            ],
            "critic_overall": (state.get("critic") or {}).get("overall"),
            "analysis": {
                k: (state.get("analysis") or {}).get(k)
                for k in ("observations", "mismatches", "summary")
            },
            "gates": state.get("gates"),
        }
        try:
            result = await self.deps.steps.run(
                "report",
                brief,
                self._scope(state, "report"),
                fake=lambda: fakes.report(dict(state)),
            )
            data = result.model_dump(mode="json")
        except GraphBubbleUp:
            raise
        except Exception as exc:  # the audit still ends with a report (plan 01 P8)
            data = fakes.report(dict(state)).model_dump(mode="json")
            data["writer_error"] = type(exc).__name__
        data["engineer_markdown"] = (
            f"{data.get('engineer_markdown') or ''}\n\n{report_appendix(state)}"
        )
        data["sealed_head_hash"] = sealed[-1]["hash"] if sealed else None
        art_id = await self._artifact(state, "report", data)
        self._finish("report")
        return {**out, "report": data, "artifacts": {"report": art_id}}

    async def finalize(self, state: AuditState) -> dict[str, Any]:
        status = "done"
        verdicts: dict[str, int] = {}
        for f in state.get("sealed") or []:
            verdicts[f.get("verdict", "?")] = verdicts.get(f.get("verdict", "?"), 0) + 1
        try:
            await self._backend(state).patch(
                stage="report",
                status=status,
                data={
                    "verdicts": verdicts,
                    "gaps": sum(1 for f in state.get("sealed") or [] if f.get("gap_id")),
                    "finishedAt": datetime.now(UTC).isoformat(),
                },
            )
        except Exception:
            logger.warning("pipeline_stage_patch_failed", "Final patch failed")
        if state.get("change_id") and self.deps.delta is not None:
            try:  # a regulation-change re-run: write its delta report (survives restarts)
                await self.deps.delta(state["audit_id"])
            except Exception:
                logger.warning("pipeline_delta_failed", "Delta report failed")
        return {"status": status}

    async def stop(self, state: AuditState) -> dict[str, Any]:
        """A gate's redo budget is spent: the audit ends as rejected, with an incomplete report."""
        await self._incomplete_report(
            state, "stop", "A gate's redo budget is spent: the reviewer rejected the step."
        )
        try:
            await self._backend(state).patch(
                status="failed",
                data={"outcome": "rejected", "stoppedAt": datetime.now(UTC).isoformat()},
            )
        except Exception:
            logger.warning("pipeline_stage_patch_failed", "Stop patch failed")
        return {"status": "rejected"}

    # ------------------------------------------------------------ failure (plan 01 §6.3)
    async def _incomplete_report(self, state: AuditState, stage: str, reason: str) -> None:
        """Every audit ends with a report: what ran, what did not, why, partial results."""
        try:
            artifacts = state.get("artifacts") or {}
            done = [n for n in NODE_ORDER if _ran(n, state)]
            not_run = [n for n in NODE_ORDER if n not in done and n != stage]
            tests = (state.get("test_results") or {}).get("tests") or []
            lines = [
                f"# Incomplete audit {state['audit_id']} ({state.get('system_id')})",
                "",
                f"The audit stopped at **{stage}**: {reason}",
                "",
                "## Pins",
                "```yaml",
                dumps_yaml(state.get("pins") or {"kb_version": state.get("kb_version")}).strip(),
                "```",
                "",
                f"## What ran\n{', '.join(done) or 'nothing'}",
                f"\n## What did not run\n{', '.join(not_run) or 'nothing'}",
                "\n## Partial results",
                f"- Obligations in scope: {len(state.get('scope') or [])}",
                f"- Scenarios: {len((state.get('scenarios') or {}).get('scenarios') or [])}",
                f"- Dataset sha256: {(state.get('dataset') or {}).get('sha256') or 'none'}",
                "- Predictions sha256: "
                f"{(state.get('inference') or {}).get('predictions_sha256') or 'none'}",
                f"- Metric rows: {len(tests)}",
                "",
                "No verdict is given for an obligation that was not tested. "
                "Retry resumes from the failed step with the same pins.",
            ]
            await self._artifact(
                state,
                "report",
                {
                    "incomplete": True,
                    "failed_stage": stage,
                    "reason": reason,
                    "ran": done,
                    "not_run": not_run,
                    "artifacts": artifacts,
                    "engineer_markdown": "\n".join(lines),
                    "management": {
                        "headline": f"Incomplete audit: stopped at {stage}.",
                        "traffic_lights": [],
                        "decisions_needed": ["Retry the audit or fix the failing step."],
                        "next_steps": [reason[:300]],
                    },
                },
            )
            await self._backend(state).patch(
                stage=stage,
                status="failed",
                data={"failure": {"stage": stage, "reason": reason[:1000]}, "incomplete": True},
            )
        except Exception:
            logger.warning("pipeline_incomplete_report_failed", "Incomplete report not written")

    def _guard(self, name: str, node: Callable[[AuditState], Any]) -> Callable[..., Any]:
        """Any unrecoverable node failure writes the incomplete report, then re-raises
        (the checkpoint stays on the failed node, so ``retry`` resumes there)."""

        async def guarded(state: AuditState) -> dict[str, Any]:
            try:
                return await node(state)
            except GraphBubbleUp:
                raise
            except Exception as exc:
                reason = getattr(exc, "public_message", None) or f"{type(exc).__name__}: {exc}"
                logger.warning(
                    "pipeline_node_failed",
                    "Pipeline node failed",
                    stage=name,
                    failure_reason=type(exc).__name__,
                )
                await self._incomplete_report(state, name, str(reason)[:1500])
                raise

        guarded.__name__ = name
        return guarded

    # ---------------------------------------------------------------- graph
    def build(self, checkpointer: Any = None) -> Any:
        graph = StateGraph(AuditState)
        for name in NODE_ORDER:
            graph.add_node(name, self._guard(name, getattr(self, name)))
        graph.add_node("stop", self.stop)
        graph.add_edge(START, "load_context")
        graph.add_edge("load_context", "pin")
        graph.add_edge("pin", "ground_obligations")
        graph.add_edge("ground_obligations", "profile_model")
        graph.add_edge("profile_model", "plan_scenarios")
        graph.add_edge("plan_scenarios", "analyse_scenarios")
        graph.add_conditional_edges(
            "analyse_scenarios", _route, {"redo": "plan_scenarios", "next": "gate_scenarios"}
        )
        graph.add_conditional_edges(
            "gate_scenarios",
            _route,
            {"redo": "plan_scenarios", "next": "find_public_data", "stop": "stop"},
        )
        graph.add_edge("find_public_data", "gate_public_data")
        graph.add_conditional_edges(
            "gate_public_data", _route, {"next": "draft_spec", "plan": "plan_scenarios"}
        )
        graph.add_edge("draft_spec", "generate_data")
        graph.add_conditional_edges(
            "generate_data", _route, {"redo": "draft_spec", "next": "analyse_datasets"}
        )
        graph.add_conditional_edges(
            "analyse_datasets", _route, {"redo": "draft_spec", "next": "gate_datasets"}
        )
        graph.add_conditional_edges(
            "gate_datasets",
            _route,
            {"redo": "draft_spec", "next": "run_inference", "stop": "stop"},
        )
        graph.add_edge("run_inference", "analyse_results")
        graph.add_edge("analyse_results", "assess_obligations")
        graph.add_edge("assess_obligations", "critic")
        graph.add_edge("critic", "seal")
        graph.add_edge("seal", "report")
        graph.add_edge("report", "finalize")
        graph.add_edge("finalize", END)
        graph.add_edge("stop", END)
        return graph.compile(checkpointer=checkpointer)


def _route(state: AuditState) -> str:
    return state.get("route") or "next"


#: Which state key shows a node has run (for the incomplete report).
_RAN_BY = {
    "load_context": "card",
    "pin": "pins",
    "ground_obligations": "scope",
    "profile_model": "profile",
    "plan_scenarios": "scenarios",
    "analyse_scenarios": "scenario_analysis",
    "draft_spec": "spec",
    "generate_data": "dataset",
    "analyse_datasets": "dataset_analysis",
    "run_inference": "inference",
    "analyse_results": "test_results",
    "assess_obligations": "verdicts",
    "critic": "critic",
    "seal": "sealed",
    "report": "report",
}


def _ran(node: str, state: AuditState) -> bool:
    if node.startswith("gate_"):
        return node.removeprefix("gate_") in (state.get("gates") or {})
    if node == "find_public_data":
        return bool(state.get("public_data"))
    key = _RAN_BY.get(node)
    return bool(key and state.get(key))  # type: ignore[misc]


def _row_digest(row: dict[str, Any]) -> dict[str, Any]:
    thr = row.get("threshold") or {}
    return {
        "id": row.get("id"),
        "metric": row.get("metric"),
        "value": row.get("value"),
        "ci95": row.get("ci95"),
        "n": row.get("n"),
        "threshold": f"{thr.get('op')} {thr.get('value')}" if thr.get("op") else None,
        "threshold_source": row.get("threshold_source"),
        "status": row.get("status"),
        "mlflow_run_id": row.get("mlflow_run_id"),
    }


def headline_mismatches(
    claims: list[dict[str, Any]], results: dict[str, Any]
) -> list[dict[str, Any]]:
    """The analyst's recomputed headline numbers vs synthkit's (code flags any mismatch)."""
    rows = results.get("tests") or []
    out = []
    for c in claims:
        row = next(
            (
                r
                for r in rows
                if r.get("metric") == c.get("metric")
                and c.get("test_id") in (r.get("test_id"), r.get("id"))
            ),
            None,
        )
        if row is None:
            out.append({**c, "problem": "no such metric in the synthkit results"})
        elif (
            c.get("value") is not None
            and row.get("value") is not None
            and abs(float(c["value"]) - float(row["value"])) > max(1e-3, 0.01 * abs(row["value"]))
        ):
            out.append({**c, "synthkit": row["value"], "problem": "value differs"})
    return out


def legacy_finding(finding: dict[str, Any], n: int, tests: list[dict[str, Any]]) -> dict[str, Any]:
    """A sealed finding in the ``finding`` artifact shape the UI and impact index read."""
    rows = {t.get("id"): t for t in tests}
    entry_reqs = (finding.get("metrics_ref") or {}).get("rows") or []
    evidence = []
    for rid in entry_reqs:
        t = rows.get(rid)
        if not t:
            continue
        thr = t.get("threshold") or {}
        evidence.append(
            {
                "test_id": t.get("id"),
                "metric": t.get("metric"),
                "value": t.get("value"),
                "ci95": t.get("ci95"),
                "threshold": f"{thr.get('op')} {thr.get('value')}" if thr.get("op") else None,
                "threshold_source": thr.get("source") or str(t.get("threshold_source")),
                "mlflow_run_id": t.get("mlflow_run_id"),
            }
        )
    judges = finding.get("judges") or {}
    iris = judges.get("iris") or {}
    return {
        "id": finding.get("gap_id") or f"F-{n:02d}",
        "requirement": finding["obligation_id"],
        "obligation_id": finding["obligation_id"],
        "article": finding.get("article"),
        "title": finding.get("title") or finding["obligation_id"],
        "verdict": LEGACY_VERDICT.get(finding["verdict"], "inconclusive"),
        "obligation_verdict": finding["verdict"],
        "severity": finding.get("severity"),
        "gap_id": finding.get("gap_id"),
        "confidence": float(iris.get("confidence") or 0.6),
        "reasoning": finding.get("reasoning"),
        "evidence": evidence[:12],
        "counter_evidence": finding.get("counter_arguments") or [],
        "would_change_if": finding.get("would_change_if") or [],
        "citations": finding.get("citations") or [],
        "limitations": [],
        "judges": judges,
        "critic": finding.get("critic"),
        "needs_human": finding.get("needs_human"),
        "evidence_refs": finding.get("evidence_refs"),
        "hash": finding.get("hash"),
        "prev_hash": finding.get("prev_hash"),
        "sealed": True,
    }


def report_appendix(state: AuditState) -> str:
    """The code-written report sections: pins, evidence register, gap list (plan 01 §8)."""
    sealed = state.get("sealed") or []
    lines = ["## Pins", "```yaml", dumps_yaml(state.get("pins") or {}).strip(), "```", ""]
    lines += [
        "## Evidence register",
        "| Obligation | Verdict | Evidence (sha256) | MLflow runs | Citations (kb) | Hash |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for f in sealed:
        files = "; ".join(
            f"{r['path']} ({str(r.get('sha256'))[:12]})"
            for r in f.get("evidence_refs") or []
            if r.get("sha256")
        )
        runs = ", ".join(
            str(r["mlflow_run_id"])[:12]
            for r in f.get("evidence_refs") or []
            if r.get("mlflow_run_id")
        )
        cites = ", ".join(
            f"{c.get('provision_id')} ({c.get('kb_version')})" for c in f.get("citations") or []
        )
        lines.append(
            f"| {f['obligation_id']} | {f['verdict']} | {files or '-'} | {runs or '-'} | "
            f"{cites or '-'} | {str(f.get('hash'))[:12]} |"
        )
    gaps = [f for f in sealed if f.get("gap_id")]
    lines += [
        "",
        "## Gap list",
        "| Gap | Obligation | Verdict | Severity | In force | Remediation |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for f in gaps:
        fix = (f.get("would_change_if") or ["Review with the AI Officer."])[0]
        lines.append(
            f"| {f['gap_id']} | {f['obligation_id']} | {f['verdict']} | {f.get('severity')} | "
            f"{f.get('in_force_date') or '-'} | {str(fix)[:160]} |"
        )
    if not gaps:
        lines.append("| - | none | - | - | - | - |")
    return "\n".join(lines)


async def resolve_model_version(access: dict[str, Any]) -> dict[str, Any]:
    """``models:/<name>@<alias>`` -> the concrete registered version (MLflow REST)."""
    uri = str(access.get("uri") or "")
    out: dict[str, Any] = {"type": access.get("type"), "uri": uri or access.get("url")}
    match = _MODEL_URI.match(uri)
    if not match:
        return out
    name, alias, version = match.group(1), match.group(2), match.group(3)
    out.update(name=name, alias=alias, version=version)
    if version:
        return out
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(
                f"{MLFLOW_URL}/api/2.0/mlflow/registered-models/alias",
                params={"name": name, "alias": alias},
            )
        body = response.json().get("model_version") or {} if response.status_code < 400 else {}
        out.update(version=body.get("version"), run_id=body.get("run_id"))
        if not body:
            out["error"] = f"mlflow answered {response.status_code}"
    except Exception as exc:
        out["error"] = f"mlflow unreachable: {type(exc).__name__}"
    return out


#: The nodes in pipeline order (gates included).
NODE_ORDER = (
    "load_context",
    "pin",
    "ground_obligations",
    "profile_model",
    "plan_scenarios",
    "analyse_scenarios",
    "gate_scenarios",
    "find_public_data",
    "gate_public_data",
    "draft_spec",
    "generate_data",
    "analyse_datasets",
    "gate_datasets",
    "run_inference",
    "analyse_results",
    "assess_obligations",
    "critic",
    "seal",
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
