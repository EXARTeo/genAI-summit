"""Generic HTTP fetching with retries, a size cap, conditional requests, challenge
detection and link following."""

from __future__ import annotations

import asyncio
import html as html_lib
import re
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlsplit

import httpx

from engine.catalog.loader import FollowLinks

RETRY_STATUSES = {429, 500, 502, 503, 504}


class FetchError(Exception):
    """The document could not be fetched (recorded as a failed version)."""


class ChallengeError(FetchError):
    """The site answered with a bot/WAF challenge (e.g. HTTP 202, empty body)."""


@dataclass
class FetchResult:
    url: str
    final_url: str
    status_code: int
    content: bytes = b""
    content_type: str = ""
    etag: str | None = None
    last_modified: str | None = None
    not_modified: bool = False
    headers: dict[str, str] = field(default_factory=dict)


_FILENAME_RE = re.compile(r"""filename\*?=(?:UTF-8'')?["']?([^"';]+)""", re.I)


def filename_from_headers(headers: dict[str, str]) -> str | None:
    """The file name from ``Content-Disposition`` (newsroom downloads send ``Content-Type: /``)."""
    m = _FILENAME_RE.search(headers.get("content-disposition", ""))
    return m.group(1).strip() if m else None


class HostThrottle:
    """At most one request per ``interval`` seconds to the same host.

    digital-strategy.ec.europa.eu and ai-act-service-desk.ec.europa.eu answer
    429 to faster clients.
    """

    def __init__(self, interval: float) -> None:
        self.interval = interval
        self._locks: dict[str, asyncio.Lock] = {}
        self._last: dict[str, float] = {}

    async def wait(self, url: str) -> None:
        if self.interval <= 0:
            return
        host = (urlsplit(url).hostname or "").lower()
        lock = self._locks.setdefault(host, asyncio.Lock())
        async with lock:
            loop = asyncio.get_running_loop()
            delay = self._last.get(host, -1e9) + self.interval - loop.time()
            if delay > 0:
                await asyncio.sleep(delay)
            self._last[host] = loop.time()


@dataclass
class FetchOptions:
    retries: int = 3
    max_bytes: int = 50 * 1024 * 1024
    backoff_seconds: float = 1.0
    max_retry_after_seconds: float = 60.0
    throttle: HostThrottle | None = None


class _Retryable(FetchError):
    def __init__(self, message: str, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


def _retry_after(value: str | None) -> float | None:
    try:
        return float(value) if value else None
    except ValueError:
        return None  # an HTTP date: fall back to backoff


async def fetch(
    client: httpx.AsyncClient,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    etag: str | None = None,
    last_modified: str | None = None,
    options: FetchOptions | None = None,
) -> FetchResult:
    """GET ``url`` (redirects followed). 304 -> ``not_modified``; 202/empty -> ChallengeError.

    429/5xx and transport errors are retried with exponential backoff (a 429's
    ``Retry-After`` is respected, capped).
    """
    opts = options or FetchOptions()
    req_headers = dict(headers or {})
    if etag:
        req_headers["If-None-Match"] = etag
    if last_modified:
        req_headers["If-Modified-Since"] = last_modified
    last_exc: Exception | None = None
    wait = 0.0
    for attempt in range(opts.retries + 1):
        if attempt:
            await asyncio.sleep(wait)
        if opts.throttle:
            await opts.throttle.wait(url)
        backoff = opts.backoff_seconds * 2**attempt
        try:
            return await _get_once(client, url, req_headers, opts.max_bytes)
        except ChallengeError:
            raise
        except _Retryable as exc:
            last_exc = exc
            wait = min(max(backoff, exc.retry_after or 0.0), opts.max_retry_after_seconds)
        except httpx.TransportError as exc:
            last_exc = exc
            wait = backoff
    raise FetchError(f"giving up on {url}: {last_exc}")


async def _get_once(
    client: httpx.AsyncClient, url: str, headers: dict[str, str], max_bytes: int
) -> FetchResult:
    async with client.stream("GET", url, headers=headers, follow_redirects=True) as resp:
        if resp.status_code in RETRY_STATUSES:
            raise _Retryable(
                f"HTTP {resp.status_code}", _retry_after(resp.headers.get("retry-after"))
            )
        result = FetchResult(
            url=url,
            final_url=str(resp.url),
            status_code=resp.status_code,
            content_type=resp.headers.get("content-type", "").split(";")[0].strip().lower(),
            etag=resp.headers.get("etag"),
            last_modified=resp.headers.get("last-modified"),
            headers={k.lower(): v for k, v in resp.headers.items()},
        )
        if resp.status_code == 304:
            result.not_modified = True
            return result
        if resp.status_code == 202:
            raise ChallengeError(f"HTTP 202 challenge from {urlsplit(url).hostname}")
        if resp.status_code >= 400:
            raise FetchError(f"HTTP {resp.status_code}")
        declared = int(resp.headers.get("content-length") or 0)
        if declared > max_bytes:
            raise FetchError(f"too large: {declared} bytes > {max_bytes}")
        chunks: list[bytes] = []
        size = 0
        async for chunk in resp.aiter_bytes():
            size += len(chunk)
            if size > max_bytes:
                raise FetchError(f"too large: > {max_bytes} bytes")
            chunks.append(chunk)
        result.content = b"".join(chunks)
    if not result.content.strip():
        raise ChallengeError(f"empty body from {urlsplit(url).hostname}")
    return result


_HREF = re.compile(r"""<a\b[^>]*?\bhref\s*=\s*["']([^"']+)["'][^>]*>(.*?)</a>""", re.I | re.S)
_TAG = re.compile(r"<[^>]+>")


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", html_lib.unescape(_TAG.sub(" ", text))).strip()


def find_links(page_html: str, base_url: str, follow: FollowLinks) -> list[tuple[str, str]]:
    """Links on the page matching ``follow``: ``[(absolute_url, label)]``, deduplicated.

    The label is the link's own text plus the text just before it (download
    cards put the document title there, e.g. "... (AI Act) (English)").
    """
    url_re = re.compile(follow.pattern)
    include = re.compile(follow.include_label) if follow.include_label else None
    exclude = re.compile(follow.exclude_label) if follow.exclude_label else None
    hosts = {h.lower() for h in follow.hosts} or {(urlsplit(base_url).hostname or "").lower()}
    seen: set[str] = set()
    out: list[tuple[str, str]] = []
    prev_end = 0
    for m in _HREF.finditer(page_html):
        before = _clean(page_html[max(prev_end, m.start() - 1500) : m.start()])[-200:]
        prev_end = m.end()
        url = urljoin(base_url, html_lib.unescape(m.group(1)))
        if url in seen or not url_re.search(url):
            continue
        if (urlsplit(url).hostname or "").lower() not in hosts:
            continue
        label = before
        anchor = _clean(m.group(2))
        if anchor and anchor.lower() not in {"download", "pdf"}:
            label = f"{before} {anchor}".strip()
        if exclude and exclude.search(before):
            continue
        if include and not include.search(label):
            continue
        seen.add(url)
        out.append((url, label))
        if len(out) >= follow.max:
            break
    return out
