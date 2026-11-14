"""Build the architecture diagrams: SVG sources and PNG renders.

Colours and fonts come from ``branding/brand.json`` (light theme). Each diagram is
recorded once as shapes, then written as ``<name>.svg`` (editable, crisp on GitHub)
and drawn to ``<name>.png`` at 2x with Pillow (no browser needed).

Usage: ``uv run python docs/architecture/diagrams/build.py [--svg-only]``
(or ``scripts/build-diagrams.*``).
"""

from __future__ import annotations

import json
import math
import sys
from html import escape
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
BRAND = json.loads((ROOT / "branding" / "brand.json").read_text(encoding="utf-8"))
C = BRAND["colors"]["light"]
FONT = f"{BRAND['fonts']['body']}, 'Segoe UI', Arial, sans-serif"
MONO = f"{BRAND['fonts']['mono']}, Consolas, monospace"

# Box styles: (stroke, fill, dash, title colour)
STYLES = {
    "existing": (C["primary"], C["background"], "", C["primary"]),
    "planned": (C["primary"], C["background"], "8 5", C["primary"]),
    "external": (C["muted"], C["surface"], "3 4", C["muted"]),
    "store": (C["border"], C["surface"], "", C["text"]),
    "hitl": (C["accent"], C["background"], "", C["accent"]),
    "step": (C["primary"], C["background"], "", C["text"]),
    "output": (C["accent"], C["surface"], "", C["text"]),
}


