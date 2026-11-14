"""brand.json is the source of truth: the frontend's generated tokens must match it."""

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FRONTEND_TOKENS = ROOT / "product" / "frontend" / "src" / "styles" / "theme" / "tokens.css"


def _export_tokens():
    path = ROOT / "branding" / "export_tokens.py"
    spec = importlib.util.spec_from_file_location("export_tokens", path)
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


def _luminance(hex_color: str) -> float:
    h = hex_color.lstrip("#")
    channels = [int(h[i : i + 2], 16) / 255 for i in (0, 2, 4)]
    lin = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def _contrast(a: str, b: str) -> float:
    hi, lo = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


# (foreground, background, WCAG AA minimum): 4.5 for text, 3 for UI parts and the logo.
CONTRAST_PAIRS = [
    *(
        (fg, bg, 4.5)
        for fg in ("text", "muted")
        for bg in ("background", "surface", "surface_muted")
    ),
    *(
        (fg, bg, 4.5)
        for fg in ("primary", "accent", "success", "warning", "danger", "info")
        for bg in ("background", "surface")
    ),
    *(
        (f"{role}_foreground", role, 4.5)
        for role in ("primary", "accent", "success", "warning", "danger", "info")
    ),
    *(
        (fg, bg, 3.0)
        for fg in ("ring", "logo_lex", "logo_terra")
        for bg in ("background", "surface")
    ),
]


def test_palette_meets_wcag_aa() -> None:
    colors = json.loads((ROOT / "branding" / "brand.json").read_text(encoding="utf-8"))["colors"]
    failures = [
        f"{mode}: {fg} on {bg} = {_contrast(c[fg], c[bg]):.2f} < {need}"
        for mode, c in colors.items()
        for fg, bg, need in CONTRAST_PAIRS
        if _contrast(c[fg], c[bg]) < need
    ]
    assert not failures, failures
