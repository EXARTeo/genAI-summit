"""Discovery: find documents the catalog does not have yet.

(a) **Index-page link diff**: catalog sources with ``discover`` (library / FAQ /
    Service Desk index pages). Links matching the pattern that were not on the
    page at the previous check are candidates. With ``FIRECRAWL_API_KEY`` the
    links come from Firecrawl ``map``; without, from the page we just fetched.
    The first look at a page only records a baseline.
(b) **Cellar SPARQL**: acts that amend, are based on, or cite 32024R1689 with a
    document date since the last check.
(c) **Firecrawl search** (keyed only): ``categories: [gov, pdf]`` on europa.eu,
    recent results (``tbs``).

    <data>/discovery/links/<source_id>.json   last seen links per index page
    <data>/discovery/state.json               sparql_since, last runs
"""

from __future__ import annotations

import json
import re
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx

from core.logging import get_logger
from engine.catalog.loader import FollowLinks, Source
from engine.fetch.http import find_links
from engine.firecrawl import client as firecrawl
from engine.firecrawl.client import FirecrawlConfig
from engine.store import Store, _atomic_write, now_iso

logger = get_logger(__name__)

AI_ACT_CELEX = "32024R1689"
SPARQL_LOOKBACK_DAYS = 30
SEARCH_QUERIES = [
    "AI Act guidelines high-risk classification Article 6",
    "AI Act Service Desk FAQ new questions",
    "Regulation (EU) 2024/1689 implementing act guidelines",
]

SPARQL_QUERY = """PREFIX cdm: <http://publications.europa.eu/ontology/cdm#>
PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
SELECT DISTINCT ?celex ?date ?title ?rel WHERE {
  VALUES ?rel { cdm:resource_legal_amends_resource_legal
                cdm:resource_legal_based_on_resource_legal cdm:work_cites_work }
  ?act ?rel ?target .
  ?target cdm:resource_legal_id_celex "%(celex)s"^^xsd:string .
  ?act cdm:resource_legal_id_celex ?celex .
  ?act cdm:work_date_document ?date .
  FILTER(?date >= "%(since)s"^^xsd:date)
  OPTIONAL {
    ?exp cdm:expression_belongs_to_work ?act ;
         cdm:expression_uses_language %(lang)s ;
         cdm:expression_title ?title .
  }
} ORDER BY DESC(?date) LIMIT %(limit)d"""

_RELATIONS = {
    "resource_legal_amends_resource_legal": "amends",
    "resource_legal_based_on_resource_legal": "based_on",
    "work_cites_work": "cites",
}


def _state_path(data_dir: Path) -> Path:
    return Path(data_dir) / "discovery" / "state.json"


def load_state(data_dir: Path) -> dict[str, Any]:
    path = _state_path(data_dir)
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def save_state(data_dir: Path, state: dict[str, Any]) -> None:
    _atomic_write(_state_path(data_dir), json.dumps(state, indent=2).encode("utf-8"))


# ---- (a) index-page link diff --------------------------------------------------------------


async def index_links(
    store: Store, source: Source, client: httpx.AsyncClient, fc: FirecrawlConfig
) -> tuple[list[dict[str, Any]], str]:
    """New links on ``source``'s index page since the last look: ``(candidates, mode)``."""
    assert source.discover is not None  # noqa: S101 - caller filters
    follow = FollowLinks(
        pattern=source.discover.pattern,
        max=source.discover.max,
        hosts=source.discover.hosts,
        exclude_label=None,
        binary=False,
    )
    links: dict[str, str] = {}
    mode = "page"
    if fc.active and source.url:
        try:
            url_re = re.compile(follow.pattern)
            for u in await firecrawl.map_site(client, fc, source.url, limit=follow.max):
                if url_re.search(u):
                    links[u] = ""
            mode = "firecrawl_map"
        except firecrawl.FirecrawlError as exc:
            logger.warning("discovery_map_failed", "Firecrawl map failed", error=str(exc))
    if mode == "page":
        latest = store.latest_raw(source.id)
        if latest and latest[1].get("ext") in {"html", "xhtml"}:
            page = latest[0].decode("utf-8", errors="replace")
            for u, label in find_links(page, latest[1]["final_url"], follow)[: follow.max]:
                links[u.split("#")[0]] = label
    links.pop((source.url or "").split("#")[0], None)
    path = store.root / "discovery" / "links" / f"{source.id}.json"
    previous = json.loads(path.read_text(encoding="utf-8")) if path.exists() else None
    _atomic_write(
        path,
        json.dumps({"checked_at": now_iso(), "mode": mode, "links": links}, indent=2).encode(),
    )
    if previous is None:
        return [], f"{mode}:baseline"
    old = set(previous.get("links") or {})
    return [
        {
            "url": u,
            "title": (label or u)[-200:],
            "found_by": "index_links",
            "from_source": source.id,
        }
        for u, label in links.items()
        if u not in old
    ], mode