class Svg:
    """Tiny diagram builder: records shapes, then renders them to SVG and PNG."""

    def __init__(self, width: int, height: int, title: str, subtitle: str = "") -> None:
        self.w, self.h = width, height
        self.ops: list[tuple[str, dict]] = []
        self._rect(0, 0, width, height, 0, C["background"], None)
        self.text(40, 52, title, 28, C["text"], 700)
        if subtitle:
            self.text(40, 80, subtitle, 15, C["muted"])

    # ---------------------------------------------------------------- primitives

    def _rect(self, x, y, w, h, rx, fill, stroke, dash="", sw=2):
        self.ops.append(
            ("rect", dict(x=x, y=y, w=w, h=h, rx=rx, fill=fill, stroke=stroke, dash=dash, sw=sw))
        )

    def text(self, x, y, text, size=14, color=None, weight=400, anchor="start", family=None):
        self.ops.append(
            (
                "text",
                dict(
                    x=x,
                    y=y,
                    text=text,
                    size=size,
                    color=color or C["text"],
                    weight=weight,
                    anchor=anchor,
                    mono=family == MONO,
                ),
            )
        )

    def box(self, x, y, w, h, title, lines=(), style="existing", tag="", mono_title=True):
        stroke, fill, dash, tcol = STYLES[style]
        self._rect(x, y, w, h, 12, fill, stroke, dash)
        self.text(x + 14, y + 28, title, 17, tcol, 700, family=MONO if mono_title else None)
        if tag:
            tw = 9 + len(tag) * 6.6
            self._rect(x + w - tw - 10, y + 12, tw, 20, 10, _blend(stroke, fill, 0.14), None)
            self.text(x + w - tw / 2 - 10, y + 26, tag, 11, stroke, 600, "middle")
        for i, line in enumerate(lines):
            self.text(x + 14, y + 52 + i * 19, line, 13.5, C["text"] if i == 0 else C["muted"])
        return (x, y, w, h)

    def actor(self, cx, cy, label):
        self.ops.append(("actor", dict(cx=cx, cy=cy, color=C["text"])))
        self.text(cx, cy + 44, label, 15, C["text"], 600, "middle")

    def arrow(self, points, label="", color=None, dashed=False, both=False, label_at=0.5, dy=-8):
        color = color or C["muted"]
        self.ops.append(("path", dict(points=points, color=color, dashed=dashed, both=both)))
        if label:
            (x1, y1), (x2, y2) = _segment_at(points, label_at)
            self.label(x1 + (x2 - x1) * 0.5, y1 + (y2 - y1) * 0.5 + dy, label, color)

    def label(self, x, y, text, color=None, size=12.5):
        tw = len(text) * size * 0.56 + 12
        self._rect(x - tw / 2, y - size - 2, tw, size + 9, 5, C["background"], None)
        self.text(x, y + 1, text, size, color or C["muted"], anchor="middle")

    def legend(self, x, y, items):
        for i, (style, text) in enumerate(items):
            stroke, fill, dash, _ = STYLES[style]
            xx = x + i * 220
            self._rect(xx, y, 34, 20, 5, fill, stroke, dash)
            self.text(xx + 44, y + 15, text, 13.5, C["muted"])

    # ---------------------------------------------------------------- SVG

    def render(self) -> str:
        parts = []
        for kind, o in self.ops:
            if kind == "rect":
                stroke = f' stroke="{o["stroke"]}" stroke-width="{o["sw"]}"' if o["stroke"] else ""
                da = f' stroke-dasharray="{o["dash"]}"' if o["dash"] and o["stroke"] else ""
                parts.append(
                    f'<rect x="{o["x"]}" y="{o["y"]}" width="{o["w"]}" height="{o["h"]}" '
                    f'rx="{o["rx"]}" fill="{o["fill"]}"{stroke}{da}/>'
                )
            elif kind == "text":
                fam = f' font-family="{escape(MONO, quote=True)}"' if o["mono"] else ""
                anchor = f' text-anchor="{o["anchor"]}"' if o["anchor"] != "start" else ""
                parts.append(
                    f'<text x="{o["x"]}" y="{o["y"]}" font-size="{o["size"]}" '
                    f'font-weight="{o["weight"]}"{anchor}{fam} fill="{o["color"]}">'
                    f"{escape(o['text'])}</text>"
                )
            elif kind == "actor":
                cx, cy, m = o["cx"], o["cy"], o["color"]
                parts.append(
                    f'<circle cx="{cx}" cy="{cy - 30}" r="14" fill="none" '
                    f'stroke="{m}" stroke-width="2.5"/>'
                    f'<path d="M{cx - 24},{cy + 18} Q{cx},{cy - 26} {cx + 24},{cy + 18} Z" '
                    f'fill="none" stroke="{m}" stroke-width="2.5"/>'
                )
            elif kind == "path":
                d = "M" + " L".join(f"{x},{y}" for x, y in o["points"])
                da = ' stroke-dasharray="6 5"' if o["dashed"] else ""
                mid = _marker_id(o["color"])
                start = f' marker-start="url(#{mid}s)"' if o["both"] else ""
                parts.append(
                    f'<path d="{d}" fill="none" stroke="{o["color"]}" stroke-width="2"{da} '
                    f'marker-end="url(#{mid})"{start}/>'
                )
        colors = {C["muted"], C["primary"], C["accent"], C["text"]}
        markers = "".join(
            f'<marker id="{_marker_id(c)}" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="8" '
            f'markerHeight="8" orient="auto"><path d="M0,0 L10,5 L0,10 z" fill="{c}"/></marker>'
            f'<marker id="{_marker_id(c)}s" viewBox="0 0 10 10" refX="1" refY="5" markerWidth="8" '
            f'markerHeight="8" orient="auto"><path d="M10,0 L0,5 L10,10 z" fill="{c}"/></marker>'
            for c in colors
        )
        return (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{self.w}" height="{self.h}" '
            f'viewBox="0 0 {self.w} {self.h}" font-family="{escape(FONT, quote=True)}">'
            f"<defs>{markers}</defs>{''.join(parts)}</svg>\n"
        )

    # ---------------------------------------------------------------- PNG (Pillow)

    def render_png(self, path: Path, scale: int = 2) -> None:
        s = scale
        img = Image.new("RGB", (self.w * s, self.h * s), C["background"])
        d = ImageDraw.Draw(img)
        for kind, o in self.ops:
            if kind == "rect":
                box = [o["x"] * s, o["y"] * s, (o["x"] + o["w"]) * s, (o["y"] + o["h"]) * s]
                solid = o["stroke"] if o["stroke"] and not o["dash"] else None
                d.rounded_rectangle(
                    box,
                    radius=o["rx"] * s,
                    fill=o["fill"],
                    outline=solid,
                    width=o["sw"] * s if solid else 0,
                )
                if o["stroke"] and o["dash"]:
                    pts = _rounded_outline(*box, o["rx"] * s)
                    pattern = [float(v) * s for v in o["dash"].split()]
                    _dashed(d, pts, pattern, o["stroke"], o["sw"] * s)
            elif kind == "text":
                font = _font(o["mono"], o["weight"], o["size"] * s)
                anchor = {"start": "ls", "middle": "ms", "end": "rs"}[o["anchor"]]
                d.text(
                    (o["x"] * s, o["y"] * s), o["text"], font=font, fill=o["color"], anchor=anchor
                )
            elif kind == "actor":
                cx, cy, m, w = o["cx"] * s, o["cy"] * s, o["color"], round(2.5 * s)
                r = 14 * s
                d.ellipse([cx - r, cy - 30 * s - r, cx + r, cy - 30 * s + r], outline=m, width=w)
                p0, p1, p2 = (
                    (cx - 24 * s, cy + 18 * s),
                    (cx, cy - 26 * s),
                    (cx + 24 * s, cy + 18 * s),
                )
                curve = [_quad(p0, p1, p2, t / 40) for t in range(41)]
                d.line(curve + [p0], fill=m, width=w, joint="curve")
            elif kind == "path":
                pts = [(x * s, y * s) for x, y in o["points"]]
                if o["dashed"]:
                    _dashed(d, pts, [6 * s, 5 * s], o["color"], 2 * s)
                else:
                    d.line(pts, fill=o["color"], width=2 * s, joint="curve")
                _arrowhead(d, pts[-2], pts[-1], o["color"], s)
                if o["both"]:
                    _arrowhead(d, pts[1], pts[0], o["color"], s)
        img.save(path, optimize=True)


