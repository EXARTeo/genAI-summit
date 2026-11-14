"""Optional Firecrawl fallback (``FIRECRAWL_API_KEY``) for pages that answer
plain HTTP with a bot challenge. Returns the page as markdown."""

from __future__ import annotations

import httpx

from engine.fetch.http import FetchError, FetchResult


async def scrape(
    client: httpx.AsyncClient, url: str, *, api_key: str, base_url: str
) -> FetchResult:
    if not api_key:
        raise FetchError("firecrawl: FIRECRAWL_API_KEY not set")
    resp = await client.post(
        f"{base_url.rstrip('/')}/v1/scrape",
        json={"url": url, "formats": ["markdown"], "onlyMainContent": True},
        headers={"Authorization": f"Bearer {api_key}"},
        timeout=120,
    )
    if resp.status_code != 200:
        raise FetchError(f"firecrawl: HTTP {resp.status_code}")
    data = (resp.json() or {}).get("data") or {}
    markdown = data.get("markdown") or ""
    if not markdown.strip():
        raise FetchError("firecrawl: empty markdown")
    meta = data.get("metadata") or {}
    return FetchResult(
        url=url,
        final_url=meta.get("sourceURL") or meta.get("url") or url,
        status_code=200,
        content=markdown.encode("utf-8"),
        content_type="text/markdown",
    )
