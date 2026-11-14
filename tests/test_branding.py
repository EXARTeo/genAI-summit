"""brand.json is the source of truth: the frontend's generated tokens must match it."""

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FRONTEND_TOKENS = ROOT / "product" / "frontend" / "src" / "styles" / "theme" / "tokens.css"


def _export_tokens():
    spec = importlib.util.spec_from_file_location("export_tokens", ROOT / "branding" / "export_tokens.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_light_and_dark_have_the_same_tokens() -> None:
    colors = json.loads((ROOT / "branding" / "brand.json").read_text(encoding="utf-8"))["colors"]
    assert set(colors["light"]) == set(colors["dark"])


def test_rgb_channels() -> None:
    assert _export_tokens()._channels("#3B37C8") == "59 55 200"


def test_frontend_tokens_are_up_to_date() -> None:
    mod = _export_tokens()
    brand = json.loads((ROOT / "branding" / "brand.json").read_text(encoding="utf-8"))
    expected = mod.render_css(brand)
    actual = FRONTEND_TOKENS.read_text(encoding="utf-8")
    assert actual == expected, "run: uv run python branding/export_tokens.py --frontend"
