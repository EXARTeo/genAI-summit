"""What a case builder hands to the registry: one ``ModelSpec`` per registered model."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd
import yaml


@dataclass
class DatasetSpec:
    frame: pd.DataFrame
    name: str
    context: str  # training | evaluation | edge_cases
    targets: str | None = None


@dataclass
class ModelSpec:
    name: str  # registered model name (a contract with the model gateway)
    plugin: str  # plugin folder under cases/<SYS>/plugins/
    python_model: Any
    input_example: pd.DataFrame
    output_example: pd.DataFrame
    metrics: dict[str, float]
    params: dict[str, Any] = field(default_factory=dict)
    datasets: list[DatasetSpec] = field(default_factory=list)
    artifacts: dict[str, str] = field(default_factory=dict)  # file name -> text
    description: str = ""


@dataclass
class CaseResult:
    system_id: str
    models: list[ModelSpec]


def load_yaml(path: Path) -> dict[str, Any]:
    return yaml.safe_load(Path(path).read_text(encoding="utf-8"))


def system_card(case_dir: Path) -> dict[str, Any]:
    return load_yaml(case_dir / "system-card.yaml")


def generation_settings(case_dir: Path, plugin: str) -> dict[str, Any]:
    """``scenarios.generation`` of a plugin (seed and training-set size)."""
    card = load_yaml(case_dir / "plugins" / plugin / "plugin.yaml")
    return card.get("scenarios", {}).get("generation", {})
