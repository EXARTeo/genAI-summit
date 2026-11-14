"""Repo-level checks: required files exist, scripts come in pairs, YAML parses."""

from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
SKIP_DIRS = {".git", ".venv", "node_modules"}

REQUIRED_FILES = [
    "README.md",
    "LICENSE",
    ".gitignore",
    ".env.example",
    "CHANGELOG.md",
    "CONTRIBUTING.md",
    "SECURITY.md",
    ".github/workflows/ci.yml",
]


def _yaml_files() -> list[Path]:
    return sorted(
        p
        for pattern in ("*.yml", "*.yaml")
        for p in ROOT.rglob(pattern)
        if not SKIP_DIRS.intersection(p.relative_to(ROOT).parts)
    )


@pytest.mark.parametrize("name", REQUIRED_FILES)
def test_required_file_exists(name: str) -> None:
    assert (ROOT / name).is_file(), f"missing {name}"


def test_every_script_has_bash_and_powershell_versions() -> None:
    scripts = ROOT / "scripts"
    sh = {p.stem for p in scripts.glob("*.sh")}
    ps1 = {p.stem for p in scripts.glob("*.ps1")}
    assert sh == ps1, f"unpaired scripts: {sorted(sh ^ ps1)}"


@pytest.mark.parametrize("path", _yaml_files(), ids=lambda p: p.relative_to(ROOT).as_posix())
def test_yaml_parses(path: Path) -> None:
    with path.open(encoding="utf-8") as fh:
        list(yaml.safe_load_all(fh))
