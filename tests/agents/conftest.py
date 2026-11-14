"""Shared fixtures for the agents-service suite.

The service runs for real, imported once, with no network: no Postgres (stores
are in-memory twins or unit-driven), no OpenAI (fake chat models), no MCP
gateway (off unless a test turns it on), Redis as fakeredis.

Isolation is explicit, because the modules are shared across tests: the whole
``settings`` tree is snapshotted and restored in place around every test, the
normalizer's per-run memory is cleared, and a stub ``agent_runtime`` pool is
wired so building a workspace works offline (nothing executes SQL against it).
"""

from __future__ import annotations

import copy
import hashlib
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

# tests/agents/ -> repo root -> product/agents (the service's import root).
SERVICE_ROOT = Path(__file__).resolve().parents[2] / "product" / "agents"
if str(SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVICE_ROOT))

# Settings are read at import time, so the environment is set before the app loads.
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("OPENAI_API_KEY", "test-openai-key")
os.environ.setdefault("INTERNAL_SERVICE_SECRET", "agents-test-secret")
os.environ.setdefault("MCP_GATEWAY_URL", "")
os.environ.setdefault("LANGFUSE_BASE_URL", "")
os.environ.setdefault("SANDBOX_EXECUTION_ENABLED", "false")
# The service ships no agent; the suite runs against a test-only definition.
os.environ.setdefault("AGENTS_DIR", str(Path(__file__).resolve().parent / "fixtures" / "agents"))
os.environ.setdefault("DEFAULT_AGENT_SLUG", "assistant")

import main  # noqa: E402
from core.security.internal_trust import INTERNAL_SECRET_HEADER  # noqa: E402
from core.settings import settings  # noqa: E402
from harness.agui import normalizer as normalizer_module  # noqa: E402
from harness.checkpointer import store as checkpointer_store  # noqa: E402
from harness.conversation_files import ConversationFiles, paths  # noqa: E402
from harness.conversation_files.store import FileEntry  # noqa: E402

#: The client id every test run carries (the backend's anonymous X-Client-Id).
CLIENT_ID = "11111111-1111-4111-8111-111111111111"
#: A second browser, for isolation tests.
OTHER_CLIENT_ID = "22222222-2222-4222-8222-222222222222"
CONVERSATION_ID = "c1"


def _is_model(value: object) -> bool:
    return hasattr(value, "__pydantic_fields_set__")


def _snapshot_settings(root: object) -> list[tuple[object, dict, set]]:
    """Every field of the settings tree, sub-models by reference (restored in place)."""
    captured: list[tuple[object, dict, set]] = []

    def walk(model: object) -> None:
        fields: dict = {}
        children: list[object] = []
        for name, value in vars(model).items():
            if _is_model(value):
                fields[name] = value
                children.append(value)
            else:
                try:
                    fields[name] = copy.deepcopy(value)
                except (TypeError, ValueError, copy.Error):
                    fields[name] = value
        captured.append((model, fields, set(getattr(model, "__pydantic_fields_set__", ()))))
        for child in children:
            walk(child)

    walk(root)
    return captured


def _restore_settings(captured: list[tuple[object, dict, set]]) -> None:
    for model, fields, fields_set in captured:
        model.__dict__.update(fields)
        model.__pydantic_fields_set__ = set(fields_set)


@pytest.fixture(autouse=True)
def _isolated_state():
    """Settings restored, per-run caches emptied and a stub pool wired, around every test."""
    snapshot = _snapshot_settings(settings)
    normalizer_module._RUNS.clear()
    checkpointer_store.set_runtime_pool(object())
    try:
        yield
    finally:
        checkpointer_store.set_runtime_pool(None)
        normalizer_module._RUNS.clear()
        _restore_settings(snapshot)


@pytest.fixture
def agents_service() -> SimpleNamespace:
    """The loaded service's main modules, for tests that patch across them."""
    return SimpleNamespace(main=main, settings=settings)


@pytest.fixture
def internal_headers() -> dict[str, str]:
    """The internal-caller header the backend sends."""
    secret = settings.proxy.internal_service_secret.get_secret_value()
    return {INTERNAL_SECRET_HEADER: secret}


