"""Generate CSS variables from branding/brand.json.

Usage:
    uv run python branding/export_tokens.py            # writes branding/dist/tokens.css
    uv run python branding/export_tokens.py --out x.css
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

BRANDING_DIR = Path(__file__).resolve().parent
BRAND_FILE = BRANDING_DIR / "brand.json"
DEFAULT_OUT = BRANDING_DIR / "dist" / "tokens.css"


def _var(name: str) -> str:
    return name.replace("_", "-")


def _color_block(colors: dict[str, str], indent: str = "  ") -> str:
    return "\n".join(f"{indent}--color-{_var(k)}: {v};" for k, v in colors.items())


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
    args = parser.parse_args(argv)

    brand = json.loads(BRAND_FILE.read_text(encoding="utf-8"))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(render_css(brand), encoding="utf-8", newline="\n")
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
