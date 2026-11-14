"""Engine: fetch -> store -> extract -> diff, all against a fake web."""

from __future__ import annotations

import json

import httpx
from conftest import PDF_BYTES, make_docx

from engine.catalog.loader import Catalog, FollowLinks, load_catalog
from engine.diff import diff_pending
from engine.extract.stage import extract_pending
from engine.extract.text import extract_text, guess_ext
from engine.fetch.http import find_links
from engine.ingest import run_ingest

CELLAR = "https://publications.europa.eu/resource/celex/"


def _xhtml(body: str) -> bytes:
    return (
        '<?xml version="1.0" encoding="UTF-8"?><html xmlns="http://www.w3.org/1999/xhtml">'
        f"<body>{body}</body></html>"
    ).encode()


def _catalog(*entries: dict) -> Catalog:
    return Catalog.model_validate({"sources": list(entries)})


ACT = {
    "id": "act",
    "title": "Act",
    "kind": "regulation",
    "binding": True,
    "fetcher": "cellar",
    "celex": "32024R1689",
    "formats": ["xhtml"],
}


def test_shipped_catalog_is_valid():
    from core.settings import DEFAULT_CATALOG

    catalog = load_catalog(DEFAULT_CATALOG)
    ids = {s.id for s in catalog.sources}
    assert {"ai-act-consolidated", "ai-act", "digital-omnibus-ai", "gdpr"} <= ids
    assert catalog.get("gpsr-2023-988").enabled is False


async def test_cellar_new_then_same_then_changed_with_diff(web, store, config):
    body = {"text": '<p class="ti-art">Article 1</p><p>Old rule.</p>'}
    web.add(CELLAR + "32024R1689", lambda r: httpx.Response(200, content=_xhtml(body["text"])))
    catalog = _catalog(ACT)

    async with web.client() as client:
        run1 = await run_ingest(catalog, store, client, config)
        run2 = await run_ingest(catalog, store, client, config)
        body["text"] = '<p class="ti-art">Article 1</p><p>New rule.</p>'
        run3 = await run_ingest(catalog, store, client, config)

    assert [r["results"][0]["status"] for r in (run1, run2, run3)] == ["new", "same", "changed"]
    req = web.requests[0]
    assert req.headers["accept"] == "application/xhtml+xml"
    assert req.headers["accept-language"] == "eng"

    manifest = store.load_manifest("act")
    assert [v["status"] for v in manifest["versions"]] == ["new", "same", "changed"]
    raws = sorted(p.name for p in (store.root / "raw" / "act").iterdir())
    assert len(raws) == 2 and raws[0].startswith("v0001__") and raws[1].startswith("v0002__")
    text, entry = store.read_text("act")
    assert entry["version"] == 2 and "New rule." in text and "### Article 1" in text

    summary = json.loads((store.root / "diffs/act/v0001__v0002.json").read_text("utf-8"))
    assert summary["lines_added"] == 1 and summary["lines_removed"] == 1
    assert summary["changed_sections"] == ["Article 1"]
    assert run3["diff"]["diffed"] == 1
    assert (store.root / "runs" / f"{run3['run_id']}.json").exists()


async def test_stages_are_incremental(web, store, config):
    web.add(CELLAR + "32024R1689", lambda r: httpx.Response(200, content=_xhtml("<p>A</p>")))
    async with web.client() as client:
        await run_ingest(_catalog(ACT), store, client, config)
    assert extract_pending(store) == {"extracted": 0, "skipped": 1, "failed": 0}
    assert diff_pending(store)["diffed"] == 0


async def test_not_modified_is_same_without_download(web, store, config):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.headers.get("if-none-match") == '"v1"':
            return httpx.Response(304)
        return httpx.Response(200, content=_xhtml("<p>A</p>"), headers={"ETag": '"v1"'})

    web.add(CELLAR + "32024R1689", handler)
    async with web.client() as client:
        await run_ingest(_catalog(ACT), store, client, config)
        run = await run_ingest(_catalog(ACT), store, client, config)
        forced = await run_ingest(_catalog(ACT), store, client, config, force=True)
    assert run["results"][0]["status"] == "same"
    assert forced["results"][0]["status"] == "same"
    assert "if-none-match" not in web.requests[-1].headers


async def test_cellar_pdf_falls_back_to_pdfa2a(web, store, config):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.headers["accept"] == "application/pdf;type=pdfa2a":
            return httpx.Response(
                200, content=PDF_BYTES, headers={"Content-Type": "application/pdf"}
            )
        if request.headers["accept"] == "application/xhtml+xml":
            return httpx.Response(200, content=_xhtml("<p>A</p>"))
        return httpx.Response(404, text="no")

    web.add(CELLAR + "32024R1689", handler)
    async with web.client() as client:
        run = await run_ingest(
            _catalog({**ACT, "formats": ["xhtml", "pdf"]}), store, client, config, extract=False
        )
    docs = {d["doc_id"]: d["status"] for d in run["results"][0]["documents"]}
    assert docs == {"act": "new", "act.pdf": "new"}


