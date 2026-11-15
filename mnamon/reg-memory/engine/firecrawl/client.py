"""Firecrawl REST v2 (https://docs.firecrawl.dev): scrape (+ change tracking),
search, map. Every call needs ``FIRECRAWL_API_KEY``; callers check
:attr:`FirecrawlConfig.active` first and fall back to their own fetch + hash
diff without it.

Credits are scarce (free plan: 500), so every call is **cached on disk**
(``<data>/firecrawl-cache/<sha256 of path + body>.json``) for
``FIRECRAWL_CACHE_MINUTES`` (default 360; 0 = off), and a URL Firecrawl cannot reach
(localhost, private or Docker-internal hosts, e.g. the demo mirror) is never sent:
it raises :class:`FirecrawlError` without spending a credit.
"""

from __future__ import annotations

import hashlib
import ipaddress
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

from core.settings import FetchSettings, settings
from engine.fetch.http import FetchError, FetchResult

#: Search filters used by discovery (v2 ``categories``: research, pdf, developer, gov).
DEFAULT_CATEGORIES = ["gov", "pdf"]
DEFAULT_DOMAINS = ["europa.eu"]


@dataclass
class FirecrawlConfig:
    api_key: str = ""
    base_url: str = "https://api.firecrawl.dev"
    #: Where answers are cached (``None`` = no cache) and for how long.
    cache_dir: Path | None = None
    cache_minutes: int = 0

    @classmethod
    def from_settings(cls, s: FetchSettings | None = None) -> FirecrawlConfig:
        s = s or settings.fetch
        return cls(
            api_key=s.firecrawl_api_key.get_secret_value(),
            base_url=s.firecrawl_url,
            cache_dir=Path(settings.store.data_dir) / "firecrawl-cache",
            cache_minutes=s.firecrawl_cache_minutes,
        )

    @property
    def active(self) -> bool:
        return bool(self.api_key)


class FirecrawlError(FetchError):
    pass


_PRIVATE_SUFFIXES = (".local", ".internal", ".lan", ".localhost")


def unreachable_url(url: str | None) -> bool:
    """A URL Firecrawl's cloud cannot fetch: localhost, a private IP or a bare Docker name."""
    if not url:
        return False
    host = (urlparse(url).hostname or "").lower()
    if not host or host == "localhost" or host.endswith(_PRIVATE_SUFFIXES) or "." not in host:
        return True
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    return ip.is_private or ip.is_loopback or ip.is_link_local


def _cache_path(cfg: FirecrawlConfig, path: str, body: dict[str, Any]) -> Path | None:
    if cfg.cache_dir is None or cfg.cache_minutes <= 0:
        return None
    key = hashlib.sha256(f"{path}\n{json.dumps(body, sort_keys=True)}".encode()).hexdigest()
    return cfg.cache_dir / f"{key}.json"


