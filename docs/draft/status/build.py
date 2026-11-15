"""Build the status diagrams (SVG + PNG) for the project status page.

Reuses the shapes, renderers and brand colours of
``docs/architecture/diagrams/build.py`` (imported, not copied) and only adds four
status styles mapped to brand.json tokens: built = success, partial = warning,
missing = danger, not configured = muted.

Usage: ``uv run python docs/draft/status/build.py [--svg-only]``
"""

from __future__ import annotations

import importlib.util
import itertools
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]

_spec = importlib.util.spec_from_file_location(
    "architecture_diagrams", ROOT / "docs" / "architecture" / "diagrams" / "build.py"
)
arch = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(arch)

C = arch.C
OK, PART, MISS, OFF = C["success"], C["warning"], C["danger"], C["muted"]

# Status box styles: (stroke, fill, dash, title colour), registered next to the
# architecture styles so Svg.box and Svg.legend can use them.
arch.STYLES.update(
    {
        "built": (OK, C["background"], "", OK),
        "partial": (PART, C["background"], "", PART),
        "missing": (MISS, C["background"], "8 5", MISS),
        "unset": (OFF, C["surface"], "3 4", OFF),
    }
)
LEGEND = [
    ("built", "built / works live"),
    ("partial", "partial / tests only"),
    ("missing", "missing"),
    ("unset", "not configured (no key)"),
]


class StatusSvg(arch.Svg):
    """Svg with arrow markers for the status colours too."""

    def render(self) -> str:
        extra = "".join(
            f'<marker id="{arch._marker_id(c)}" viewBox="0 0 10 10" refX="9" refY="5" '
            f'markerWidth="8" markerHeight="8" orient="auto">'
            f'<path d="M0,0 L10,5 L0,10 z" fill="{c}"/></marker>'
            f'<marker id="{arch._marker_id(c)}s" viewBox="0 0 10 10" refX="1" refY="5" '
            f'markerWidth="8" markerHeight="8" orient="auto">'
            f'<path d="M10,0 L0,5 L10,10 z" fill="{c}"/></marker>'
            for c in (OK, PART, MISS)
        )
        return super().render().replace("<defs>", "<defs>" + extra, 1)


