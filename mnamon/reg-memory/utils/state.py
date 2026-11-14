"""Process-wide handles: the store, the catalog, the knowledge base, the HTTP client
factory and the lock that serialises everything writing manifests (ingest, checks).

Tests swap ``client_factory`` for one built on ``httpx.MockTransport``.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable

import httpx

from core.settings import settings
from engine.catalog.loader import Catalog, load_catalog
from engine.ingest import make_client
from engine.kb.releases import KnowledgeBase
from engine.store import Store
from engine.watch.proposals import overlay_path

DEMO_SOURCE_ID = "demo-art6-guideline-mirror"


def get_store() -> Store:
    return Store(settings.store.data_dir)


def get_catalog() -> Catalog:
    """The git catalog + accepted proposals (data overlay) + the demo mirror URL."""
    return load_catalog(
        settings.store.catalog_path,
        overlay=overlay_path(settings.store.data_dir),
        url_overrides={DEMO_SOURCE_ID: settings.watch.demo_mirror_url},
    )


def get_kb() -> KnowledgeBase:
    return KnowledgeBase(get_store())


def _default_client() -> httpx.AsyncClient:
    return make_client(settings.fetch)


client_factory: Callable[[], httpx.AsyncClient] = _default_client

_locks: dict[int, asyncio.Lock] = {}


def write_lock() -> asyncio.Lock:
    """One ingest / check at a time (they share manifests); one lock per event loop."""
    key = id(asyncio.get_running_loop())
    if key not in _locks:
        _locks.clear()  # a new loop (tests): the old lock is unusable anyway
        _locks[key] = asyncio.Lock()
    return _locks[key]