# ---- (b) Cellar SPARQL -------------------------------------------------------------------------


async def cellar_sparql(
    client: httpx.AsyncClient, endpoint: str, since: date, *, limit: int = 100
) -> list[dict[str, Any]]:
    query = SPARQL_QUERY % {
        "celex": AI_ACT_CELEX,
        "since": since.isoformat(),
        "limit": limit,
        "lang": "<http://publications.europa.eu/resource/authority/language/ENG>",
    }
    resp = await client.get(
        endpoint,
        params={"query": query},
        headers={"Accept": "application/sparql-results+json"},
        timeout=90,
    )
    resp.raise_for_status()
    rows = (resp.json().get("results") or {}).get("bindings") or []
    by_celex: dict[str, dict[str, Any]] = {}
    for row in rows:
        celex = row.get("celex", {}).get("value")
        if not celex or celex == AI_ACT_CELEX:
            continue
        rel = _RELATIONS.get(row.get("rel", {}).get("value", "").rsplit("#", 1)[-1], "cites")
        item = by_celex.setdefault(
            celex,
            {
                "celex": celex,
                "url": f"https://publications.europa.eu/resource/celex/{celex}",
                "title": (row.get("title") or {}).get("value") or celex,
                "date": (row.get("date") or {}).get("value"),
                "relation": rel,
                "found_by": "cellar_sparql",
            },
        )
        # strongest relation wins: amends > based_on > cites
        order = ["cites", "based_on", "amends"]
        if order.index(rel) > order.index(item["relation"]):
            item["relation"] = rel
    return list(by_celex.values())


# ---- (c) Firecrawl search -----------------------------------------------------------------------


async def firecrawl_search(
    client: httpx.AsyncClient, fc: FirecrawlConfig, queries: list[str] | None = None
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for q in queries or SEARCH_QUERIES:
        try:
            results = await firecrawl.search(client, fc, q, tbs="qdr:m", limit=10)
        except firecrawl.FirecrawlError as exc:
            logger.warning("discovery_search_failed", "Firecrawl search failed", error=str(exc))
            continue
        for r in results:
            if r.get("url"):
                out.append(
                    {
                        "url": r["url"],
                        "title": r.get("title") or r["url"],
                        "description": r.get("description"),
                        "category": r.get("category"),
                        "query": q,
                        "found_by": "firecrawl_search",
                    }
                )
    return out


# ---- all of it -----------------------------------------------------------------------------------


async def discover(
    store: Store,
    sources: list[Source],
    client: httpx.AsyncClient,
    fc: FirecrawlConfig,
    sparql_url: str,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Run (a), (b), (c); returns ``(candidates, report)``."""
    report: dict[str, Any] = {"index_links": {}, "cellar_sparql": None, "firecrawl_search": None}
    candidates: list[dict[str, Any]] = []
    for src in sources:
        if not src.discover:
            continue
        try:
            found, mode = await index_links(store, src, client, fc)
            report["index_links"][src.id] = {"mode": mode, "new": len(found)}
            candidates += found
        except Exception as exc:  # one page must not stop discovery
            report["index_links"][src.id] = {"error": repr(exc)}
    state = load_state(store.root)
    today = datetime.now(UTC).date()
    since = (
        date.fromisoformat(state["sparql_since"])
        if state.get("sparql_since")
        else today - timedelta(days=SPARQL_LOOKBACK_DAYS)
    )
    try:
        hits = await cellar_sparql(client, sparql_url, since)
        report["cellar_sparql"] = {"since": since.isoformat(), "hits": len(hits)}
        candidates += hits
        state["sparql_since"] = today.isoformat()
    except (httpx.HTTPError, ValueError) as exc:
        report["cellar_sparql"] = {"since": since.isoformat(), "error": type(exc).__name__}
    if fc.active:
        hits = await firecrawl_search(client, fc)
        report["firecrawl_search"] = {"hits": len(hits)}
        candidates += hits
    else:
        report["firecrawl_search"] = {"status": "disabled: FIRECRAWL_API_KEY not set"}
    state["last_run_at"] = now_iso()
    save_state(store.root, state)
    return candidates, report
