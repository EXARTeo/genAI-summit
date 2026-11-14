"""Shared fixtures for the backend test suite.

The app runs for real against a per-test SQLite database and an in-process
fakeredis, and the agents service is an ``httpx.MockTransport``.
"""

from __future__ import annotations

import base64
import os
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest
import pytest_asyncio
from fakeredis import aioredis as fake_aioredis
from fastapi_pagination import add_pagination
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# tests/backend/ -> repo root -> product/backend (the service's import root).
SERVICE_ROOT = Path(__file__).resolve().parents[2] / "product" / "backend"
if str(SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVICE_ROOT))

# Settings are read at import time, so the environment is set before the app loads.
os.environ.setdefault("APP_ENV", "test")
# A placeholder so core.settings loads; every test gets its own engine below.
_BOOTSTRAP_DB = (Path(tempfile.gettempdir()) / "pytest-bootstrap-backend.db").as_posix()
os.environ.setdefault("DATABASE_URL", f"sqlite+aiosqlite:///{_BOOTSTRAP_DB}")
os.environ.setdefault("AGENTS_SERVICE_URL", "http://agents.test")
os.environ.setdefault("LANGFUSE_PUBLIC_KEY", "")
os.environ.setdefault("LANGFUSE_SECRET_KEY", "")
# Rate limits run for real against fakeredis. The suite shares one client id
# and one IP, so the ceilings are lifted; 429 behaviour has its own tests.
for _name in (
    "IP_RATE_LIMIT_MAX_CALLS",
    "INFERENCE_RATE_LIMIT_MAX_ATTEMPTS",
    "MESSAGE_RATE_LIMIT_MAX_ATTEMPTS",
    "CONVERSATION_RATE_LIMIT_MAX_ATTEMPTS",
    "SEARCH_RATE_LIMIT_MAX_ATTEMPTS",
    "TASK_READ_RATE_LIMIT_MAX_ATTEMPTS",
    "TASK_MUTATE_RATE_LIMIT_MAX_ATTEMPTS",
    "WS_CONNECT_RATE_LIMIT_MAX_ATTEMPTS",
):
    os.environ.setdefault(_name, "1000000")

from redis_fastapi.deps import _PoolState  # noqa: E402

from core.database import Base, ConversationTable, MessageTable, get_db  # noqa: E402
from main import app as backend_app  # noqa: E402
from utils.conversation_channel import conversation_channel  # noqa: E402
from utils.event_log import event_log as run_event_log  # noqa: E402
from utils.task_streams import task_streams  # noqa: E402

#: The client id every test request sends (X-Client-Id).
CLIENT_ID = "11111111-1111-4111-8111-111111111111"
#: A second browser, for isolation tests.
OTHER_CLIENT_ID = "22222222-2222-4222-8222-222222222222"
AGENT_SLUG = "test-agent"

# The SDK pool is normally created by the app lifespan, which these tests never
# run. Seed it with fakeredis so the global budget and per-route limits execute
# their real code path.
_sdk_fake_redis = fake_aioredis.FakeRedis(decode_responses=True)
_sdk_pool_state = _PoolState()
_sdk_pool_state.async_pool = _sdk_fake_redis.connection_pool
_sdk_pool_state._async_client = _sdk_fake_redis
backend_app.state._redis = _sdk_pool_state

# Every raw-Redis singleton the app holds; left alone each would dial a real
# (absent) server. Holders with a second pool for blocking stream reads too.
_REDIS_HOLDERS = (run_event_log, conversation_channel, task_streams)
_REDIS_READERS = (run_event_log, conversation_channel, task_streams)
_app_redis = fake_aioredis.FakeRedis(decode_responses=True)


def _sqlite_encode(data: bytes, encoding: str) -> str:
    if encoding == "base64":
        return base64.b64encode(data).decode("ascii").replace("\n", "")
    raise ValueError(f"Unsupported encoding: {encoding}")


def utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