def containers_status() -> StatusSvg:
    s = StatusSvg(
        1500,
        940,
        "Mnamon stack: status",
        "Local stack on 2026-11-14 (evening): all 15 containers healthy, fake-LLM mode",
    )
    # External row
    s.box(480, 110, 220, 80, "Telegram", ["no token / chat id"], "unset", "not set", False)
    s.box(740, 110, 200, 80, "Gemini", ["no GOOGLE_API_KEY"], "unset", "not set", False)
    s.box(960, 110, 170, 80, "mcp_gateway", ["shared, running"], "built", "up")
    s.box(1170, 110, 280, 80, "Firecrawl", ["no key; plain HTTP fetch works"], "unset", "not set")
    # Main row
    s.actor(105, 350, "AI Engineer")
    s.box(
        180,
        290,
        250,
        122,
        "frontend",
        ["Vite + React · :8080", "run page crashes on real data", "no Start audit / Check now"],
        "partial",
        "partial",
    )
    s.box(
        480,
        290,
        260,
        122,
        "backend",
        ["systems, audits, approvals", "regulation proxy, Telegram", "accept does not call judge"],
        "built",
        "built",
    )
    s.box(
        800,
        290,
        260,
        122,
        "agents",
        ["live up to scenarios gate", "rest of the graph: tests only", "fake LLM (no Gemini key)"],
        "partial",
        "partial",
    )
    s.box(
        1150,
        290,
        300,
        122,
        "reg-memory",
        ["1,706 provisions · kb releases", "watcher · diff · classifier", "Check now: API only"],
        "built",
        "built",
    )
    # Stores and runners
    s.box(330, 510, 150, 96, "postgres", ["product DB", "+ agent_runtime"], "built")
    s.box(500, 510, 150, 96, "redis", ["cache · streams"], "built")
    s.box(
        800,
        510,
        260,
        96,
        "langfuse",
        ["traces per stage written", "spans not checked in UI"],
        "partial",
        "partial",
    )
    s.box(
        1150,
        510,
        300,
        96,
        "sandbox_runner",
        ["synthkit: profile works live", "run_tests: tests only"],
        "built",
        "built",
    )
    s.box(
        800,
        710,
        260,
        96,
        "model-gateway",
        ["seed models as REST", "MLflow models only"],
        "built",
        "built",
    )
    s.box(
        1150,
        710,
        300,
        96,
        "mlflow + mlflow-seed",
        ["SYS-001..004 imported", "4 models @champion"],
        "built",
        "built",
    )
    # Arrows: colour = status of that link
    s.arrow([(135, 350), (178, 350)], "", OFF)
    s.arrow([(430, 350), (478, 350)], "REST", PART, dy=-10)
    s.arrow([(740, 335), (798, 335)], "AG-UI", OK, dy=-10)
    s.arrow([(1060, 335), (1148, 335)], "requirements", OK, both=True, dy=-10)
    s.arrow([(590, 288), (590, 192)], "alerts, approvals", OFF, dashed=True, both=True, dy=-14)
    s.arrow([(840, 288), (840, 192)], "LLM calls", OFF, dashed=True, dy=-14)
    s.arrow([(1045, 288), (1045, 192)], "tools", OK, dy=-14)
    s.arrow([(1390, 192), (1390, 288)], "page changed", OFF, dashed=True, dy=-14)
    s.arrow([(720, 288), (720, 266), (1200, 266), (1200, 288)], "", OK, both=True)
    s.label(1110, 271, "proxy · notify", OK)
    s.arrow(
        [(700, 414), (700, 460), (880, 460), (880, 414)],
        "accept change → judge",
        MISS,
        dashed=True,
        dy=24,
    )
    s.arrow([(520, 414), (420, 508)], "", OK)
    s.arrow([(600, 414), (585, 508)], "", OK)
    s.arrow([(930, 414), (930, 508)], "traces", PART, dashed=True, dy=0)
    s.arrow([(1060, 400), (1148, 530)], "execute", OK, dy=-6)
    s.arrow([(1360, 608), (1360, 708)], "run per test", PART, dy=4)
    s.arrow([(1200, 608), (1062, 728)], "calls model", OK, dy=-6)
    s.arrow([(1060, 790), (1148, 790)], "loads", OK, dy=-6)
    # Left notes
    s.text(40, 680, "Top gaps", 15, C["text"], 700)
    notes = [
        "1  run page typed to mock shapes",
        "2  accept change never runs the judge",
        "3  no prior audits seeded",
        "4  delta report + stale: missing",
        "5  no Gemini / Telegram keys",
    ]
    for i, line in enumerate(notes):
        s.text(40, 708 + i * 22, line, 13.5, C["muted"])
    s.legend(40, 880, LEGEND)
    return s


DEMO_STEPS = [
    (
        "1 start audit",
        "partial",
        "API only",
        ["POST /v1/systems/{id}/audits", "works; no UI button"],
    ),
    (
        "2 pipeline + gates",
        "partial",
        "partial",
        ["live to approve-scenarios gate", "run page crashes on real data"],
    ),
    (
        "3 finding + critic",
        "partial",
        "tests",
        ["analyse → critic → report", "verified in tests only"],
    ),
    ("4 reject → memory", "partial", "tests", ["gate reject → remember", "lesson: tests only"]),
    (
        "5 next audit cites",
        "missing",
        "missing",
        ["memory_applied not filled", "no UI field for the citation"],
    ),
    (
        "6 regulation change",
        "partial",
        "API only",
        ["mirror + Check now via API", "no UI button / editor"],
    ),
    ("7 Telegram", "unset", "not set", ["code in backend", "no bot token or chat id"]),
    (
        "8 judge → re-run",
        "missing",
        "missing",
        ["accept never calls the judge", "no prior audits to impact"],
    ),
    ("9 delta report", "missing", "missing", ["delta report and stale", "findings not built"]),
    (
        "10 Langfuse trace",
        "partial",
        "partial",
        ["traces written per stage", "spans not checked in UI"],
    ),
]