def _cached(file: Path | None, minutes: int) -> dict[str, Any] | None:
    if file is None or not file.exists():
        return None
    try:
        entry = json.loads(file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if time.time() - float(entry.get("at") or 0) > minutes * 60:
        return None
    data = entry.get("data")
    return data if isinstance(data, dict) else None


async def _post(
    client: httpx.AsyncClient, cfg: FirecrawlConfig, path: str, body: dict[str, Any]
) -> dict[str, Any]:
    if not cfg.active:
        raise FirecrawlError("firecrawl: FIRECRAWL_API_KEY not set")
    if unreachable_url(body.get("url")):
        raise FirecrawlError(f"firecrawl {path}: {body.get('url')} is not public; not sent")
    file = _cache_path(cfg, path, body)
    hit = _cached(file, cfg.cache_minutes)
    if hit is not None:
        return hit
    resp = await client.post(
        f"{cfg.base_url.rstrip('/')}/v2/{path}",
        json=body,
        headers={"Authorization": f"Bearer {cfg.api_key}"},
        timeout=120,
    )
    if resp.status_code != 200:
        raise FirecrawlError(f"firecrawl {path}: HTTP {resp.status_code}")
    data = resp.json() or {}
    if data.get("success") is False:
        raise FirecrawlError(f"firecrawl {path}: {data.get('error') or 'failed'}")
    if file is not None:
        file.parent.mkdir(parents=True, exist_ok=True)
        tmp = file.with_suffix(".tmp")
        tmp.write_text(json.dumps({"at": time.time(), "data": data}), encoding="utf-8")
        tmp.replace(file)
    return data


async def scrape(
    client: httpx.AsyncClient,
    cfg: FirecrawlConfig,
    url: str,
    *,
    change_tracking: bool = False,
    modes: list[str] | None = None,
    tag: str | None = None,
    schema: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """``POST /v2/scrape``; returns ``data`` (markdown, metadata, changeTracking?)."""
    formats: list[Any] = ["markdown"]  # change tracking compares markdown: always included
    if change_tracking:
        ct: dict[str, Any] = {"type": "changeTracking"}
        if modes:
            ct["modes"] = modes
        if tag:
            ct["tag"] = tag
        if schema and "json" in (modes or []):
            ct["schema"] = schema
        formats.append(ct)
    body = {"url": url, "formats": formats, "onlyMainContent": True}
    return (await _post(client, cfg, "scrape", body)).get("data") or {}


async def scrape_result(client: httpx.AsyncClient, cfg: FirecrawlConfig, url: str) -> FetchResult:
    """A scrape as a :class:`FetchResult` (markdown bytes): the bot-challenge fallback."""
    data = await scrape(client, cfg, url)
    markdown = data.get("markdown") or ""
    if not markdown.strip():
        raise FirecrawlError("firecrawl: empty markdown")
    meta = data.get("metadata") or {}
    return FetchResult(
        url=url,
        final_url=meta.get("sourceURL") or meta.get("url") or url,
        status_code=200,
        content=markdown.encode("utf-8"),
        content_type="text/markdown",
    )


async def track_change(
    client: httpx.AsyncClient,
    cfg: FirecrawlConfig,
    url: str,
    tag: str,
    *,
    schema: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Scrape with change tracking (git-diff mode, plus json mode when ``schema``; per-source
    ``tag`` = its own comparison history).

    Returns ``{status, previous_scrape_at, diff, json}``; status is new/same/changed/removed,
    or ``unknown`` when Firecrawl omitted the object (e.g. a history lookup timeout).
    """
    modes = ["git-diff", "json"] if schema else ["git-diff"]
    data = await scrape(client, cfg, url, change_tracking=True, modes=modes, tag=tag, schema=schema)
    ct = data.get("changeTracking") or {}
    diff = ct.get("diff") or {}
    return {
        "status": ct.get("changeStatus") or "unknown",
        "previous_scrape_at": ct.get("previousScrapeAt"),
        "visibility": ct.get("visibility"),
        "diff": diff.get("text") if isinstance(diff, dict) else None,
        "json": ct.get("json"),
        "warning": data.get("warning"),
    }


async def search(
    client: httpx.AsyncClient,
    cfg: FirecrawlConfig,
    query: str,
    *,
    categories: list[str] | None = None,
    include_domains: list[str] | None = None,
    tbs: str | None = "qdr:m",
    limit: int = 10,
) -> list[dict[str, Any]]:
    """``POST /v2/search``; returns the web results (url, title, description, category)."""
    body: dict[str, Any] = {
        "query": query,
        "limit": limit,
        "sources": ["web"],
        "categories": DEFAULT_CATEGORIES if categories is None else categories,
        "includeDomains": DEFAULT_DOMAINS if include_domains is None else include_domains,
    }
    if tbs:
        body["tbs"] = tbs
    data = (await _post(client, cfg, "search", body)).get("data") or {}
    if isinstance(data, list):  # flat shape (with scrapeOptions)
        return data
    return list(data.get("web") or [])


async def map_site(
    client: httpx.AsyncClient,
    cfg: FirecrawlConfig,
    url: str,
    *,
    search_term: str | None = None,
    limit: int = 200,
) -> list[str]:
    """``POST /v2/map``; returns the URLs found on/under ``url``."""
    body: dict[str, Any] = {"url": url, "limit": limit}
    if search_term:
        body["search"] = search_term
    links = (await _post(client, cfg, "map", body)).get("links") or []
    return [lk["url"] if isinstance(lk, dict) else str(lk) for lk in links if lk]