@pytest_asyncio.fixture(autouse=True)
async def _in_process_redis():
    """Point every Redis singleton at the in-process server, emptied first."""
    await _app_redis.flushall()
    await _sdk_fake_redis.flushall()
    for holder in _REDIS_HOLDERS:
        holder._client = _app_redis
    for holder in _REDIS_READERS:
        holder._reader = _app_redis
    yield
    for holder in _REDIS_HOLDERS:
        holder._client = None
    for holder in _REDIS_READERS:
        holder._reader = None


@pytest_asyncio.fixture
async def db_engine(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{(tmp_path / 'backend_test.db').as_posix()}")

    @event.listens_for(engine.sync_engine, "connect")
    def _register_sqlite_functions(dbapi_connection, _connection_record):
        dbapi_connection.create_function("encode", 2, _sqlite_encode)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest.fixture
def session_factory(db_engine):
    return async_sessionmaker(bind=db_engine, class_=AsyncSession, expire_on_commit=False)


@pytest.fixture
def app(session_factory):
    add_pagination(backend_app)

    async def override_get_db():
        async with session_factory() as session:
            yield session

    backend_app.dependency_overrides[get_db] = override_get_db
    try:
        yield backend_app
    finally:
        backend_app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def client(app):
    """An HTTP client that sends the test browser's X-Client-Id on every request."""
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport, base_url="http://testserver", headers={"X-Client-Id": CLIENT_ID}
    ) as async_client:
        yield async_client


@pytest_asyncio.fixture
async def other_client(app):
    """A second browser (different X-Client-Id), for isolation tests."""
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport, base_url="http://testserver", headers={"X-Client-Id": OTHER_CLIENT_ID}
    ) as async_client:
        yield async_client


@pytest.fixture
def conversation_factory(session_factory):
    """Insert a conversation (and optional messages) owned by the test client."""

    async def create_conversation(
        *,
        title: str,
        client_id: str = CLIENT_ID,
        is_archived: bool = False,
        is_pinned: bool = False,
        messages: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        async with session_factory() as session:
            conversation = ConversationTable(
                client_id=client_id,
                agent_slug=AGENT_SLUG,
                agent_name="Test Agent",
                title=title,
                is_archived=is_archived,
                archived_at=utcnow() if is_archived else None,
                is_pinned=is_pinned,
                pinned_at=utcnow() if is_pinned else None,
                last_message_preview=(messages[-1]["content"] if messages else ""),
            )
            session.add(conversation)
            await session.flush()
            created: list[MessageTable] = []
            for payload in messages or []:
                message = MessageTable(
                    conversation_id=conversation.id,
                    sender=payload.get("sender", "user"),
                    content=payload.get("content"),
                    parent_message_id=payload.get("parent_message_id"),
                )
                session.add(message)
                created.append(message)
            await session.commit()
            return {"conversation_id": conversation.id, "message_ids": [m.id for m in created]}

    return create_conversation


class FakeAgentsService:
    """The agents service as an ``httpx.MockTransport``: answers by (method, path)
    and records every call. An unregistered call fails the test."""

    def __init__(self) -> None:
        self.routes: dict[tuple[str, str], Any] = {}
        self.calls: list[httpx.Request] = []

    def on(self, method: str, path: str, reply: Any) -> None:
        self.routes[(method.upper(), path)] = reply

    def called(self, method: str, path: str) -> list[httpx.Request]:
        return [r for r in self.calls if r.method == method.upper() and r.url.path == path]

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        reply = self.routes.get((request.method, request.url.path))
        if reply is None:
            raise AssertionError(
                f"unexpected agents-service call: {request.method} {request.url.path}"
            )
        return reply(request) if callable(reply) else reply


@pytest.fixture
def agents_service(client, monkeypatch):
    """Route every backend -> agents-service call to a :class:`FakeAgentsService`."""
    fake = FakeAgentsService()
    real = httpx.AsyncClient
    transport = httpx.MockTransport(fake.handle)
    monkeypatch.setattr(
        httpx, "AsyncClient", lambda *a, **k: real(transport=transport, timeout=k.get("timeout"))
    )
    return fake