async def test_challenge_without_firecrawl_is_recorded_as_failed(web, store, config):
    web.add("https://example.eu/page", lambda r: httpx.Response(202, content=b""))
    src = {
        "id": "page",
        "title": "P",
        "kind": "other",
        "binding": False,
        "fetcher": "http",
        "url": "https://example.eu/page",
    }
    async with web.client() as client:
        run = await run_ingest(_catalog(src), store, client, config)
    result = run["results"][0]
    assert result["status"] == "failed" and "FIRECRAWL_API_KEY" in result["error"]
    assert store.load_manifest("page")["versions"][0]["status"] == "failed"


async def test_retry_on_429_then_success(web, store, config):
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(429, headers={"Retry-After": "0"})
        return httpx.Response(200, content=_xhtml("<p>ok</p>"))

    web.add(CELLAR + "32024R1689", handler)
    async with web.client() as client:
        run = await run_ingest(_catalog(ACT), store, client, config)
    assert run["results"][0]["status"] == "new" and calls["n"] == 2


PAGE = """<html><body><main><h1>Guidelines</h1>
<p>Guidelines on X (English)</p><a download href="https://ec.europa.eu/newsroom/dae/redirection/document/1">Download</a>
<p>Guidelines on X (Greek)</p><a download href="https://ec.europa.eu/newsroom/dae/redirection/document/2">Download</a>
<p>Annex template</p><a href="https://ec.europa.eu/newsroom/dae/redirection/document/3">Download</a>
<p>Broken</p><a href="https://ec.europa.eu/newsroom/dae/redirection/document/4">Download</a>
<a href="https://evil.example/newsroom/dae/redirection/document/5">x</a>
</main></body></html>"""


def test_find_links_filters_languages_and_hosts():
    follow = FollowLinks(pattern=r"redirection/document/\d+$", max=10, hosts=["ec.europa.eu"])
    links = find_links(PAGE, "https://digital-strategy.ec.europa.eu/en/library/x", follow)
    assert [u.rsplit("/", 1)[-1] for u, _ in links] == ["1", "3", "4"]
    assert "(English)" in links[0][1]


async def test_follow_links_children_magic_bytes_and_error_pages(web, store, config):
    base = "https://ec.europa.eu/newsroom/dae/redirection/document/"
    web.add(
        "https://digital-strategy.ec.europa.eu/en/library/x",
        lambda r: httpx.Response(200, text=PAGE, headers={"Content-Type": "text/html"}),
    )
    web.add(
        base + "1",
        lambda r: httpx.Response(
            200,
            content=PDF_BYTES,
            headers={"Content-Type": "/", "Content-Disposition": 'attachment; filename="g_EN.pdf"'},
        ),
    )
    web.add(
        base + "3",
        lambda r: httpx.Response(
            200, content=make_docx("Τεχνητή νοημοσύνη", "Template"), headers={"Content-Type": "/"}
        ),
    )
    web.add(base + "4", lambda r: httpx.Response(200, text="<html><body>Error</body></html>"))
    src = {
        "id": "guide",
        "title": "G",
        "kind": "guideline",
        "binding": False,
        "fetcher": "http",
        "url": "https://digital-strategy.ec.europa.eu/en/library/x",
        "follow_links": {
            "pattern": r"redirection/document/\d+$",
            "max": 5,
            "hosts": ["ec.europa.eu"],
        },
    }
    async with web.client() as client:
        run = await run_ingest(_catalog(src), store, client, config)

    result = run["results"][0]
    assert result["status"] == "new"
    assert result["children"] == 3 and result["children_failed"] == 1
    child = store.load_manifest("guide.document-1")
    assert child["parent_id"] == "guide"
    assert child["versions"][0]["ext"] == "pdf"
    assert child["versions"][0]["filename"] == "g_EN.pdf"
    docx_text, _ = store.read_text("guide.document-3")
    assert "Τεχνητή νοημοσύνη" in docx_text
    assert store.load_manifest("guide.document-4")["versions"][0]["status"] == "failed"


def test_extractors_and_sniffing():
    assert guess_ext("/", PDF_BYTES) == "pdf"
    assert guess_ext("/", make_docx("a")) == "docx"
    assert guess_ext("text/html", b"<html></html>") == "html"
    html = (
        "<html><head><meta charset='utf-8'></head>"
        "<body><h2>Άρθρο 1</h2><p>Κείμενο</p></body></html>"
    )
    text = extract_text(html.encode("utf-8"), "html")
    assert "## Άρθρο 1" in text and "Κείμενο" in text
