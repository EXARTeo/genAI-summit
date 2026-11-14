"""Generate CSS variables from branding/brand.json.

Usage:
    uv run python branding/export_tokens.py              # writes branding/dist/tokens.css
    uv run python branding/export_tokens.py --frontend   # also writes the frontend copy
    uv run python branding/export_tokens.py --out x.css

Each colour token becomes two variables: ``--color-<name>`` (hex, for plain CSS)
and ``--rgb-<name>`` (space-separated channels, so Tailwind can apply opacity:
``rgb(var(--rgb-primary) / <alpha-value>)``).
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

BRANDING_DIR = Path(__file__).resolve().parent
BRAND_FILE = BRANDING_DIR / "brand.json"
DEFAULT_OUT = BRANDING_DIR / "dist" / "tokens.css"
FRONTEND_OUT = BRANDING_DIR.parent / "product" / "frontend" / "src" / "styles" / "theme" / "tokens.css"


def _var(name: str) -> str:
    return name.replace("_", "-")


def _channels(hex_color: str) -> str:
    h = hex_color.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    if len(h) != 6:
        raise ValueError(f"expected #RRGGBB, got {hex_color!r}")
    return " ".join(str(int(h[i : i + 2], 16)) for i in (0, 2, 4))


def _color_block(colors: dict[str, str], indent: str = "  ") -> str:
    lines = []
    for k, v in colors.items():
        lines.append(f"{indent}--color-{_var(k)}: {v};")
        lines.append(f"{indent}--rgb-{_var(k)}: {_channels(v)};")
    return "\n".join(lines)


def render_css(brand: dict[str, Any]) -> str:
    light, dark = brand["colors"]["light"], brand["colors"]["dark"]
    fonts = "\n".join(f"  --font-{_var(k)}: '{v}';" for k, v in brand["fonts"].items())
    return f"""/* Generated from branding/brand.json by branding/export_tokens.py. Do not edit. */

:root {{
{_color_block(light)}
{fonts}
  color-scheme: light;
}}

@media (prefers-color-scheme: dark) {{
  :root:not([data-theme="light"]) {{
{_color_block(dark, "    ")}
    color-scheme: dark;
  }}
}}

:root[data-theme="dark"] {{
{_color_block(dark)}
  color-scheme: dark;
}}
"""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="output CSS file")
    parser.add_argument(
        "--frontend", action="store_true", help=f"also write {FRONTEND_OUT.relative_to(BRANDING_DIR.parent)}"
    )
    args = parser.parse_args(argv)

    brand = json.loads(BRAND_FILE.read_text(encoding="utf-8"))
    css = render_css(brand)
    targets = [args.out] + ([FRONTEND_OUT] if args.frontend else [])
    for out in targets:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(css, encoding="utf-8", newline="\n")
        print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
