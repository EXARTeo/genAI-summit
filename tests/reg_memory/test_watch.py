# ruff: noqa: E501, S106 - long fixture rows, fake test secrets
"""Watcher, demo mirror, releases/changes/requirements API, Firecrawl (mocked HTTP),
webhook signatures, proposed sources, notifications and no-key integrations."""

from __future__ import annotations

import json
from datetime import date

import httpx
import pytest
from kb_fixtures import CONSOLIDATED

from core.settings import NotifySettings, settings
from engine.catalog.loader import Catalog
from engine.demo import read_mirror
from engine.firecrawl import client as fc
from engine.firecrawl.webhook import changed_urls, sign, verify_signature
from engine.llm.gemini import Gemini
from engine.notify import notify_change
from engine.watch import discovery, proposals
from utils.watch import wait_all

CELLAR = "https://publications.europa.eu/resource/celex/02024R1689-20260727"
MIRROR = "http://localhost:8010/demo/mirror/art6-guidelines.html"
SPARQL = "https://publications.europa.eu/webapi/rdf/sparql"

CATALOG = """
sources:
  - id: ai-act-consolidated
    title: AI Act consolidated
    kind: consolidated
    binding: true
    fetcher: cellar
    celex: 02024R1689-20260727
    formats: [xhtml]
  - id: demo-art6-guideline-mirror
    title: Demo mirror
    kind: guideline
    binding: false
    status: draft
    fetcher: http
    url: http://localhost:8010/demo/mirror/art6-guidelines.html
    formats: [html]
    monitor: true
"""


@pytest.fixture
def stack(web, write_catalog, data_dir):
    """Fake web: Cellar serves the fixture act; the mirror URL serves the data-dir page."""
    write_catalog(CATALOG)
    web.add(
        CELLAR,
        lambda r: httpx.Response(
            200, content=CONSOLIDATED.encode(), headers={"Content-Type": "text/markdown"}
        ),
    )
    web.add(
        MIRROR,
        lambda r: httpx.Response(
            200, content=read_mirror(data_dir).encode(), headers={"Content-Type": "text/html"}
        ),
    )
    return web


async def test_no_key_integrations_report(api):
    data = (await api.get("/v1/integrations")).json()
    assert data["gemini"]["active"] is False and "heuristic" in data["gemini"]["fallback"]
    assert data["firecrawl"]["active"] is False
    assert data["firecrawl"]["features"]["search"] is False
    assert "search disabled" in data["firecrawl"]["fallback"]
    assert data["telegram"]["active"] is False and data["backend_notify"]["active"] is False
    assert data["watcher"]["scheduler"] == "off"


