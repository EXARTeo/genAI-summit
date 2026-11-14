"""The derived corpus kept in git (``mnamon/reg-memory/corpus/``): requirements and
test templates (PDF §12.3). Loaded and validated into every kb release."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field

from core.settings import SERVICE_ROOT

CORPUS_DIR = SERVICE_ROOT / "corpus"
REQS_FILE = "requirements.yaml"
TTS_FILE = "test_templates.yaml"

Actor = Literal["provider", "deployer", "importer", "distributor", "authorised_representative"]
Testability = Literal["model_and_data_test", "documentation", "process"]


class AppliesIf(BaseModel):
    # Any of these risk classes (empty = any class).
    risk_class: list[str] = Field(default_factory=list)
    # Basis families (annex_iii, annex_i); empty = any basis.
    basis: list[str] = Field(default_factory=list)
    # The system must have at least one of these features (e.g. interacts_with_persons).
    features_any: list[str] = Field(default_factory=list)


class Requirement(BaseModel):
    id: str = Field(pattern=r"^REQ\.[A-Z]+\.[0-9A-Za-z_.]+\.[a-z0-9-]+$")
    source: str
    related: list[str] = Field(default_factory=list)
    actor: Actor
    applies_if: AppliesIf = Field(default_factory=AppliesIf)
    modality: Literal["shall", "shall_not", "should", "may"]
    obligation: str
    testability: Testability
    test_templates: list[str] = Field(default_factory=list)
    notes: str = ""
    provenance: str = "drafted_by_agent"
    review: Literal["pending", "accepted", "rejected"] = "pending"


class TestTemplate(BaseModel):
    id: str = Field(pattern=r"^TT\.[a-z_]+\.[a-z_]+$")
    title: str
    supports: list[str]
    needs: list[str] = Field(default_factory=list)
    data_strategy: str
    metric: str
    pass_criterion: str = ""
    limitations: list[str] = Field(default_factory=list)
    provenance: str = "drafted_by_agent"
    review: Literal["pending", "accepted", "rejected"] = "pending"


def _load(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return yaml.safe_load(path.read_text(encoding="utf-8")) or []


def load_corpus(corpus_dir: Path = CORPUS_DIR) -> tuple[list[dict], list[dict]]:
    """``(requirements, test_templates)`` as validated plain dicts."""
    reqs = [Requirement.model_validate(r).model_dump() for r in _load(corpus_dir / REQS_FILE)]
    tts = [TestTemplate.model_validate(t).model_dump() for t in _load(corpus_dir / TTS_FILE)]
    return reqs, tts


def check_corpus(reqs: list[dict], tts: list[dict], provision_ids: set[str]) -> list[str]:
    """Cross-reference warnings (unknown provisions, templates, requirements)."""
    warnings: list[str] = []
    req_ids = {r["id"] for r in reqs}
    tt_ids = {t["id"] for t in tts}
    for r in reqs:
        for pid in [r["source"], *r["related"]]:
            if pid not in provision_ids:
                warnings.append(f"{r['id']}: unknown provision {pid}")
        for tid in r["test_templates"]:
            if tid not in tt_ids:
                warnings.append(f"{r['id']}: unknown test template {tid}")
    for t in tts:
        for rid in t["supports"]:
            if rid not in req_ids:
                warnings.append(f"{t['id']}: supports unknown requirement {rid}")
    return warnings
