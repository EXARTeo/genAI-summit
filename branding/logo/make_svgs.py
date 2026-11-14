"""Generate the Mnamon logo SVGs in branding/logo/.

The source sheet (branding/source/logo-a-plus-c.pdf) is a raster, so the mark is re-drawn here
from geometry measured on it (one 70-unit stroke on a 75-unit grid: arch, U, arch; seven
horizontal bands; lex left, terra right, fading to 45% at the bottom) and the MNAMON wordmark is
EB Garamond Medium outlines with ~0.19 em tracking. The PNG/ICO exports are rendered from these
SVGs (see branding/logo/README.md).

Usage (fonttools is not a repo dependency):
    uv run --with fonttools --with brotli python branding/logo/make_svgs.py \
        branding/logo path/to/eb-garamond-latin-500-normal.woff2
"""

import sys
from pathlib import Path

from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen
from fontTools.ttLib import TTFont

OUT = Path(sys.argv[1])
FONT = Path(sys.argv[2])

W, H = 520, 365  # mark box
CENTER = "M35 365V110A75 75 0 0 1 185 110V260A75 75 0 0 0 335 260V110A75 75 0 0 1 485 110V365"
STROKE = 70
BANDS = [(y, 35) for y in range(0, 365, 55)]  # 7 bands, 35 on / 20 off
FADE = 0.45  # bottom opacity (the mark fades into the background)

THEMES = {
    "light": {"lex": "#2F5F80", "terra": "#B85A20", "word": "#13171F"},
    "dark": {"lex": "#7FB0D1", "terra": "#D2773A", "word": "#EDE8DC"},
}


def wordmark_path() -> tuple[str, float]:
    f = TTFont(str(FONT))
    gs = f.getGlyphSet()
    cmap = f.getBestCmap()
    s = 0.2167  # px per font unit, measured on the PDF raster
    track = 194  # font units between letters (~0.19 em)
    x0, base = 691.4, 261.5
    pen = SVGPathPen(gs, ntos=lambda v: f"{v:.1f}".rstrip("0").rstrip("."))
    x = 0.0
    end = 0.0
    for ch in "MNAMON":
        g = cmap[ord(ch)]
        tp = TransformPen(pen, (s, 0, 0, -s, x0 + x * s, base))
        gs[g].draw(tp)
        end = x0 + (x + gs[g].width) * s
        x += gs[g].width + track
    return pen.getCommands(), end


def defs(prefix: str, lex: str, terra: str, striped: bool) -> str:
    grads = "".join(
        f'<linearGradient id="{prefix}{n}" x1="0" y1="0" x2="0" y2="{H}" '
        'gradientUnits="userSpaceOnUse">'
        f'<stop offset="0" stop-color="{c}"/>'
        f'<stop offset="1" stop-color="{c}" stop-opacity="{FADE}"/>'
        "</linearGradient>"
        for n, c in (("l", lex), ("t", terra))
    )
    clips = ""
    for n, (x, w) in (("l", (0, 260)), ("t", (260, 260))):
        rects = (
            "".join(f'<rect x="{x}" y="{y}" width="{w}" height="{h}"/>' for y, h in BANDS)
            if striped
            else f'<rect x="{x}" y="0" width="{w}" height="{H}"/>'
        )
        clips += f'<clipPath id="{prefix}c{n}">{rects}</clipPath>'
    return f"<defs>{grads}{clips}</defs>"


def mark_group(prefix: str) -> str:
    return "".join(
        f'<path d="{CENTER}" fill="none" stroke="url(#{prefix}{n})" stroke-width="{STROKE}" '
        f'clip-path="url(#{prefix}c{n})"/>'
        for n in ("l", "t")
    )


def svg(vb: str, body: str, label: str, w: float, h: float) -> str:
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{vb}" width="{w:g}" height="{h:g}" '
        f'role="img" aria-label="{label}">{body}</svg>\n'
    )


def main() -> None:
    word, end = wordmark_path()
    full_w = round(end + 1)
    print("lockup width", full_w)
    for theme, c in THEMES.items():
        suffix = "" if theme == "light" else "-on-dark"
        p = "m"
        body = (
            defs(p, c["lex"], c["terra"], True)
            + mark_group(p)
            + f'<path d="{word}" fill="{c["word"]}"/>'
        )
        (OUT / f"logo{suffix}.svg").write_text(
            svg(f"0 0 {full_w} {H}", body, "Mnamon", full_w / 4, H / 4),
            encoding="utf-8",
            newline="\n",
        )
        body = defs(p, c["lex"], c["terra"], True) + mark_group(p)
        (OUT / f"mark{suffix}.svg").write_text(
            svg(f"0 0 {W} {H}", body, "Mnamon", W / 8, H / 8), encoding="utf-8", newline="\n"
        )
    # App icon / favicon: dark mark on an ink tile (as in the source sheet). Striped for large
    # sizes, solid stroke for the favicon (stripes do not survive 16-32 px).
    d = THEMES["dark"]
    side, k = 1000, 1.15  # the mark spans ~60% of the tile, as on the source sheet
    tx, ty = (side - W * k) / 2, (side - H * k) / 2
    for name, striped in (("icon.svg", True), ("favicon.svg", False)):
        body = (
            defs("i", d["lex"], d["terra"], striped)
            + f'<rect width="{side}" height="{side}" rx="{side * 0.225:g}" fill="#13171F"/>'
            + f'<g transform="translate({tx:g} {ty:g}) scale({k})">{mark_group("i")}</g>'
        )
        (OUT / name).write_text(
            svg(f"0 0 {side} {side}", body, "Mnamon", 64, 64), encoding="utf-8", newline="\n"
        )


if __name__ == "__main__":
    main()