async def test_demo_mirror_change_produces_regchange(api, stack):
    # 1) first check: download + baseline release (auto-activated) + no RegChange
    first = (await api.post("/v1/watch/check-now", json={"wait": True})).json()
    assert first["status"] == "done", first
    assert set(first["changed_documents"]) == {"ai-act-consolidated", "demo-art6-guideline-mirror"}
    assert first["release"]["activated"] is True
    assert first["firecrawl"]["status"].startswith("disabled")
    assert first["discovery"]["firecrawl_search"]["status"].startswith("disabled")
    baseline = first["release"]["kb_version"]

    releases = (await api.get("/v1/releases")).json()
    assert releases["active"] == baseline and releases["items"][0]["status"] == "active"

    prov = (await api.get("/v1/provisions/AIA.10.2.f")).json()
    assert prov["kb_version"] == baseline and prov["path"] == ["Art 10", "para 2", "pt f"]
    assert any(i.startswith("INT.demo-art6-guideline-mirror") for i in prov["interpretations"])
    listed = (await api.get("/v1/provisions", params={"prefix": "AIA.10"})).json()
    assert {p["id"] for p in listed["items"]} >= {"AIA.10", "AIA.10.2", "AIA.10.2.f"}
    found = (await api.get("/v1/provisions", params={"q": "recruitment"})).json()
    assert [p["id"] for p in found["items"]] == ["AIA.ANNEX_III.4.a"]
    assert (await api.get("/v1/provisions/AIA.999")).status_code == 404
    # ranked search: one call answers with label, (inherited) title and a snippet
    assert prov["label"] == "Art. 10(2)(f)" and prov["title"] == "Data and data governance"
    assert prov["title_inherited"] is True
    hits = (await api.get("/v1/provisions/search", params={"q": "governance"})).json()
    assert hits["kb_version"] == baseline
    top = hits["items"][0]
    assert top["id"].startswith("AIA.10") and top["title"] == "Data and data governance"
    assert "governance" in top["snippet"].lower() and top["binding"] is True
    assert top["source"] == "ai-act-consolidated" and top["score"] > 0

    # 2) unchanged check: nothing new
    same = (
        await api.post(
            "/v1/watch/check-now",
            json={"source_ids": ["demo-art6-guideline-mirror"], "wait": True},
        )
    ).json()
    assert same["changed_documents"] == [] and "release" not in same

    # 3) edit the mirror live, check now -> candidate release + RegChange
    edit = await api.put(
        "/v1/demo/mirror",
        json={
            "find": "high-risk under Article 6(2).",
            "replace": "high-risk under Article 6(2), even when a human reviews the shortlist.",
        },
    )
    assert edit.status_code == 200 and "human reviews" in edit.json()["html"]
    page = await api.get("/demo/mirror/art6-guidelines.html")
    assert page.status_code == 200 and "human reviews" in page.text

    check = (
        await api.post(
            "/v1/watch/check-now",
            json={"source_ids": ["demo-art6-guideline-mirror"], "wait": True},
        )
    ).json()
    assert check["changed_documents"] == ["demo-art6-guideline-mirror"]
    rel = check["release"]
    assert rel["created"] is True and rel["change_id"] == f"RC-{rel['kb_version']}"
    assert rel["notified"] == {"backend": "skipped", "telegram": "skipped"}

    change = (await api.get(f"/v1/changes/{rel['change_id']}")).json()
    assert change["from_kb_version"] == baseline and change["provisions"] == []
    [entry] = change["interpretations"]
    assert entry["change"] == "changed" and entry["change_type"] == "new_interpretation"
    assert entry["classified_by"] == "heuristic"
    assert "human reviews" in entry["new_text"] and "+" in entry["diff"]
    assert "AIA.ANNEX_III.4.a" in entry["relates_to"]
    impacted = {i["requirement_id"] for i in change["impacted_requirements"]}
    assert "REQ.AIA.6.2.annex-iii-high-risk" in impacted
    assert (await api.get("/v1/changes")).json()["items"][0]["id"] == rel["change_id"]

    # 4) the candidate needs the explicit HITL activation
    cand = (await api.get(f"/v1/releases/{rel['kb_version']}")).json()
    assert cand["status"] == "candidate"
    act = await api.post(f"/v1/releases/{rel['kb_version']}/activate", json={"by": "engineer"})
    assert act.status_code == 200 and act.json()["status"] == "active"
    assert (await api.get(f"/v1/releases/{baseline}")).json()["status"] == "superseded"
    assert (await api.post("/v1/releases/2020.01.01-1/activate")).status_code == 404

    # 5) requirements applicability answers from the active release
    reqs = (
        await api.get(
            "/v1/requirements",
            params={
                "role": "provider",
                "risk_class": "high",
                "basis": "AIA.ANNEX_III.4.a",
                "date": date(2026, 11, 14).isoformat(),
            },
        )
    ).json()
    assert reqs["kb_version"] == rel["kb_version"]
    f = next(r for r in reqs["items"] if r["id"] == "REQ.AIA.10.2.f.bias-examination")
    assert f["valid_from"] == "2027-12-02" and f["in_force"] is False
    assert f["source_hash"].startswith("sha256:")
    tts = (await api.get("/v1/test-templates")).json()
    assert len(tts["items"]) == 8

    status = (await api.get("/v1/watch")).json()
    assert status["recent_checks"][0]["check_id"] == check["check_id"]
    assert (await api.get(f"/v1/watch/checks/{check['check_id']}")).json()["status"] == "done"


