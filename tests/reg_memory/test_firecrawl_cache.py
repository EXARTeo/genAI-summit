"""Firecrawl credit guards: answers cached on disk, non-public URLs never sent."""

from __future__ import annotations

import httpx
import pytest

from engine.firecrawl import client as fc


def _web(calls: list[httpx.Request]) -> httpx.AsyncClient:
    def handle(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(
            200, json={"success": True, "data": {"markdown": "# page", "metadata": {}}}
        )

    return httpx.AsyncClient(transport=httpx.MockTransport(handle))


@pytest.mark.parametrize(
    ("url", "blocked"),
    [
        ("http://localhost:8010/demo/mirror/art6-guidelines.html", True),
        ("http://reg-memory:8010/demo/mirror/art6-guidelines.html", True),
        ("http://10.0.0.5/page", True),
        ("http://127.0.0.1/page", True),
        ("http://host.docker.internal/page", True),
        ("https://digital-strategy.ec.europa.eu/en/policies", False),
        ("https://8.8.8.8/page", False),
    ],
)
def test_unreachable_urls(url, blocked):
    assert fc.unreachable_url(url) is blocked


async def test_scrapes_are_cached_and_private_urls_cost_nothing(tmp_path):
    calls: list[httpx.Request] = []
    cfg = fc.FirecrawlConfig(
        api_key="fc-key", base_url="https://fc.test", cache_dir=tmp_path, cache_minutes=60
    )
    async with _web(calls) as client:
        first = await fc.scrape(client, cfg, "https://ec.europa.eu/page")
        again = await fc.scrape(client, cfg, "https://ec.europa.eu/page")
        assert first == again and len(calls) == 1
        await fc.scrape(client, cfg, "https://ec.europa.eu/other")
        assert len(calls) == 2
        with pytest.raises(fc.FirecrawlError, match="not public"):
            await fc.track_change(client, cfg, "http://localhost:8010/demo", tag="demo")
        assert len(calls) == 2
    assert len(list(tmp_path.glob("*.json"))) == 2


async def test_no_cache_dir_means_every_call_goes_out(tmp_path):
    calls: list[httpx.Request] = []
    cfg = fc.FirecrawlConfig(api_key="fc-key", base_url="https://fc.test")
    async with _web(calls) as client:
        await fc.scrape(client, cfg, "https://ec.europa.eu/page")
        await fc.scrape(client, cfg, "https://ec.europa.eu/page")
    assert len(calls) == 2


async def test_expired_entries_are_refetched(tmp_path, monkeypatch):
    calls: list[httpx.Request] = []
    cfg = fc.FirecrawlConfig(
        api_key="fc-key", base_url="https://fc.test", cache_dir=tmp_path, cache_minutes=1
    )
    now = [1_000_000.0]
    monkeypatch.setattr(fc.time, "time", lambda: now[0])
    async with _web(calls) as client:
        await fc.scrape(client, cfg, "https://ec.europa.eu/page")
        now[0] += 120
        await fc.scrape(client, cfg, "https://ec.europa.eu/page")
    assert len(calls) == 2
