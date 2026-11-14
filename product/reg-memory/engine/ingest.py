"""Ingest orchestrator: fetch every (selected) source into the store, then run the
extract and diff stages (each incremental, each also runnable on its own).

    python -m engine.ingest [--source ID ...] [--force] [--no-extract] [--no-diff]

``--force`` skips the conditional request (ETag / Last-Modified); unchanged
bytes are still recorded as ``same`` and never stored twice.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx

from core.logging import configure_logging, get_logger
from core.settings import FetchSettings, settings
from engine.catalog.loader import Catalog, Source, load_catalog
from engine.diff import diff_pending
from engine.extract.stage import extract_pending
from engine.extract.text import BINARY_EXTS, guess_ext
from engine.fetch.cellar import cellar_url, fetch_celex
from engine.fetch.http import (
    ChallengeError,
    FetchError,
    FetchOptions,
    FetchResult,
    HostThrottle,
    fetch,
    filename_from_headers,
    find_links,
)
from engine.firecrawl.client import FirecrawlConfig, scrape_result
from engine.store import Store, now_iso

logger = get_logger(__name__)


@dataclass
class IngestConfig:
    fetch: FetchOptions
    concurrency: int = 4
    firecrawl_api_key: str = ""
    firecrawl_url: str = "https://api.firecrawl.dev"

    @classmethod
    def from_settings(cls, s: FetchSettings) -> IngestConfig:
        return cls(
            fetch=FetchOptions(
                retries=s.retries,
                max_bytes=s.max_bytes,
                throttle=HostThrottle(s.host_interval_seconds),
            ),
            concurrency=s.concurrency,
            firecrawl_api_key=s.firecrawl_api_key.get_secret_value(),
            firecrawl_url=s.firecrawl_url,
        )


def make_client(s: FetchSettings) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        headers={"User-Agent": s.user_agent},
        timeout=httpx.Timeout(s.timeout_seconds, connect=15.0),
        limits=httpx.Limits(max_connections=s.concurrency * 2),
    )


def new_run_id() -> str:
    return f"{now_iso().replace(':', '').replace('-', '')[:15]}-{uuid.uuid4().hex[:8]}"


class Ingestor:
    def __init__(self, store: Store, client: httpx.AsyncClient, config: IngestConfig) -> None:
        self.store = store
        self.client = client
        self.config = config
        self.sem = asyncio.Semaphore(config.concurrency)

    # ---- one document -------------------------------------------------------------

    async def _get(self, doc_id: str, url: str, force: bool, fetcher: str, **kw) -> FetchResult:
        manifest = self.store.load_manifest(doc_id) or {}
        cond = (
            {}
            if force
            else {
                "etag": manifest.get("etag"),
                "last_modified": manifest.get("last_modified"),
            }
        )
        async with self.sem:
            if fetcher == "firecrawl" and self.config.firecrawl_api_key:
                return await self._firecrawl(url)  # without a key: plain HTTP below
            if fetcher == "cellar":
                return await fetch_celex(
                    self.client, kw["celex"], kw["fmt"], **cond, options=self.config.fetch
                )
            try:
                return await fetch(self.client, url, **cond, options=self.config.fetch)
            except ChallengeError as exc:
                if not self.config.firecrawl_api_key:
                    raise FetchError(f"{exc}; no FIRECRAWL_API_KEY for fallback") from exc
                return await self._firecrawl(url)

    async def _firecrawl(self, url: str) -> FetchResult:
        cfg = FirecrawlConfig(self.config.firecrawl_api_key, self.config.firecrawl_url)
        return await scrape_result(self.client, cfg, url)

    async def fetch_doc(
        self,
        source: Source,
        doc_id: str,
        url: str,
        *,
        force: bool,
        fetcher: str,
        parent_id: str | None = None,
        label: str | None = None,
        expect_binary: bool = False,
        **kw,
    ) -> dict[str, Any]:
        common = {
            "doc_id": doc_id,
            "source_id": source.id,
            "url": url,
            "parent_id": parent_id,
            "label": label,
        }
        try:
            res = await self._get(doc_id, url, force, fetcher, **kw)
        except (FetchError, httpx.HTTPError) as exc:
            logger.warning("fetch_failed", "Fetch failed", doc_id=doc_id, url=url, error=str(exc))
            return self.store.record(**common, error=str(exc) or type(exc).__name__)
        filename = filename_from_headers(res.headers)
        ext = None if res.not_modified else guess_ext(res.content_type, res.content, filename)
        if expect_binary and ext is not None and ext not in BINARY_EXTS:
            # e.g. a wrong newsroom document id: an HTML error page with HTTP 200.
            error = f"expected a pdf/docx document, got .{ext} (error page?)"
            logger.warning("fetch_failed", "Unexpected content", doc_id=doc_id, error=error)
            return self.store.record(**common, error=error)
        entry = self.store.record(
            **common,
            content=res.content if not res.not_modified else None,
            ext=ext,
            filename=filename,
            final_url=res.final_url,
            content_type=res.content_type,
            etag=res.etag,
            last_modified=res.last_modified,
            not_modified=res.not_modified,
        )
        logger.info(
            "document_fetched",
            "Document fetched",
            doc_id=doc_id,
            fetch_status=entry["status"],
            bytes=entry["bytes"],
        )
        return entry

    # ---- one source -------------------------------------------------------------

    async def ingest_source(self, source: Source, force: bool) -> dict[str, Any]:
        result: dict[str, Any] = {
            "source_id": source.id,
            "documents": [],
            "children": 0,
            "children_failed": 0,
        }
        if source.fetcher == "cellar":
            for i, fmt in enumerate(source.formats):
                doc_id = source.id if i == 0 else f"{source.id}.{fmt}"
                entry = await self.fetch_doc(
                    source,
                    doc_id,
                    cellar_url(source.celex or ""),
                    force=force,
                    fetcher="cellar",
                    celex=source.celex,
                    fmt=fmt,
                )
                result["documents"].append({"doc_id": doc_id, **_brief(entry)})
        else:
            entry = await self.fetch_doc(
                source,
                source.id,
                source.url or "",
                force=force,
                fetcher=source.fetcher,
                expect_binary=set(source.formats) <= {"pdf", "docx"},
            )
            result["documents"].append({"doc_id": source.id, **_brief(entry)})
            if source.follow_links and entry["status"] != "failed":
                await self._children(source, force, result)
        main = result["documents"][0]
        result.update(
            status=main["status"],
            bytes=sum(d["bytes"] for d in result["documents"]),
            error=main.get("error"),
        )
        return result

    async def _children(self, source: Source, force: bool, result: dict[str, Any]) -> None:
        latest = self.store.latest_raw(source.id)
        if not latest or latest[1].get("ext") not in {"html", "xhtml"}:
            return
        raw, entry = latest
        page = raw.decode("utf-8", errors="replace")
        assert source.follow_links is not None  # noqa: S101
        links = find_links(page, entry["final_url"], source.follow_links)
        entries = await asyncio.gather(
            *[
                self.fetch_doc(
                    source,
                    f"{source.id}.{_slug(url)}",
                    url,
                    force=force,
                    fetcher="http",
                    parent_id=source.id,
                    label=label,
                    expect_binary=source.follow_links.binary,
                )
                for url, label in links
            ]
        )
        for (_url, _label), child in zip(links, entries, strict=True):
            result["children"] += 1
            result["children_failed"] += child["status"] == "failed"
            result["documents"].append({"doc_id": f"{source.id}.{_slug(_url)}", **_brief(child)})


def _brief(entry: dict[str, Any]) -> dict[str, Any]:
    out = {k: entry.get(k) for k in ("status", "version", "bytes")}
    if entry.get("error"):
        out["error"] = entry["error"]
    return out


def _slug(url: str) -> str:
    parts = [p for p in urlsplit(url).path.split("/") if p]
    tail = parts[-1] if parts else "index"
    if tail.isdigit() and len(parts) > 1:
        tail = f"{parts[-2]}-{tail}"
    tail = re.sub(r"\.(pdf|html?)$", "", tail.lower())
    return re.sub(r"[^a-z0-9_-]+", "-", tail).strip("-")[:60] or "doc"


async def run_ingest(
    catalog: Catalog,
    store: Store,
    client: httpx.AsyncClient,
    config: IngestConfig,
    *,
    source_ids: list[str] | None = None,
    force: bool = False,
    run_id: str | None = None,
    catalog_path: Path | None = None,
    extract: bool = True,
    diff: bool = True,
) -> dict[str, Any]:
    """Fetch the selected (enabled) sources, then extract and diff. Returns the run record."""
    run_id = run_id or new_run_id()
    if source_ids:
        unknown = [i for i in source_ids if not catalog.get(i)]
        if unknown:
            raise ValueError(f"unknown source ids: {unknown}")
        sources = [catalog.get(i) for i in source_ids]
    else:
        sources = [s for s in catalog.sources if s.enabled]
    run: dict[str, Any] = {
        "run_id": run_id,
        "status": "running",
        "started_at": now_iso(),
        "finished_at": None,
        "force": force,
        "source_ids": [s.id for s in sources],
        "results": [],
        "catalog_snapshot": store.snapshot_catalog(run_id, catalog_path) if catalog_path else None,
    }
    store.save_run(run)
    logger.info("ingest_started", "Ingest run started", run_id=run_id, sources=len(sources))
    ingestor = Ingestor(store, client, config)
    try:
        results = await asyncio.gather(
            *[ingestor.ingest_source(s, force) for s in sources if s is not None],
            return_exceptions=True,
        )
        for src, res in zip(sources, results, strict=True):
            if isinstance(res, BaseException):
                logger.error(
                    "source_failed", "Source ingest crashed", source_id=src.id, error=repr(res)
                )
                res = {
                    "source_id": src.id,
                    "status": "failed",
                    "error": repr(res),
                    "bytes": 0,
                    "children": 0,
                    "children_failed": 0,
                    "documents": [],
                }
            run["results"].append(res)
        ids = [s.id for s in sources]
        if extract:
            run["extract"] = await asyncio.to_thread(extract_pending, store, ids)
        if diff:
            run["diff"] = await asyncio.to_thread(diff_pending, store, ids)
        run["status"] = "done"
    except Exception as exc:
        run.update(status="failed", error=repr(exc))
        raise
    finally:
        run["finished_at"] = now_iso()
        store.save_run(run)
        logger.info(
            "ingest_finished", "Ingest run finished", run_id=run_id, run_status=run["status"]
        )
    return run


async def _main(args: argparse.Namespace) -> dict[str, Any]:
    catalog = load_catalog(settings.store.catalog_path)
    async with make_client(settings.fetch) as client:
        return await run_ingest(
            catalog,
            Store(settings.store.data_dir),
            client,
            IngestConfig.from_settings(settings.fetch),
            source_ids=args.sources,
            force=args.force,
            catalog_path=settings.store.catalog_path,
            extract=not args.no_extract,
            diff=not args.no_diff,
        )


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", action="append", dest="sources")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--no-extract", action="store_true")
    parser.add_argument("--no-diff", action="store_true")
    args = parser.parse_args(argv)
    configure_logging()
    run = asyncio.run(_main(args))
    rows = [
        {
            k: r.get(k)
            for k in ("source_id", "status", "bytes", "children", "children_failed", "error")
        }
        for r in run["results"]
    ]
    print(
        json.dumps(
            {
                "run_id": run["run_id"],
                "status": run["status"],
                "results": rows,  # noqa: T201
                "extract": run.get("extract"),
                "diff": run.get("diff"),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