async def test_check_now_background_and_unknown_source(api, stack):
    resp = await api.post("/v1/watch/check-now", json={"source_ids": ["ai-act-consolidated"]})
    assert resp.status_code == 202
    await wait_all()
    done = (await api.get(f"/v1/watch/checks/{resp.json()['check_id']}")).json()
    assert done["status"] == "done"
    bad = await api.post("/v1/watch/check-now", json={"source_ids": ["nope"]})
    assert bad.status_code == 422


# ---- webhook ---------------------------------------------------------------------------------


def test_webhook_signature_helpers():
    body = b'{"type":"monitor.page"}'
    assert verify_signature("s3", body, sign("s3", body))
    assert not verify_signature("s3", body, sign("other", body))
    assert not verify_signature("s3", body, None)
    payload = {
        "type": "monitor.page",
        "data": [
            {"url": "https://a.eu/x", "status": "changed"},
            {"url": "https://a.eu/y", "status": "same"},
            {
                "metadata": {"sourceURL": "https://a.eu/z"},
                "changeTracking": {"changeStatus": "new"},
            },
        ],
    }
    assert changed_urls(payload) == ["https://a.eu/x", "https://a.eu/z"]


async def test_firecrawl_webhook_auth_and_trigger(api, stack, monkeypatch):
    monkeypatch.setattr(settings.fetch, "firecrawl_webhook_secret", _secret("hook-secret"))
    payload = {"type": "monitor.page", "data": [{"url": MIRROR, "status": "changed"}]}
    body = json.dumps(payload).encode()
    bad = await api.post(
        "/v1/webhooks/firecrawl", content=body, headers={"X-Firecrawl-Signature": "sha256=00"}
    )
    assert bad.status_code == 401
    unsigned = await api.post("/v1/webhooks/firecrawl", content=body)
    assert unsigned.status_code == 401
    ok = await api.post(
        "/v1/webhooks/firecrawl",
        content=body,
        headers={"X-Firecrawl-Signature": sign("hook-secret", body)},
    )
    assert ok.status_code == 202
    data = ok.json()
    assert data["matched_sources"] == ["demo-art6-guideline-mirror"] and data["check_id"]
    await wait_all()
    check = (await api.get(f"/v1/watch/checks/{data['check_id']}")).json()
    assert check["trigger"] == "firecrawl_webhook" and check["status"] == "done"


# ---- Firecrawl client (mocked HTTP) ----------------------------------------------------------