def _marker_id(color: str) -> str:
    return "m" + color.lstrip("#")


def _segment_at(points, frac):
    idx = min(int(frac * (len(points) - 1)), len(points) - 2)
    return points[idx], points[idx + 1]


def _blend(fg: str, bg: str, alpha: float) -> str:
    f = [int(fg[i : i + 2], 16) for i in (1, 3, 5)]
    b = [int(bg[i : i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(
        f"{round(fc * alpha + bc * (1 - alpha)):02x}" for fc, bc in zip(f, b, strict=True)
    )


# Font files per (mono, weight); Pillow finds them in the system fonts folder.
FONT_FILES = {
    (False, 400): ["segoeui.ttf", "DejaVuSans.ttf", "Arial.ttf"],
    (False, 600): ["seguisb.ttf", "DejaVuSans-Bold.ttf", "Arial Bold.ttf"],
    (False, 700): ["segoeuib.ttf", "DejaVuSans-Bold.ttf", "Arial Bold.ttf"],
    (True, 400): ["consola.ttf", "DejaVuSansMono.ttf", "Courier New.ttf"],
    (True, 600): ["consolab.ttf", "DejaVuSansMono-Bold.ttf", "Courier New Bold.ttf"],
    (True, 700): ["consolab.ttf", "DejaVuSansMono-Bold.ttf", "Courier New Bold.ttf"],
}
_FONT_CACHE: dict = {}


def _font(mono: bool, weight: int, px: float):
    key = (mono, 700 if weight >= 700 else 600 if weight >= 600 else 400, round(px))
    if key not in _FONT_CACHE:
        for name in FONT_FILES[key[:2]]:
            try:
                _FONT_CACHE[key] = ImageFont.truetype(name, key[2])
                break
            except OSError:
                continue
        else:
            _FONT_CACHE[key] = ImageFont.load_default(size=key[2])
    return _FONT_CACHE[key]


def _quad(p0, p1, p2, t):
    return (
        (1 - t) ** 2 * p0[0] + 2 * (1 - t) * t * p1[0] + t * t * p2[0],
        (1 - t) ** 2 * p0[1] + 2 * (1 - t) * t * p1[1] + t * t * p2[1],
    )


def _rounded_outline(x0, y0, x1, y1, r, steps=8):
    """Closed polyline around a rounded rectangle (clockwise from top-left)."""
    corners = [
        (x1 - r, y0 + r, -90),
        (x1 - r, y1 - r, 0),
        (x0 + r, y1 - r, 90),
        (x0 + r, y0 + r, 180),
    ]
    pts = []
    for cx, cy, start in corners:
        for i in range(steps + 1):
            a = math.radians(start + 90 * i / steps)
            pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    return pts + [pts[0]]


def _dashed(d, pts, pattern, color, width):
    """Draw a dashed polyline; the pattern carries on across segments."""
    idx, left, on = 0, pattern[0], True
    for (x0, y0), (x1, y1) in zip(pts, pts[1:], strict=False):
        seg = math.hypot(x1 - x0, y1 - y0)
        pos = 0.0
        while seg > 0 and pos < seg:
            step = min(left, seg - pos)
            if on:
                a, b = pos / seg, (pos + step) / seg
                d.line(
                    [
                        (x0 + (x1 - x0) * a, y0 + (y1 - y0) * a),
                        (x0 + (x1 - x0) * b, y0 + (y1 - y0) * b),
                    ],
                    fill=color,
                    width=round(width),
                )
            pos += step
            left -= step
            if left <= 1e-6:
                idx = (idx + 1) % len(pattern)
                left, on = pattern[idx], not on


def _arrowhead(d, frm, to, color, s):
    ang = math.atan2(to[1] - frm[1], to[0] - frm[0])
    length, half = 13 * s, 6.5 * s
    bx, by = to[0] - length * math.cos(ang), to[1] - length * math.sin(ang)
    px, py = -math.sin(ang) * half, math.cos(ang) * half
    d.polygon([to, (bx + px, by + py), (bx - px, by - py)], fill=color)


# --------------------------------------------------------------------------- diagrams


def containers() -> Svg:
    s = Svg(
        1500,
        900,
        "Containers",
        "AI Act Governance Copilot: hackathon MVP (AI Engineer / provider pillar)",
    )
    P, A, M = C["primary"], C["accent"], C["muted"]
    # External row
    s.box(
        480,
        115,
        260,
        76,
        "Telegram bot",
        ["Change alerts, inline buttons"],
        "external",
        mono_title=False,
    )
    s.box(800, 115, 260, 76, "LLM provider", ["Hackathon credits"], "external", mono_title=False)
    s.box(
        1150,
        115,
        300,
        76,
        "Firecrawl",
        ["Monitors EUR-Lex, guidelines"],
        "external",
        mono_title=False,
    )
    # Main row
    s.actor(105, 340, "AI Engineer")
    s.box(200, 280, 220, 110, "frontend", ["Engineer workspace", "Next.js"], "planned", "new")
    s.box(
        480,
        280,
        260,
        110,
        "backend",
        ["API, cards, runs, findings", "FastAPI · job queue · webhooks"],
        "existing",
        "built",
    )
    s.box(
        800,
        280,
        260,
        110,
        "agents",
        ["Test + impact pipelines", "LangGraph · AG-UI over SSE"],
        "existing",
        "built",
    )
    s.box(
        1150,
        280,
        300,
        110,
        "reg-memory (RKS)",
        ["Versioned AI Act corpus", "diff · watcher · change judge"],
        "planned",
        "new",
    )
    # Stores and runners
    s.box(400, 490, 160, 96, "postgres", ["product DB", "+ agent_runtime"], "store")
    s.box(580, 490, 160, 96, "redis", ["cache · streams"], "store")
    s.box(
        800, 490, 260, 96, "langfuse", ["Traces = audit trail", "UI on :3400"], "existing", "built"
    )
    s.box(
        1150,
        490,
        300,
        96,
        "sandbox",
        ["Runs tests · no network", "sklearn · fairlearn · sdv"],
        "existing",
        "built",
    )
    s.box(
        1150,
        690,
        300,
        96,
        "mlflow",
        ["Model registry + test runs", "artifacts, data cards"],
        "planned",
        "new",
    )
    # Arrows
    s.arrow([(135, 335), (198, 335)], "", M)
    s.arrow([(420, 335), (478, 335)], "REST / WS", P, dy=-10)
    s.arrow([(740, 335), (798, 335)], "AG-UI", P, dy=-10)
    s.arrow([(1060, 335), (1148, 335)], "requirements", P, both=True, dy=-10)
    s.arrow([(610, 278), (610, 193)], "notify / callback", M, both=True)
    s.arrow([(930, 278), (930, 193)], "LLM calls", M)
    s.arrow([(1300, 193), (1300, 278)], "webhook: page changed", M)
    s.arrow([(540, 392), (500, 488)], "", M)
    s.arrow([(680, 392), (660, 488)], "", M)
    s.arrow([(740, 380), (810, 488)], "", A, dashed=True)
    s.arrow([(930, 392), (930, 488)], "traces", A, dashed=True, dy=0)
    s.arrow([(1060, 380), (1148, 500)], "run tests", P, dy=-4)
    s.arrow([(1300, 588), (1300, 688)], "log run", P)
    s.arrow([(1040, 392), (1148, 720)], "model, results", P, label_at=0.6)
    s.label(1300, 445, "RegChange → impact pipeline", P)
    # Legend
    s.legend(
        40,
        830,
        [
            ("existing", "built (repo today)"),
            ("planned", "planned (MVP)"),
            ("external", "external service"),
            ("store", "datastore"),
        ],
    )
    s.text(960, 845, "Dashed blue arrows: every step is traced in Langfuse", 13.5, A)
    return s


def engineer_pipeline() -> Svg:
    s = Svg(
        1500,
        700,
        "Engineer pipeline",
        "LangGraph test pipeline: system card + model in, findings and two reports out",
    )
    P, A, M = C["primary"], C["accent"], C["muted"]
    s.box(
        40,
        120,
        220,
        130,
        "1 load_context",
        ["System card, MLflow model", "Requirements from RKS", "(provider, high, Annex III 4a)"],
        "step",
    )
    s.box(
        310,
        120,
        220,
        130,
        "2 plan_tests",
        ["Requirement → templates", "Each test: proves / can't", "Untestable → needs_docs"],
        "step",
    )
    s.box(580, 140, 170, 90, "HITL", ["approve plan"], "hitl", mono_title=False)
    s.box(
        800,
        120,
        240,
        130,
        "3 generate_data",
        ["DatasetSpec per test", "Counterfactual twins,", "perturbation, schema-driven"],
        "step",
    )
    s.box(1090, 140, 170, 90, "HITL", ["audit datasets"], "hitl", mono_title=False)
    for a, b in [(260, 308), (530, 578), (750, 798), (1040, 1088)]:
        s.arrow([(a, 185), (b, 185)], "", P)
    s.arrow([(1175, 232), (1175, 300), (150, 300), (150, 358)], "", P)
    s.box(
        40,
        360,
        220,
        130,
        "4 execute",
        ["In the sandbox", "One MLflow run per test", "bootstrap CI on metrics"],
        "step",
    )
    s.box(
        310,
        360,
        220,
        130,
        "5 analyse",
        ["Findings: verdict,", "confidence, evidence,", "reasoning"],
        "step",
    )
    s.box(
        580,
        360,
        220,
        130,
        "6 critic",
        ["Tries to overturn", "each finding; verdict", "adjusted, conflicts shown"],
        "step",
    )
    s.box(850, 360, 220, 130, "7 report", ["Two audiences,", "same evidence"], "step")
    for a, b in [(260, 308), (530, 578), (800, 848)]:
        s.arrow([(a, 425), (b, 425)], "", P)
    s.arrow([(690, 492), (690, 520), (420, 520), (420, 492)], "challenges", A, dashed=True, dy=16)
    s.box(
        1120,
        340,
        340,
        80,
        "Engineer report",
        ["run ids, seeds, code: reproducible"],
        "output",
        mono_title=False,
    )
    s.box(
        1120,
        430,
        340,
        80,
        "Management report",
        ["traffic light per requirement, top risks"],
        "output",
        mono_title=False,
    )
    s.arrow([(1070, 410), (1118, 380)], "", A)
    s.arrow([(1070, 440), (1118, 470)], "", A)
    # Footer facts
    y = 580
    s.text(40, y, "Finding verdicts", 15, weight=700)
    s.text(
        40,
        y + 26,
        "supports_compliance · indicates_gap · inconclusive · not_assessable_by_testing",
        14,
        M,
        family=MONO,
    )
    s.text(
        40,
        y + 60,
        "Each MLflow run is tagged req_ids, card_version, kb_version, dataset_id. "
        "Thresholds are the "
        "organisation's, not the law's.",
        14,
        M,
    )
    s.text(
        40,
        y + 84,
        "Every node and tool call is a Langfuse span: the judges can replay the whole run.",
        14,
        A,
    )
    return s


def reg_change() -> Svg:
    s = Svg(
        1500,
        640,
        "Regulation change → re-review",
        "From a changed web page to a per-system decision and a delta report",
    )
    P, A, M = C["primary"], C["accent"], C["muted"]
    s.box(
        40,
        120,
        230,
        120,
        "Firecrawl monitor",
        ["EUR-Lex, Service Desk,", "guideline pages"],
        "external",
        mono_title=False,
    )
    s.box(
        320,
        120,
        260,
        120,
        "RKS: diff",
        ["Re-parse document", "Provision-level diff", "by content_hash"],
        "planned",
    )
    s.box(
        630,
        120,
        260,
        120,
        "RKS: classify",
        ["LLM: editorial, substantive,", "date, scope, interpretation", "→ RegChange + kb_version"],
        "planned",
    )
    s.box(
        940,
        120,
        240,
        120,
        "Impact index",
        ["No LLM: provision →", "requirements → findings", "→ systems"],
        "planned",
    )
    s.box(
        1230,
        120,
        230,
        120,
        "HITL",
        ["AI Officer accepts", "new kb_version"],
        "hitl",
        mono_title=False,
    )
    for a, b in [(270, 318), (580, 628), (890, 938), (1180, 1228)]:
        s.arrow([(a, 180), (b, 180)], "", P)
    s.arrow([(1345, 242), (1345, 290), (160, 290), (160, 338)], "", P)
    s.box(
        40,
        340,
        300,
        150,
        "Change judge",
        [
            "per (system, change)",
            "no_impact",
            "reinterpret_existing_evidence",
            "rerun_tests · new_tests_needed",
        ],
        "existing",
        "agents",
    )
    s.box(
        390,
        340,
        300,
        150,
        "Notify",
        [
            "Platform inbox + Telegram",
            "summary, diff excerpt,",
            "decision per system",
            "[See diff] [Re-run SYS-001]",
        ],
        "existing",
        "backend",
    )
    s.box(
        740,
        340,
        300,
        150,
        "Re-run",
        ["Engineer pipeline again", "(also on override of", "no_impact → judge feedback)"],
        "existing",
        "agents",
    )
    s.box(
        1090,
        340,
        370,
        150,
        "Delta report",
        ["Which findings changed verdict", "vs the previous kb_version,", "and why"],
        "output",
        mono_title=False,
    )
    for a, b in [(340, 388), (690, 738), (1040, 1088)]:
        s.arrow([(a, 415), (b, 415)], "", P)
    s.text(
        40,
        560,
        "Old decisions are never rewritten: they are marked stale and keep the "
        "kb_version they were made with.",
        14,
        M,
    )
    s.text(
        40,
        586,
        'Demo trick: a mirrored guideline page we edit live, then "Check now" '
        "→ Telegram alert in seconds.",
        14,
        A,
    )
    return s


def traceability() -> Svg:
    s = Svg(
        1500,
        720,
        "Traceability model",
        "RKS corpus (YAML in git) linked to tests, runs and findings; "
        "every link carries kb_version",
    )
    P, A, M = C["primary"], C["accent"], C["muted"]
    # Change + interpretation row
    s.box(40, 120, 220, 110, "Interpretation", ["GL.ART6.DRAFT.ex12", "binding: false"], "planned")
    s.box(
        340,
        120,
        260,
        110,
        "RegChange",
        ["affected provisions", "→ candidate kb_version"],
        "planned",
    )
    # Main chain
    s.box(
        40,
        300,
        220,
        120,
        "Provision",
        ["AIA.10.2.f", "verbatim text, valid_from,", "content_hash"],
        "planned",
    )
    s.box(
        330,
        300,
        250,
        120,
        "Requirement",
        ["REQ.AIA.10.2.f.bias-exam", "actor, applies_if,", "testability"],
        "planned",
    )
    s.box(
        650,
        300,
        260,
        120,
        "TestTemplate",
        ["TT.fairness.counterfactual", "needs, metric,", "limitations"],
        "planned",
    )
    s.box(
        980,
        300,
        210,
        120,
        "TestRun",
        ["MLflow run", "dataset + Data Card,", "metrics with CI"],
        "planned",
    )
    s.box(
        1260,
        300,
        200,
        120,
        "Finding",
        ["F-SYS001-0007", "verdict, evidence,", "counter_evidence"],
        "output",
    )
    s.box(
        980,
        540,
        210,
        110,
        "SystemCard",
        ["SYS-001 CV Screener", "proxies, thresholds"],
        "existing",
        "seeded",
    )
    # Links
    s.arrow([(338, 175), (262, 175)], "affects", M)
    s.arrow([(380, 232), (250, 298)], "affects", M, dashed=True, dy=-4)
    s.arrow([(150, 232), (150, 298)], "relates_to", M, dy=4)
    s.arrow([(262, 360), (328, 360)], "source", P)
    s.arrow([(580, 360), (648, 360)], "uses", P)
    s.arrow([(910, 360), (978, 360)], "runs as", P)
    s.arrow([(1190, 360), (1258, 360)], "yields", P)
    s.arrow([(1085, 538), (1085, 422)], "params, thresholds", P, dy=16, label_at=0.9)
    s.arrow([(1400, 422), (1400, 595), (1192, 595)], "about", M, label_at=0.9)
    s.arrow(
        [(1300, 422), (1300, 475), (110, 475), (110, 422)],
        "citations (verified against the KB)",
        A,
        dashed=True,
    )
    s.text(
        40,
        690,
        "Impact index (no LLM) walks these links backwards: provision → requirement → test run → "
        "finding → system.",
        14,
        M,
    )
    return s


def agent_context() -> Svg:
    s = Svg(
        1500,
        900,
        "Agent context and memory",
        "Everything is a file in Postgres; human feedback becomes audited memory",
    )
    P, A, M = C["primary"], C["accent"], C["muted"]
    # Four context sources (top row)
    s.box(
        40,
        115,
        420,
        165,
        "reg-memory (RKS)",
        [
            "All regulation, versioned (kb_version)",
            "AI Act + Omnibus, guidelines, FAQs,",
            "codes of practice, standards, national law",
            "requirements · test templates",
            "read-only for agents",
        ],
        "planned",
        "new",
    )
    s.box(
        540,
        115,
        420,
        165,
        "System dossier",
        [
            "/systems/<id>/ · versioned folder",
            "system card · architecture of components",
            "docs: specs, model cards, data sheets",
            "past runs, findings, evidence, open gaps",
        ],
        "planned",
        "new",
        mono_title=False,
    )
    s.box(
        1040,
        115,
        420,
        165,
        "Plugins (one per target)",
        [
            "plugin.yaml: access, pipeline place, I/O",
            "mlflow · REST · LLM chat · dataset",
            "+ docs, training-data description,",
            "data dictionary, expected behaviour",
            "secrets by reference only",
        ],
        "planned",
        "new",
        mono_title=False,
    )
    # Middle row
    s.box(
        40,
        375,
        420,
        130,
        "HITL gates",
        [
            "Engineer / AI Officer",
            "approve · edit · reject + reason",
            "plan, datasets, findings, change judge",
        ],
        "hitl",
        mono_title=False,
    )
    s.box(
        540,
        375,
        420,
        130,
        "agents: load_context",
        [
            "One run context from all sources",
            "→ scenarios, use cases, synthetic data,",
            "   tests, results, findings",
        ],
        "existing",
        "built",
    )
    s.box(
        1040,
        375,
        420,
        130,
        "sandbox",
        [
            "Adapter picked by access.type",
            "egress only to the target + mlflow",
            "calls the model / endpoint under test",
        ],
        "existing",
        "built",
    )
    # Memory row
    s.box(
        40,
        620,
        420,
        140,
        "Memory: per system",
        [
            "/memory/systems/<id>/ (files)",
            "corrections, rejections, quirks",
            "approved by the engineer",
        ],
        "planned",
        "new",
        mono_title=False,
    )
    s.box(
        540,
        620,
        420,
        140,
        "Memory: general (org)",
        [
            "/memory/org/ (files)",
            "rules for every system, promoted",
            "AI Officer approves, regression-checked",
        ],
        "planned",
        "new",
        mono_title=False,
    )
    s.box(
        1040,
        620,
        420,
        140,
        "Memory ledger (audit)",
        [
            "workspace_events: append-only",
            "who, what, why, when; every read",
            "retire · roll back · stale on law change",
        ],
        "output",
        mono_title=False,
    )
    # Context → agent
    s.arrow([(330, 282), (640, 373)], "regulation", P, label_at=0.5, dy=-4)
    s.arrow([(750, 282), (750, 373)], "the folder", P, dy=0)
    s.arrow([(1170, 282), (860, 373)], "what to call, how", P, dy=-4)
    # Agent ↔ gates / sandbox
    s.arrow([(538, 420), (462, 420)], "proposals", P)
    s.arrow([(962, 440), (1038, 440)], "run tests", P)
    # Feedback loop
    s.arrow([(250, 507), (250, 618)], "reject + reason", A)
    s.arrow([(462, 690), (538, 690)], "promote", A)
    s.arrow(
        [(250, 762), (250, 800), (1250, 800), (1250, 762)],
        "every write and every use is logged",
        M,
        dashed=True,
    )
    s.arrow([(420, 618), (640, 507)], "", A, dashed=True)
    s.arrow([(750, 618), (750, 507)], "retrieved + cited", A, dashed=True, dy=0)
    s.legend(
        40,
        845,
        [
            ("existing", "built (repo today)"),
            ("planned", "planned (MVP)"),
            ("hitl", "human gate"),
            ("output", "audit record"),
        ],
    )
    s.text(960, 860, "Blue: feedback becomes memory; dashed blue: memory read back", 13.5, A)
    return s


DIAGRAMS = {
    "containers": containers,
    "engineer-pipeline": engineer_pipeline,
    "reg-change": reg_change,
    "traceability": traceability,
    "agent-context": agent_context,
}


def main() -> None:
    svg_only = "--svg-only" in sys.argv
    for name, build in DIAGRAMS.items():
        diagram = build()
        (HERE / f"{name}.svg").write_text(diagram.render(), encoding="utf-8")
        if not svg_only:
            diagram.render_png(HERE / f"{name}.png")
        print(f"built {name}")


if __name__ == "__main__":
    main()
