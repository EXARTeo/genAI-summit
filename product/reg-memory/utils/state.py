"""Process-wide handles: the store, the catalog and the HTTP client factory.

Tests swap ``client_factory`` for one built on ``httpx.MockTransport``.
"""

from __future__ import annotations

from collections.abc import Callable

import httpx

from core.settings import settings
from engine.catalog.loader import Catalog, load_catalog
from engine.ingest import make_client
from engine.store import Store


def get_store() -> Store:
    return Store(settings.store.data_dir)


def get_catalog() -> Catalog:
    return load_catalog(settings.store.catalog_path)


def _default_client() -> httpx.AsyncClient:
    return make_client(settings.fetch)


client_factory: Callable[[], httpx.AsyncClient] = _default_client