async def test_firecrawl_v2_calls(web):
    cfg = fc.FirecrawlConfig(api_key="fc-key", base_url="https://fc.test")
    seen: dict[str, dict] = {}

    def handler(name, response):
        def _h(request: httpx.Request) -> httpx.Response:
            seen[name] = json.loads(request.content)
            assert request.headers["authorization"] == "Bearer fc-key"
            return httpx.Response(200, json=response)

        return _h

    web.add(
        "https://fc.test/v2/scrape",
        handler(
            "scrape",
            {
                "success": True,
                "data": {
                    "markdown": "# x",
                    "changeTracking": {
                        "changeStatus": "changed",
                        "previousScrapeAt": "2026-11-13T10:00:00Z",
                        "visibility": "visible",
                        "diff": {"text": "-old\n+new"},
                    },
                },
            },
        ),
    )
    web.add(
        "https://fc.test/v2/search",
        handler("search", {"success": True, "data": {"web": [{"url": "https://ec.europa.eu/a"}]}}),
    )
    web.add(
        "https://fc.test/v2/map",
        handler(
            "map", {"success": True, "links": [{"url": "https://ec.europa.eu/b"}, "https://c"]}
        ),
    )
    async with web.client() as client:
        tracked = await fc.track_change(client, cfg, "https://ec.europa.eu/page", tag="src-1")
        results = await fc.search(client, cfg, "AI Act guidelines")
        links = await fc.map_site(client, cfg, "https://ec.europa.eu/")
    assert tracked["status"] == "changed" and tracked["diff"] == "-old\n+new"
    ct = seen["scrape"]["formats"][1]
    assert seen["scrape"]["formats"][0] == "markdown"
    assert ct == {"type": "changeTracking", "modes": ["git-diff"], "tag": "src-1"}
    assert seen["search"]["categories"] == ["gov", "pdf"]
    assert seen["search"]["includeDomains"] == ["europa.eu"] and seen["search"]["tbs"] == "qdr:m"
    assert results[0]["url"] == "https://ec.europa.eu/a"
    assert links == ["https://ec.europa.eu/b", "https://c"]
    with pytest.raises(fc.FirecrawlError):
        async with web.client() as client:
            await fc.search(client, fc.FirecrawlConfig(), "x")  # no key


# ---- discovery + proposed sources ---------------------------------------------------------------


async def test_sparql_discovery_and_proposals_flow(api, web, write_catalog, store):
    write_catalog(CATALOG)
    rows = {
        "results": {
            "bindings": [
                {
                    "celex": {"value": "32026R2487"},
                    "date": {"value": "2026-11-10"},
                    "title": {"value": "Implementing Regulation on AI regulatory sandboxes"},
                    "rel": {
                        "value": "http://publications.europa.eu/ontology/cdm#resource_legal_based_on_resource_legal"
                    },
                },
                {
                    "celex": {"value": "52026SC0775"},
                    "date": {"value": "2026-11-05"},
                    "title": {"value": "Staff working document on digital education"},
                    "rel": {"value": "http://publications.europa.eu/ontology/cdm#work_cites_work"},
                },
            ]
        }
    }
    seen: list[httpx.Request] = []

    async def fake_get(self, url, params=None, headers=None, timeout=None):
        seen.append(params)
        return httpx.Response(200, json=rows, request=httpx.Request("GET", url))

    async with web.client() as client:
        client.get = fake_get.__get__(client)
        hits = await discovery.cellar_sparql(client, SPARQL, date(2026, 10, 1))
    assert "32024R1689" in seen[0]["query"] and '"2026-10-01"' in seen[0]["query"]
    assert {h["celex"] for h in hits} == {"32026R2487", "52026SC0775"}

    from utils.state import get_catalog

    fresh = await proposals.add_candidates(store.root, get_catalog(), hits, Gemini())
    by_celex = {p["celex"]: p for p in fresh}
    good, noise = by_celex["32026R2487"], by_celex["52026SC0775"]
    assert good["status"] == "proposed" and good["triage"]["by"] == "heuristic"
    assert good["triage"]["kind"] == "regulation" and good["triage"]["binding"] is True
    assert noise["status"] == "ignored"
    # deduplicated on the next run
    assert await proposals.add_candidates(store.root, get_catalog(), hits, Gemini()) == []

    listed = (await api.get("/v1/sources/proposed")).json()["items"]
    assert [p["id"] for p in listed] == [good["id"]]
    assert (
        len((await api.get("/v1/sources/proposed", params={"status": "all"})).json()["items"]) == 2
    )

    acc = await api.post(f"/v1/sources/proposed/{good['id']}/accept", json={"by": "engineer"})
    assert acc.status_code == 200 and acc.json()["source_id"].startswith("disc-32026r2487")
    sources = {s["id"]: s for s in (await api.get("/v1/sources")).json()["items"]}
    new = sources[acc.json()["source_id"]]
    assert new["fetcher"] == "cellar" and new["celex"] == "32026R2487"
    assert (await api.post(f"/v1/sources/proposed/{good['id']}/accept")).status_code == 409
    rej = await api.post(f"/v1/sources/proposed/{noise['id']}/reject")
    assert rej.status_code == 200 and rej.json()["status"] == "rejected"
    assert (await api.post("/v1/sources/proposed/P-nope/accept")).status_code == 404


