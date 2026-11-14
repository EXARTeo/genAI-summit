"""Build branded PowerPoint decks from YAML, using the tokens in branding/brand.json.

Usage:
    uv run python presentations/build.py                  # every deck in presentations/decks/
    uv run python presentations/build.py example          # one deck, by folder name
    uv run python presentations/build.py example --theme dark
    uv run python presentations/build.py path/to/deck.yaml --out some/dir

Each deck is a folder in presentations/decks/ with a deck.yaml (and any images
it uses). The .pptx is written to presentations/dist/<deck>.pptx.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from PIL import Image
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.slide import Slide
from pptx.util import Emu, Inches, Pt

PRESENTATIONS_DIR = Path(__file__).resolve().parent
ROOT = PRESENTATIONS_DIR.parent
BRANDING_DIR = ROOT / "branding"
DECKS_DIR = PRESENTATIONS_DIR / "decks"
DIST_DIR = PRESENTATIONS_DIR / "dist"

SLIDE_W = Inches(13.333)  # 16:9
SLIDE_H = Inches(7.5)
MARGIN = Inches(0.75)
CONTENT_W = SLIDE_W - 2 * MARGIN
LOGO_H = Inches(0.45)

COLOR_KEYS = (
    "background",
    "surface",
    "text",
    "muted",
    "border",
    "primary",
    "primary_foreground",
    "accent",
)

# layout -> required fields
LAYOUTS: dict[str, tuple[str, ...]] = {
    "title": ("title",),
    "section": ("title",),
    "bullets": ("title", "bullets"),
    "two-column": ("title", "left", "right"),
    "image": ("title", "image"),
    "quote": ("quote",),
    "closing": ("title",),
}


class DeckError(ValueError):
    """A deck or brand file is invalid."""


@dataclass(frozen=True)
class Theme:
    brand_name: str
    colors: dict[str, RGBColor]
    heading_font: str
    body_font: str
    logo_on_light: Path | None
    logo_on_dark: Path | None


# --------------------------------------------------------------------------- brand


def _rgb(value: str) -> RGBColor:
    try:
        return RGBColor.from_string(value.lstrip("#"))
    except ValueError as exc:
        raise DeckError(f"invalid colour {value!r}") from exc


def _existing(path: str | None) -> Path | None:
    if not path:
        return None
    p = BRANDING_DIR / path
    return p if p.is_file() else None


def load_theme(mode: str, brand_file: Path = BRANDING_DIR / "brand.json") -> Theme:
    brand = json.loads(brand_file.read_text(encoding="utf-8"))
    palette = brand.get("colors", {}).get(mode)
    if palette is None:
        raise DeckError(f"brand.json has no colours for theme {mode!r}")
    missing = [k for k in COLOR_KEYS if k not in palette]
    if missing:
        raise DeckError(f"brand.json colours.{mode} is missing {missing}")
    logo = brand.get("logo", {})
    return Theme(
        brand_name=brand.get("name", ""),
        colors={k: _rgb(palette[k]) for k in COLOR_KEYS},
        heading_font=brand.get("fonts", {}).get("heading", "Calibri"),
        body_font=brand.get("fonts", {}).get("body", "Calibri"),
        logo_on_light=_existing(logo.get("on_light")),
        logo_on_dark=_existing(logo.get("on_dark")),
    )


def _is_dark(color: RGBColor) -> bool:
    r, g, b = color[0], color[1], color[2]
    return (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255 < 0.5


# --------------------------------------------------------------------------- drawing


def _rect(slide: Slide, left: int, top: int, width: int, height: int, color: RGBColor) -> None:
    shape = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, left, top, width, height)
    shape.fill.solid()
    shape.fill.fore_color.rgb = color
    shape.line.fill.background()
    shape.shadow.inherit = False


def _text(
    slide: Slide,
    box: tuple[int, int, int, int],
    text: str,
    *,
    size: int,
    color: RGBColor,
    font: str,
    bold: bool = False,
    italic: bool = False,
    align: PP_ALIGN = PP_ALIGN.LEFT,
    anchor: MSO_ANCHOR = MSO_ANCHOR.TOP,
) -> None:
    frame = slide.shapes.add_textbox(*box).text_frame
    frame.word_wrap = True
    frame.vertical_anchor = anchor
    frame.margin_left = frame.margin_right = 0
    for i, line in enumerate(str(text).splitlines() or [""]):
        para = frame.paragraphs[0] if i == 0 else frame.add_paragraph()
        para.alignment = align
        run = para.add_run()
        run.text = line
        run.font.size = Pt(size)
        run.font.bold = bold
        run.font.italic = italic
        run.font.name = font
        run.font.color.rgb = color


def _bullets(
    slide: Slide, box: tuple[int, int, int, int], items: list[Any], theme: Theme, size: int = 22
) -> None:
    frame = slide.shapes.add_textbox(*box).text_frame
    frame.word_wrap = True
    frame.margin_left = frame.margin_right = 0
    first = True
    for item in items:
        text, subs = (item, []) if isinstance(item, str) else (item["text"], item.get("sub", []))
        for level, line in [(0, text), *[(1, s) for s in subs]]:
            para = frame.paragraphs[0] if first else frame.add_paragraph()
            first = False
            para.space_after = Pt(10 if level == 0 else 6)
            marker = para.add_run()
            marker.text = "●  " if level == 0 else "      –  "
            marker.font.size = Pt(size - 8 if level == 0 else size - 4)
            marker.font.color.rgb = theme.colors["accent"]
            marker.font.name = theme.body_font
            run = para.add_run()
            run.text = str(line)
            run.font.size = Pt(size if level == 0 else size - 4)
            run.font.name = theme.body_font
            run.font.color.rgb = theme.colors["text" if level == 0 else "muted"]


def _logo(slide: Slide, theme: Theme, bg: RGBColor, left: int, top: int, fg: RGBColor) -> None:
    logo = theme.logo_on_dark if _is_dark(bg) else theme.logo_on_light
    if logo:
        slide.shapes.add_picture(str(logo), left, top, height=LOGO_H)
    else:  # wordmark fallback until logo files exist
        box = (left, top, Inches(5), LOGO_H)
        _text(slide, box, theme.brand_name, size=18, color=fg, font=theme.heading_font, bold=True)


def _background(slide: Slide, color: RGBColor) -> None:
    fill = slide.background.fill
    fill.solid()
    fill.fore_color.rgb = color


def _chrome(slide: Slide, theme: Theme, title: str, footer: str, number: int) -> None:
    """Background, title, accent bar, logo and footer shared by content slides."""
    c = theme.colors
    _background(slide, c["background"])
    _rect(slide, MARGIN, Inches(0.6), Inches(0.6), Inches(0.08), c["accent"])
    title_box = (MARGIN, Inches(0.8), CONTENT_W - Inches(3), Inches(1.0))
    _text(slide, title_box, title, size=34, color=c["text"], font=theme.heading_font, bold=True)
    _logo(slide, theme, c["background"], SLIDE_W - MARGIN - Inches(2.5), Inches(0.55), c["muted"])
    _rect(slide, MARGIN, SLIDE_H - Inches(0.7), CONTENT_W, Emu(9525), c["border"])
    footer_text = f"{theme.brand_name}  ·  {footer}" if footer else theme.brand_name
    foot_y = SLIDE_H - Inches(0.6)
    _text(
        slide,
        (MARGIN, foot_y, Inches(8), Inches(0.35)),
        footer_text,
        size=11,
        color=c["muted"],
        font=theme.body_font,
    )
    _text(
        slide,
        (SLIDE_W - MARGIN - Inches(1), foot_y, Inches(1), Inches(0.35)),
        str(number),
        size=11,
        color=c["muted"],
        font=theme.body_font,
        align=PP_ALIGN.RIGHT,
    )


BODY_TOP = Inches(2.0)
BODY_H = SLIDE_H - BODY_TOP - Inches(1.0)


# --------------------------------------------------------------------------- layouts


def _hero(slide: Slide, spec: dict[str, Any], theme: Theme, bg_key: str, fg_key: str) -> None:
    c = theme.colors
    bg, fg = c[bg_key], c[fg_key]
    _background(slide, bg)
    _logo(slide, theme, bg, MARGIN, Inches(0.6), fg)
    _text(
        slide,
        (MARGIN, Inches(2.3), CONTENT_W, Inches(1.8)),
        spec["title"],
        size=54,
        color=fg,
        font=theme.heading_font,
        bold=True,
        anchor=MSO_ANCHOR.BOTTOM,
    )
    if spec.get("subtitle"):
        _text(
            slide,
            (MARGIN, Inches(4.3), CONTENT_W, Inches(1.0)),
            spec["subtitle"],
            size=24,
            color=fg,
            font=theme.body_font,
        )
    if spec.get("meta"):
        _text(
            slide,
            (MARGIN, SLIDE_H - Inches(1.2), CONTENT_W, Inches(0.5)),
            spec["meta"],
            size=14,
            color=fg,
            font=theme.body_font,
        )


def _layout_title(slide: Slide, spec: dict[str, Any], theme: Theme, **_: Any) -> None:
    _hero(slide, spec, theme, "primary", "primary_foreground")


def _layout_closing(slide: Slide, spec: dict[str, Any], theme: Theme, **_: Any) -> None:
    _hero(slide, spec, theme, "primary", "primary_foreground")


def _layout_section(slide: Slide, spec: dict[str, Any], theme: Theme, **_: Any) -> None:
    c = theme.colors
    _background(slide, c["surface"])
    _rect(slide, MARGIN, Inches(3.0), Inches(1.2), Inches(0.1), c["accent"])
    _text(
        slide,
        (MARGIN, Inches(3.3), CONTENT_W, Inches(1.4)),
        spec["title"],
        size=44,
        color=c["text"],
        font=theme.heading_font,
        bold=True,
    )
    if spec.get("subtitle"):
        _text(
            slide,
            (MARGIN, Inches(4.6), CONTENT_W, Inches(1.0)),
            spec["subtitle"],
            size=22,
            color=c["muted"],
            font=theme.body_font,
        )


def _layout_bullets(slide: Slide, spec: dict[str, Any], theme: Theme, **kw: Any) -> None:
    _chrome(slide, theme, spec["title"], kw["footer"], kw["number"])
    _bullets(slide, (MARGIN, BODY_TOP, CONTENT_W, BODY_H), spec["bullets"], theme)


def _layout_two_column(slide: Slide, spec: dict[str, Any], theme: Theme, **kw: Any) -> None:
    _chrome(slide, theme, spec["title"], kw["footer"], kw["number"])
    gap = Inches(0.5)
    col_w = (CONTENT_W - gap) // 2
    for i, key in enumerate(("left", "right")):
        col = spec[key]
        left = MARGIN + i * (col_w + gap)
        top = BODY_TOP
        if col.get("heading"):
            _text(
                slide,
                (left, top, col_w, Inches(0.6)),
                col["heading"],
                size=24,
                color=theme.colors["primary"],
                font=theme.heading_font,
                bold=True,
            )
            top += Inches(0.8)
        _bullets(
            slide,
            (left, top, col_w, BODY_H - (top - BODY_TOP)),
            col.get("bullets", []),
            theme,
            size=20,
        )


def _layout_image(slide: Slide, spec: dict[str, Any], theme: Theme, **kw: Any) -> None:
    _chrome(slide, theme, spec["title"], kw["footer"], kw["number"])
    path = (kw["deck_dir"] / spec["image"]).resolve()
    if not path.is_file():
        raise DeckError(f"image not found: {path}")
    caption_h = Inches(0.5) if spec.get("caption") else 0
    max_w, max_h = CONTENT_W, BODY_H - caption_h
    with Image.open(path) as img:
        ratio = img.width / img.height
    width, height = (
        (max_w, int(max_w / ratio)) if max_w / ratio <= max_h else (int(max_h * ratio), max_h)
    )
    left = MARGIN + (max_w - width) // 2
    slide.shapes.add_picture(str(path), left, BODY_TOP, width, height)
    if spec.get("caption"):
        _text(
            slide,
            (MARGIN, BODY_TOP + height + Inches(0.1), CONTENT_W, caption_h),
            spec["caption"],
            size=14,
            color=theme.colors["muted"],
            font=theme.body_font,
            align=PP_ALIGN.CENTER,
        )


def _layout_quote(slide: Slide, spec: dict[str, Any], theme: Theme, **_: Any) -> None:
    c = theme.colors
    _background(slide, c["surface"])
    _rect(slide, MARGIN, Inches(2.0), Inches(0.1), Inches(3.0), c["accent"])
    inner = MARGIN + Inches(0.5)
    _text(
        slide,
        (inner, Inches(2.0), CONTENT_W - Inches(0.5), Inches(2.4)),
        spec["quote"],
        size=34,
        color=c["text"],
        font=theme.heading_font,
        italic=True,
    )
    if spec.get("author"):
        _text(
            slide,
            (inner, Inches(4.5), CONTENT_W - Inches(0.5), Inches(0.5)),
            f"— {spec['author']}",
            size=18,
            color=c["muted"],
            font=theme.body_font,
        )


RENDERERS = {
    "title": _layout_title,
    "section": _layout_section,
    "bullets": _layout_bullets,
    "two-column": _layout_two_column,
    "image": _layout_image,
    "quote": _layout_quote,
    "closing": _layout_closing,
}


# --------------------------------------------------------------------------- deck


def load_deck(path: Path) -> dict[str, Any]:
    deck = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    slides = deck.get("slides")
    if not isinstance(slides, list) or not slides:
        raise DeckError(f"{path}: 'slides' must be a non-empty list")
    for i, spec in enumerate(slides, start=1):
        layout = spec.get("layout") if isinstance(spec, dict) else None
        if layout not in LAYOUTS:
            raise DeckError(
                f"{path}: slide {i} has unknown layout {layout!r}; use one of {sorted(LAYOUTS)}"
            )
        missing = [f for f in LAYOUTS[layout] if not spec.get(f)]
        if missing:
            raise DeckError(f"{path}: slide {i} ({layout}) is missing {missing}")
    return deck


def build_deck(deck_file: Path, out_file: Path, theme_override: str | None = None) -> Path:
    deck = load_deck(deck_file)
    theme = load_theme(theme_override or deck.get("theme", "light"))
    prs = Presentation()
    prs.slide_width, prs.slide_height = SLIDE_W, SLIDE_H
    prs.core_properties.title = deck.get("title", deck_file.parent.name)
    prs.core_properties.author = theme.brand_name
    blank = prs.slide_layouts[6]
    for number, spec in enumerate(deck["slides"], start=1):
        slide = prs.slides.add_slide(blank)
        RENDERERS[spec["layout"]](
            slide,
            spec,
            theme,
            footer=deck.get("footer", ""),
            number=number,
            deck_dir=deck_file.parent,
        )
        if spec.get("notes"):
            slide.notes_slide.notes_text_frame.text = str(spec["notes"])
    out_file.parent.mkdir(parents=True, exist_ok=True)
    prs.save(str(out_file))
    return out_file


def _resolve(target: str) -> Path:
    p = Path(target)
    if p.suffix in {".yaml", ".yml"}:
        return p.resolve()
    return DECKS_DIR / target / "deck.yaml"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build branded .pptx decks from YAML.")
    parser.add_argument(
        "decks",
        nargs="*",
        help="deck folder names or deck.yaml paths (default: every deck in presentations/decks/)",
    )
    parser.add_argument("--theme", choices=["light", "dark"], help="override the deck's theme")
    parser.add_argument("--out", type=Path, default=DIST_DIR, help="output directory")
    args = parser.parse_args(argv)

    files = [_resolve(d) for d in args.decks] or sorted(DECKS_DIR.glob("*/deck.yaml"))
    if not files:
        print("no decks found", file=sys.stderr)
        return 1
    try:
        for deck_file in files:
            if not deck_file.is_file():
                raise DeckError(f"deck not found: {deck_file}")
            out = build_deck(deck_file, args.out / f"{deck_file.parent.name}.pptx", args.theme)
            print(f"built {out}")
    except DeckError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
