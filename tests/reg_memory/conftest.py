"""Shared fixtures for the reg-memory suite.

No network: every fetch goes through an ``httpx.MockTransport`` that serves a
fake web (``FakeWeb``). Each test gets its own data directory.
"""

from __future__ import annotations

import io
import os
import sys
import zipfile
from collections.abc import Callable
from pathlib import Path

import httpx
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

# tests/reg_memory/ -> repo root -> mnamon/reg-memory (the service's import root).
SERVICE_ROOT = Path(__file__).resolve().parents[2] / "mnamon" / "reg-memory"
if str(SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVICE_ROOT))

# Settings are read at import time, so the environment is set before the app loads.
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("REG_MEMORY_HOST_INTERVAL_SECONDS", "0")
# No paid / external integrations in tests, whatever the developer's .env says.
for _name in (
    "FIRECRAWL_API_KEY",
    "FIRECRAWL_WEBHOOK_SECRET",
    "GOOGLE_API_KEY",
    "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_CHAT_ID",
    "BACKEND_INTERNAL_URL",
):
    os.environ[_name] = ""
os.environ["REG_MEMORY_WATCH_INTERVAL_MINUTES"] = "0"

from core.security.rate_limit import backend as rate_limit_backend  # noqa: E402
from core.settings import settings  # noqa: E402
from engine.fetch.http import FetchOptions  # noqa: E402
from engine.ingest import IngestConfig  # noqa: E402
from engine.store import Store  # noqa: E402

PDF_BYTES = b"%PDF-1.4\n% fake pdf for tests\n"


def make_docx(*paragraphs: str) -> bytes:
    body = "".join(f"<w:p><w:r><w:t>{p}</w:t></w:r></w:p>" for p in paragraphs)
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f"<w:body>{body}</w:body></w:document>"
    )
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("word/document.xml", xml.encode("utf-8"))
    return buf.getvalue()


class FakeWeb:
    """URL -> handler(request) -> httpx.Response; records every request."""

    def __init__(self) -> None:
        self.routes: dict[str, Callable[[httpx.Request], httpx.Response]] = {}
        self.requests: list[httpx.Request] = []

    def add(self, url: str, handler: Callable[[httpx.Request], httpx.Response]) -> None:
        self.routes[url] = handler

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        handler = self.routes.get(str(request.url))
        if handler is None:
            return httpx.Response(404, text="not found")
        return handler(request)

    def client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(self.handle))


@pytest.fixture
def web() -> FakeWeb:
    return FakeWeb()


@pytest.fixture
def data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(settings.store, "data_dir", tmp_path / "data")
    return tmp_path / "data"


@pytest.fixture
def store(data_dir: Path) -> Store:
    return Store(data_dir)


@pytest.fixture
def config() -> IngestConfig:
    return IngestConfig(fetch=FetchOptions(retries=2, backoff_seconds=0), concurrency=4)


@pytest.fixture
def write_catalog(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    def _write(yaml_text: str) -> Path:
        path = tmp_path / "sources.yaml"
        path.write_text(yaml_text, encoding="utf-8")
        monkeypatch.setattr(settings.store, "catalog_path", path)
        return path

    return _write


@pytest_asyncio.fixture
async def api(data_dir: Path, web: FakeWeb, monkeypatch: pytest.MonkeyPatch):
    from main import app
    from utils import state

    monkeypatch.setattr(state, "client_factory", web.client)
    rate_limit_backend.reset()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client
