"""EU law from the Publications Office Cellar API, by CELEX number.

eur-lex.europa.eu answers bots with an HTTP 202 challenge, so it is never used;
Cellar serves the same documents with content negotiation.
"""

from __future__ import annotations

import httpx

from engine.fetch.http import FetchError, FetchOptions, FetchResult, fetch

CELLAR_BASE = "https://publications.europa.eu/resource/celex/"
# Media types tried in order. Recent OJ acts (e.g. 32026R1744) only have a
# PDF/A-2a manifestation, which a plain application/pdf request 404s on.
ACCEPT = {
    "xhtml": ["application/xhtml+xml", "text/html"],
    "html": ["text/html", "application/xhtml+xml"],
    "pdf": ["application/pdf", "application/pdf;type=pdfa2a", "application/pdf;type=pdfa1a"],
}


def cellar_url(celex: str) -> str:
    return CELLAR_BASE + celex


async def fetch_celex(
    client: httpx.AsyncClient,
    celex: str,
    fmt: str,
    *,
    etag: str | None = None,
    last_modified: str | None = None,
    options: FetchOptions | None = None,
) -> FetchResult:
    last: FetchError | None = None
    for accept in ACCEPT[fmt]:
        try:
            return await fetch(
                client,
                cellar_url(celex),
                headers={"Accept": accept, "Accept-Language": "eng"},
                etag=etag,
                last_modified=last_modified,
                options=options,
            )
        except FetchError as exc:
            if "HTTP 404" not in str(exc) and "HTTP 406" not in str(exc):
                raise
            last = exc
    raise FetchError(f"no {fmt} manifestation for CELEX {celex}: {last}")
