"""``search_public_datasets``: system context -> ranked candidates (+ report files).

Output (``dataset-candidates.json``)::

    {"kind": "public_dataset_candidates", "system": "SYS-002", "plugin": "credit-scorer",
     "queries": {...}, "sources": {"openml": {"ok": true, "found": 4}, ...},
     "candidates": [{id, slug, score, breakdown, licence, mapping, label, gaps, flags, ...}],
     "candidates_full": {id: Candidate.to_dict()},     # what fetch_public_dataset needs
     "status": "proposed"}                               # a human approves before fetching

The same payload is the ``public_dataset_candidates`` audit artifact's ``data``.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from harness.tools.public_datasets import sources
from harness.tools.public_datasets.context import build_queries
from harness.tools.public_datasets.models import Candidate, SystemContext
from harness.tools.public_datasets.rerank import rerank_with_gemini
from harness.tools.public_datasets.scoring import rank

ARTIFACT_KIND = "public_dataset_candidates"
#: Below this the best candidate is not worth a reference fit: recommend zero-shot.
GOOD_MATCH = 0.5


def _run(name: str, fn: Callable[[], list[Candidate]], status: dict) -> list[Candidate]:
    try:
        found = fn()
    except (httpx.HTTPError, sources.SourceError, ValueError, KeyError) as exc:
        status[name] = {"ok": False, "error": f"{type(exc).__name__}: {exc}"[:300]}
        return []
    status[name] = {"ok": True, "found": len(found)}
    return found


def search_public_datasets(
    ctx: SystemContext,
    *,
    client: httpx.Client | None = None,
    top: int = 8,
    per_source: int = 5,
    firecrawl_key: str | None = None,
    gemini_key: str | None = None,
    enabled: tuple[str, ...] = ("openml", "uci", "huggingface", "firecrawl"),
) -> dict[str, Any]:
    """Search every enabled catalogue for datasets matching one plugin's dictionary."""
    own = client is None
    client = client or sources.new_client()
    queries = build_queries(ctx)
    status: dict[str, dict] = {}
    found: list[Candidate] = []
    try:
        if "openml" in enabled:
            found += _run(
                "openml",
                lambda: sources.search_openml(
                    client, queries["openml_names"], queries["openml_tags"], per_source
                ),
                status,
            )
        if "uci" in enabled:
            found += _run(
                "uci", lambda: sources.search_uci(client, queries["uci"], per_source), status
            )
        if "huggingface" in enabled:
            found += _run(
                "huggingface",
                lambda: sources.search_huggingface(client, queries["free_text"], per_source),
                status,
            )
        if "firecrawl" in enabled:
            found += _run(
                "firecrawl",
                lambda: sources.search_firecrawl(
                    client, queries["free_text"], firecrawl_key, per_source
                ),
                status,
            )
            if not status["firecrawl"].get("found") and not (
                firecrawl_key or os.environ.get("FIRECRAWL_API_KEY")
            ):
                status["firecrawl"] = {"ok": False, "error": "FIRECRAWL_API_KEY not set: skipped"}
        ranked = rank(ctx, found, top=top)
        rerank = rerank_with_gemini(ctx, ranked, client=client, api_key=gemini_key)
    finally:
        if own:
            client.close()
    by_id = {c.id: c.to_dict() for c in found}
    best = next((c for c in ranked if c["fetchable"]), None)
    if best and best["score"] >= GOOD_MATCH and best["licence"]["status"] != "non_commercial":
        recommendation = {
            "mode": "reference_sample",
            "candidate": best["id"],
            "score": best["score"],
        }
    else:
        recommendation = {
            "mode": "zero_shot",
            "candidate": None,
            "reason": f"no fetchable candidate scores >= {GOOD_MATCH}",
        }
    return {
        "kind": ARTIFACT_KIND,
        "system": ctx.system_id,
        "plugin": ctx.plugin,
        "protected": ctx.protected + ctx.proxies,
        "scenario_needs": {
            "fields": ctx.scenario_fields,
            "protected": ctx.scenario_protected,
            "use_cases": ctx.use_cases,
        },
        "created_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "queries": queries,
        "sources": status,
        "candidates": ranked,
        "candidates_full": {c["id"]: by_id[c["id"]] for c in ranked},
        "rerank": rerank,
        "recommendation": recommendation,
        "status": "proposed",
        "next": "A human approves one candidate (or none) before fetch_public_dataset runs.",
    }


def to_markdown(result: dict[str, Any]) -> str:
    lines = [
        f"# Public dataset candidates: {result['system']} / {result['plugin']}",
        "",
        f"Domains: {', '.join(result['queries'].get('domains') or []) or 'none detected'}. "
        "Sources: "
        + ", ".join(
            f"{k} {'ok (' + str(v.get('found')) + ')' if v.get('ok') else 'skipped: ' + v['error']}"
            for k, v in result["sources"].items()
        )
        + ".",
        "",
        f"Recommendation: **{result['recommendation']['mode']}**"
        + (
            f" with `{result['recommendation']['candidate']}`."
            if result["recommendation"].get("candidate")
            else f" ({result['recommendation'].get('reason')})."
        )
        + "",
        "",
        "| # | Candidate | Source | Score | Schema | Protected | Label | Licence | Rows | Flags |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for i, c in enumerate(result["candidates"], 1):
        b = c["breakdown"]
        lines.append(
            f"| {i} | [{c['name']}]({c['url']}) | {c['source']} | {c['score']:.2f} | "
            f"{b['schema']:.2f} | {b['protected']:.2f} | {b['label']:.2f} | "
            f"{c['licence']['normalised']} ({c['licence']['status']}) | {c['n_rows'] or '?'} | "
            f"{', '.join(c['flags']) or '-'} |"
        )
    for c in result["candidates"][:3]:
        lines += ["", f"## {c['name']} ({c['id']})", ""]
        if c["mapping"]:
            lines += [
                "| Our field | Their column | Match | Transform |",
                "| --- | --- | --- | --- |",
            ]
            for f, m in c["mapping"].items():
                lines.append(
                    f"| {f} | {m['column']} | {m['score']} | {m.get('transform', '-')}"
                    f"{' (codes: needs a value map)' if m.get('needs_value_map') else ''} |"
                )
        if c["label"]:
            lines.append(f"\nLabel: `{c['label']['column']}` -> `{c['label']['name']}`.")
        lines.append(
            f"\nGaps (sampled zero-shot from the dictionary): {', '.join(c['gaps']) or 'none'}."
        )
        if c["protected_missing"]:
            lines.append(f"Protected/proxy fields missing: {', '.join(c['protected_missing'])}.")
    rr = result.get("rerank") or {}
    if rr.get("used"):
        lines += ["", "## Gemini notes", ""]
        lines += [f"- **{k}**: {v}" for k, v in (rr.get("notes") or {}).items()]
    lines += ["", "_Status: proposed. A human picks one candidate before anything is fetched._"]
    return "\n".join(lines) + "\n"


def write_report(result: dict[str, Any], out_dir: Path) -> dict[str, str]:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "dataset-candidates.json").write_text(
        json.dumps(result, indent=2, default=str), encoding="utf-8"
    )
    (out_dir / "dataset-candidates.md").write_text(to_markdown(result), encoding="utf-8")
    return {
        "json": str(out_dir / "dataset-candidates.json"),
        "md": str(out_dir / "dataset-candidates.md"),
    }
