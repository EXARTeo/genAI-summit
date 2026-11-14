"""Stand-ins for the audit pipeline's dependencies (no network, no Postgres, no model).

* :class:`FakeBackend`: the backend's internal API over an in-memory SYS-001
  folder (the real seed case files), recording artifacts and stage patches.
* :class:`FakeRegMemory`: two requirements and their templates.
* :class:`FakeSandbox`: answers each synthkit command with a plausible file.
* :class:`FakeMemory`: the ``system_memories`` table in memory.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from pipeline.clients import ExecResult
from pipeline.graph import AuditPipeline, PipelineDeps
from pipeline.steps import StepRunner

from harness.memory.entries import MemoryRecord

REPO = Path(__file__).resolve().parents[2]
CASE = REPO / "product" / "mlflow-seed" / "cases" / "SYS-001"
SYSTEM_ID = "SYS-001"
AUDIT_ID = "AUD-1"
KB = "2026.11.14-1"


def seed_files() -> dict[str, str]:
    out = {}
    for path in sorted(CASE.rglob("*")):
        rel = path.relative_to(CASE).as_posix()
        if path.is_file() and not rel.startswith("_"):
            out[rel] = path.read_text(encoding="utf-8")
    return out


class FakeBackend:
    def __init__(self, files: dict[str, str] | None = None) -> None:
        self.files = files if files is not None else seed_files()
        self.artifacts: list[dict[str, Any]] = []
        self.patches: list[dict[str, Any]] = []
        self.reads: list[str] = []
        self.audit_data: dict[str, Any] = {"dossier_version": 3}

    async def audit(self) -> dict[str, Any]:
        return {
            "audit": {"id": AUDIT_ID, "data": self.audit_data, "artifacts": self.artifacts},
            "system": {"id": SYSTEM_ID, "data": {}},
        }

    async def patch(self, *, stage=None, status=None, data=None) -> dict[str, Any]:
        self.patches.append({"stage": stage, "status": status, "data": data})
        return {}

    async def tree(self, prefix: str | None = None) -> list[dict[str, Any]]:
        return [
            {"path": p, "version": 1} for p in self.files if prefix is None or p.startswith(prefix)
        ]

    async def read(self, path: str) -> str | None:
        self.reads.append(path)
        return self.files.get(path)

    async def write_artifact(self, kind, data, *, name="main", file_refs=None, status="proposed"):
        art = {
            "id": f"art-{len(self.artifacts) + 1}",
            "kind": kind,
            "name": name,
            "version": 1 + sum(a["kind"] == kind and a["name"] == name for a in self.artifacts),
            "data": json.loads(json.dumps(data, default=str)),
            "fileRefs": file_refs or [],
        }
        self.artifacts.append(art)
        return art

    def kinds(self) -> list[str]:
        return [a["kind"] for a in self.artifacts]

    def stages(self) -> list[str]:
        return [p["stage"] for p in self.patches if p["stage"]]


REQUIREMENTS = [
    {
        "id": "REQ.AIA.10.2.f.bias-examination",
        "source": "AIA.10.2.f",
        "testability": "model_and_data_test",
        "test_templates": ["TT.fairness.group_metrics", "TT.fairness.counterfactual"],
    },
    {
        "id": "REQ.AIA.15.1.accuracy-consistency",
        "source": "AIA.15.1",
        "testability": "model_and_data_test",
        "test_templates": ["TT.robustness.perturbation"],
    },
    {
        "id": "REQ.AIA.11.1.technical-documentation",
        "source": "AIA.11.1",
        "testability": "documentation",
        "test_templates": [],
    },
]


class FakeRegMemory:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    async def active_kb_version(self) -> str:
        return KB

    async def requirements(self, **params: Any) -> dict[str, Any]:
        self.calls.append(("requirements", params))
        return {"kb_version": KB, "items": REQUIREMENTS}

    async def test_templates(self, kb_version=None) -> list[dict[str, Any]]:
        return [{"id": "TT.fairness.counterfactual", "metric": "flip_rate"}]

    async def provision(self, provision_id, kb_version=None) -> dict[str, Any]:
        return {"id": provision_id, "title": "t", "text": "text", "kb_version": kb_version}

    async def search_provisions(self, **params) -> list[dict[str, Any]]:
        return []

    async def change(self, change_id: str) -> dict[str, Any]:
        return {}


PROFILE = {
    "notes": ["postcode_region moves the output and stands in for nationality"],
    "sensitivity": {
        "postcode_region": {"moves_output": True, "mean_range": 0.12},
        "career_gap_months": {"moves_output": True, "mean_range": 0.08},
        "sex": {"moves_output": False, "mean_range": 0.0},
    },
}


@dataclass
class FakeSandbox:
    """Answers synthkit commands; ``fail`` maps a subcommand to a failing ExecResult."""

    available: bool = True
    commands: list[str] = field(default_factory=list)
    files_seen: list[dict[str, Any]] = field(default_factory=list)
    scenario_missing: list[dict[str, str]] = field(default_factory=list)
    fail: dict[str, ExecResult] = field(default_factory=dict)
    analyze_overall: str = "warn"
    results: dict[str, Any] | None = None

    async def run(self, command: str, files: dict[str, Any], *, timeout=None) -> ExecResult:
        self.commands.append(command)
        self.files_seen.append(dict(files))
        for key, result in self.fail.items():
            if f"synthkit {key}" in command:
                return result
        if "synthkit run-tests" in command:
            plan = yaml.safe_load(files["test-plan.yaml"])
            results = self.results or {
                "system": "SYS-001",
                "summary": {"pass": 1, "fail": 1},
                "results": [
                    row
                    for t in plan["tests"]
                    for row in (
                        [
                            {
                                "id": f"{t['id']}/cf_flip_rate.nationality.causal",
                                "test_id": t["id"],
                                "template": t["template"],
                                "requirements": t["requirements"],
                                "metric": "cf_flip_rate.nationality.causal",
                                "value": 0.15,
                                "ci95": [0.11, 0.19],
                                "threshold": {
                                    "key": "counterfactual_flip_rate",
                                    "op": "<=",
                                    "value": 0.02,
                                },
                                "threshold_source": "org",
                                "status": "fail",
                                "mlflow_run_id": f"run-{t['id']}",
                            }
                        ]
                        if t["template"] == "TT.fairness.counterfactual"
                        else [
                            {
                                "id": f"{t['id']}/metric",
                                "test_id": t["id"],
                                "template": t["template"],
                                "requirements": t["requirements"],
                                "metric": "metric",
                                "value": 0.9,
                                "ci95": [0.85, 0.95],
                                "threshold": {
                                    "key": "selection_rate_ratio",
                                    "op": ">=",
                                    "value": 0.8,
                                },
                                "threshold_source": "org",
                                "status": "pass",
                                "mlflow_run_id": f"run-{t['id']}",
                            }
                        ]
                    )
                ],
            }
            return ExecResult(
                0, "", "", files={"results/test-results.json": json.dumps(results).encode()}
            )
        if "synthkit analyze" in command:
            analysis = {
                "overall": self.analyze_overall,
                "gates": {
                    "schema": {"status": "pass", "problems": []},
                    "coverage": {
                        "status": "fail" if self.analyze_overall == "fail" else "pass",
                        "problems": ["cell sex=female has 3 rows"]
                        if self.analyze_overall == "fail"
                        else [],
                    },
                },
                "twin_validity": {"causal": {"valid": 1.0}},
            }
            code = 1 if self.analyze_overall == "fail" else 0
            return ExecResult(
                code,
                "",
                "",
                files={
                    "dataset-analysis.json": json.dumps(analysis).encode(),
                    "dataset-analysis.md": b"# analysis",
                },
            )
        if "synthkit generate" in command:
            card = {"dataset_id": "ds-abc", "content_sha256": "sha-1", "limitations": ["synthetic"]}
            return ExecResult(
                0,
                "",
                "",
                files={
                    "DataCard.yaml": yaml.safe_dump(card).encode(),
                    "sample-rows.csv": b"a,b\n1,2\n",
                },
            )
        if "synthkit scenarios-check" in command:
            report = {
                "status": "gaps" if self.scenario_missing else "ok",
                "missing": self.scenario_missing,
                "scenarios": [],
            }
            return ExecResult(
                0,
                "",
                "",
                files={
                    "scenario-analysis.json": json.dumps(report).encode(),
                    "scenario-analysis.md": b"# check",
                },
            )
        if "synthkit profile" in command:
            return ExecResult(0, "", "", files={"model-profile.json": json.dumps(PROFILE).encode()})
        return ExecResult(127, "", "unknown command")


class FakeMemory:
    def __init__(self) -> None:
        self.rows: dict[tuple[str, str, str], MemoryRecord] = {}

    async def get(self, system_id, audit_id, name):
        return self.rows.get((system_id, audit_id, name))

    async def list_system(self, system_id):
        return [r for (s, _, _), r in self.rows.items() if s == system_id]

    async def count_system(self, system_id):
        return len(await self.list_system(system_id))

    async def upsert(self, record):
        self.rows[(record.system_id, record.audit_id, record.name)] = record
        return record

    async def delete(self, system_id, audit_id, name):
        return self.rows.pop((system_id, audit_id, name), None) is not None


@dataclass
class Harness:
    backend: FakeBackend
    regmem: FakeRegMemory
    sandbox: FakeSandbox
    memory: FakeMemory
    deps: PipelineDeps
    searches: list[tuple] = field(default_factory=list)


def make_harness(
    *,
    sandbox: FakeSandbox | None = None,
    steps: StepRunner | None = None,
    search_result: dict[str, Any] | None = None,
) -> Harness:
    backend = FakeBackend()
    regmem = FakeRegMemory()
    box = sandbox or FakeSandbox()
    memory = FakeMemory()
    searches: list[tuple] = []

    def search(audit_id, plugin, **kw):
        searches.append((audit_id, plugin))
        return search_result or {
            "results": [
                {
                    "artifact_id": "cand-1",
                    "candidates": [{"id": "hf:x", "score": 0.38}],
                    "recommendation": {"mode": "zero_shot"},
                }
            ]
        }

    def fetch(audit_id, candidate, plugin):
        return {
            "id": candidate,
            "slug": "openml-31",
            "folder": "datasets/public/openml-31/",
            "rows": 10,
        }

    deps = PipelineDeps(
        backend_factory=lambda aid: backend,
        regmem=regmem,  # type: ignore[arg-type]
        sandbox=box,  # type: ignore[arg-type]
        memory_store=memory,
        steps=steps or StepRunner(),
        public_search=search,
        public_fetch=fetch,
        run_id="run-1",
        thread_id="audit-AUD-1",
        trace_id="a" * 32,
        today=lambda: "2026-11-14",
    )
    return Harness(backend, regmem, box, memory, deps, searches)


def build_graph(harness: Harness, checkpointer: Any) -> Any:
    return AuditPipeline(harness.deps).build(checkpointer)
