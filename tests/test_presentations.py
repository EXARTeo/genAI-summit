"""The deck builder and token exporter work against the real brand file."""

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest
from pptx import Presentation

ROOT = Path(__file__).resolve().parent.parent


def _load(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module  # dataclasses need the module registered
    spec.loader.exec_module(module)
    return module


build = _load("deck_build", ROOT / "presentations" / "build.py")
export_tokens = _load("export_tokens", ROOT / "branding" / "export_tokens.py")


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_example_deck_builds(tmp_path: Path, theme: str) -> None:
    deck_file = ROOT / "presentations" / "decks" / "example" / "deck.yaml"
    out = build.build_deck(deck_file, tmp_path / "example.pptx", theme)

    prs = Presentation(str(out))
    expected = len(build.load_deck(deck_file)["slides"])
    assert len(prs.slides) == expected
    assert prs.slides[0].has_notes_slide


def test_every_deck_in_repo_is_valid() -> None:
    for deck_file in (ROOT / "presentations" / "decks").glob("*/deck.yaml"):
        build.load_deck(deck_file)


def test_unknown_layout_is_rejected(tmp_path: Path) -> None:
    deck_file = tmp_path / "deck.yaml"
    deck_file.write_text("slides:\n  - layout: nope\n    title: x\n", encoding="utf-8")
    with pytest.raises(build.DeckError, match="unknown layout"):
        build.load_deck(deck_file)


def test_missing_required_field_is_rejected(tmp_path: Path) -> None:
    deck_file = tmp_path / "deck.yaml"
    deck_file.write_text("slides:\n  - layout: bullets\n    title: x\n", encoding="utf-8")
    with pytest.raises(build.DeckError, match="missing"):
        build.load_deck(deck_file)


def test_brand_has_every_colour_token_in_both_themes() -> None:
    for mode in ("light", "dark"):
        build.load_theme(mode)  # raises DeckError if a token is missing


def test_tokens_css_has_light_and_dark(tmp_path: Path) -> None:
    out = tmp_path / "tokens.css"
    assert export_tokens.main(["--out", str(out)]) == 0
    css = out.read_text(encoding="utf-8")
    assert "--color-primary:" in css
    assert "--color-primary-foreground:" in css
    assert ':root[data-theme="dark"]' in css
    assert "prefers-color-scheme: dark" in css