@pytest_asyncio.fixture
async def client():
    """An HTTP client on the app (no lifespan: tests wire what a route needs)."""
    transport = ASGITransport(app=main.app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as async_client:
        yield async_client


def run_config(
    *,
    client_id: str = CLIENT_ID,
    conversation_id: str = CONVERSATION_ID,
    thread_id: str = "t1",
    run_id: str = "r1",
    **extra: Any,
) -> dict[str, Any]:
    """A contract ``Config`` block (``docs/agents-contract.md``)."""
    return {
        "run_config": {"configurable": {"thread_id": thread_id}},
        "context": {"client_id": client_id, "conversation_id": conversation_id, "run_id": run_id},
        **extra,
    }


class MemoryFileStore:
    """``ConversationFileStore`` in memory: content-addressed blobs per client,
    path rows naming them, no directory rows (the Postgres store's contract)."""

    def __init__(self) -> None:
        self.rows: dict[
            tuple[str, str], tuple[str, FileEntry]
        ] = {}  # (conv, path) -> (client, entry)
        self.blobs: dict[tuple[str, str], bytes] = {}  # (client, sha256) -> bytes

    def _scope(self, client_id: str, conversation_id: str) -> dict[str, FileEntry]:
        return {
            path: entry
            for (conv, path), (client, entry) in self.rows.items()
            if conv == conversation_id and client == client_id
        }

    def _gc(self, client_id: str) -> None:
        referenced = {(client, entry.sha256) for client, entry in self.rows.values()}
        for key in [k for k in self.blobs if k[0] == client_id and k not in referenced]:
            del self.blobs[key]

    def _put(self, client_id: str, conversation_id: str, path: str, data: bytes, agent_slug: str):
        sha256 = hashlib.sha256(data).hexdigest()
        self.blobs[(client_id, sha256)] = bytes(data)
        self.rows[(conversation_id, path)] = (
            client_id,
            FileEntry(path, len(data), sha256, agent_slug, datetime.now(UTC)),
        )
        self._gc(client_id)

    def _conflict(self, client_id, conversation_id, path, allow_existing):
        existing = self._scope(client_id, conversation_id)
        if not allow_existing and path in existing:
            return "exists"
        if any(other.startswith(path + "/") for other in existing):
            return "is_directory"
        if any(ancestor in existing for ancestor in paths.ancestors(path)):
            return "parent_is_file"
        return None

    async def list_files(self, client_id, conversation_id, directory="/"):
        prefix = directory.rstrip("/") + "/"
        return [
            entry
            for path, entry in sorted(self._scope(client_id, conversation_id).items())
            if path == directory or path.startswith(prefix)
        ]

    async def stat(self, client_id, conversation_id, path):
        return self._scope(client_id, conversation_id).get(path)

    async def read(self, client_id, conversation_id, path):
        return (await self.read_many(client_id, conversation_id, [path])).get(path)

    async def read_many(self, client_id, conversation_id, file_paths):
        rows = self._scope(client_id, conversation_id)
        return {
            path: self.blobs[(client_id, rows[path].sha256)] for path in file_paths if path in rows
        }

    async def create(self, client_id, conversation_id, path, data, *, agent_slug, run_id=None):
        conflict = self._conflict(client_id, conversation_id, path, allow_existing=False)
        if conflict is None:
            self._put(client_id, conversation_id, path, data, agent_slug)
        return conflict or "ok"

    async def replace(self, client_id, conversation_id, path, data, *, agent_slug, run_id=None):
        conflict = self._conflict(client_id, conversation_id, path, allow_existing=True)
        if conflict is None:
            self._put(client_id, conversation_id, path, data, agent_slug)
        return conflict or "ok"

    async def edit(self, client_id, conversation_id, path, transform, *, agent_slug, run_id=None):
        current = await self.read(client_id, conversation_id, path)
        if current is None:
            return False
        updated = transform(current)
        if updated is not None and updated != current:
            self._put(client_id, conversation_id, path, updated, agent_slug)
        return True


@pytest.fixture
def memory_file_store() -> MemoryFileStore:
    return MemoryFileStore()


@pytest.fixture
def conversation_files(memory_file_store) -> ConversationFiles:
    """One run's conversation files over the in-memory store."""
    return ConversationFiles(
        client_id=CLIENT_ID,
        conversation_id=CONVERSATION_ID,
        agent_slug="assistant",
        store=memory_file_store,
        run_id="r1",
    )