def _flow(s, steps, top, w=250, h=124, gap=40, per_row=5, row_gap=70):
    """Lay out steps left to right, wrapping into rows joined by an elbow arrow."""
    pos = []
    for i, (title, style, tag, lines) in enumerate(steps):
        r, c = divmod(i, per_row)
        x, y = 40 + c * (w + gap + 6), top + r * (h + row_gap)
        s.box(x, y, w, h, title, lines, style, tag, mono_title=False)
        pos.append((x, y, style))
    for (x0, y0, _), (x1, y1, st1) in itertools.pairwise(pos):
        color = arch.STYLES[st1][0]
        if y1 == y0:
            s.arrow([(x0 + w, y0 + h / 2), (x1 - 2, y1 + h / 2)], "", color)
        else:
            mid = y0 + h + row_gap / 2
            s.arrow(
                [(x0 + w / 2, y0 + h), (x0 + w / 2, mid), (x1 + w / 2, mid), (x1 + w / 2, y1 - 2)],
                "",
                color,
            )
    return pos


def demo_flow_status() -> StatusSvg:
    s = StatusSvg(
        1500,
        560,
        "Demo spine: status",
        "Each step coloured by what works live today (2026-11-14 evening)",
    )
    _flow(s, DEMO_STEPS, 120)
    s.text(
        40,
        480,
        "Blocker: the audit run page crashes on real pipeline artifacts (UI typed to mock shapes).",
        14,
        MISS,
        600,
    )
    s.legend(40, 510, LEGEND)
    return s


PIPELINE_STEPS = [
    ("load_context", "built", "live", ["28 requirements", "kb 2026.11.14-1"]),
    ("profile_model", "built", "live", ["real synthkit; proxies:", "postcode, career gap"]),
    (
        "find_public_data",
        "partial",
        "no UI",
        ["gate skipped (< 0.5)", "no UI stage: SYS-002 stalls"],
    ),
    ("plan_scenarios", "built", "live", ["6 scenarios"]),
    ("analyse_scenarios", "built", "live", ["scenarios-check"]),
    ("gate: scenarios", "built", "live", ["audit parked here", "UI run page crashes"]),
    ("draft_spec", "partial", "tests", ["GenerationSpec draft"]),
    ("generate_data", "partial", "tests", ["synthkit generate"]),
    ("analyse_datasets", "partial", "tests", ["five dataset gates"]),
    ("gate: datasets", "partial", "tests", ["HITL approve datasets"]),
    ("run_tests", "partial", "tests", ["one MLflow run per test"]),
    ("analyse", "partial", "tests", ["findings with verdicts"]),
    ("critic", "partial", "tests", ["tries to overturn each"]),
    ("report", "missing", "gap", ["one main report, not", "engineer + management"]),
    ("memory_applied", "missing", "gap", ["fake model leaves empty", "UI has no field"]),
]


def pipeline_status() -> StatusSvg:
    s = StatusSvg(
        1500,
        640,
        "Engineer pipeline: status",
        "Live run on SYS-001 (fake LLM) vs steps verified only in tests",
    )
    _flow(s, PIPELINE_STEPS, 120, h=100, row_gap=60)
    s.legend(
        40,
        585,
        [("built", "works live"), ("partial", "tests only / partial"), ("missing", "missing")],
    )
    return s


DIAGRAMS = {
    "containers-status": containers_status,
    "demo-flow-status": demo_flow_status,
    "pipeline-status": pipeline_status,
}


def main() -> None:
    svg_only = "--svg-only" in sys.argv
    for name, build in DIAGRAMS.items():
        diagram = build()
        (HERE / f"{name}.svg").write_text(diagram.render(), encoding="utf-8", newline="\n")
        if not svg_only:
            diagram.render_png(HERE / f"{name}.png")
        print(f"built {name}")


if __name__ == "__main__":
    main()