async def test_index_link_discovery_baseline_then_new(web, store):
    src = Catalog.model_validate(
        {
            "sources": [
                {
                    "id": "lib",
                    "title": "Library",
                    "kind": "other",
                    "binding": False,
                    "fetcher": "http",
                    "url": "https://ec.europa.eu/lib",
                    "discover": {"pattern": r"^https://ec\.europa\.eu/doc/"},
                }
            ]
        }
    ).sources[0]

    def page(*links: str) -> bytes:
        body = "".join(f'<a href="{u}">Doc {u[-1]}</a>' for u in links)
        return f"<html><body>{body}</body></html>".encode()

    def record(content: bytes) -> None:
        store.record(
            doc_id="lib",
            source_id="lib",
            url=src.url,
            content=content,
            ext="html",
            content_type="text/html",
        )

    async with web.client() as client:
        record(page("https://ec.europa.eu/doc/1", "https://other.eu/doc/2"))
        first, mode = await discovery.index_links(store, src, client, fc.FirecrawlConfig())
        record(page("https://ec.europa.eu/doc/1", "https://ec.europa.eu/doc/3"))
        second, _ = await discovery.index_links(store, src, client, fc.FirecrawlConfig())
    assert first == [] and mode == "page:baseline"
    assert [c["url"] for c in second] == ["https://ec.europa.eu/doc/3"]
    assert second[0]["found_by"] == "index_links" and second[0]["from_source"] == "lib"


# ---- notifications --------------------------------------------------------------------------


async def test_notifications_backend_and_telegram(web):
    calls: dict[str, httpx.Request] = {}

    def capture(name):
        def _h(request: httpx.Request) -> httpx.Response:
            calls[name] = request
            return httpx.Response(200, json={"ok": True})

        return _h

    web.add("http://backend:8000/internal/regulation/changes", capture("backend"))
    web.add("https://tg.test/botTOKEN/sendMessage", capture("telegram"))
    cfg = NotifySettings(
        BACKEND_INTERNAL_URL="http://backend:8000",
        BACKEND_INTERNAL_SECRET="int-secret",
        TELEGRAM_BOT_TOKEN="TOKEN",
        TELEGRAM_CHAT_ID="42",
        TELEGRAM_API_URL="https://tg.test",
    )
    change = {
        "id": "RC-2026.11.14-2",
        "from_kb_version": "2026.11.14-1",
        "to_kb_version": "2026.11.14-2",
        "summary": "1 provision(s) changed: AIA.10.2.f",
        "provisions": [
            {
                "id": "AIA.10.2.f",
                "kind": "provision",
                "change": "changed",
                "change_type": "substantive",
                "rationale": "Wording changed.",
                "diff": "-a\n+b",
            }
        ],
        "interpretations": [],
        "impacted_requirements": [{"requirement_id": "REQ.AIA.10.2.f.bias-examination"}],
    }
    async with web.client() as client:
        result = await notify_change(client, change, cfg)
    assert result == {"backend": "sent", "telegram": "sent"}
    assert calls["backend"].headers["x-internal-secret"] == "int-secret"
    assert json.loads(calls["backend"].content)["items"][0]["id"] == "AIA.10.2.f"
    text = json.loads(calls["telegram"].content)["text"]
    assert "AIA.10.2.f" in text and "REQ.AIA.10.2.f.bias-examination" in text
    async with web.client() as client:
        assert await notify_change(client, change, NotifySettings()) == {
            "backend": "skipped",
            "telegram": "skipped",
        }


def _secret(value: str):
    from pydantic import SecretStr

    return SecretStr(value)
