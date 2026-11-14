"""Per-run append-only event log backed by Redis Streams.

Each run gets its own stream at ``inference:run:{run_id}:events``. An entry
holds one ``payload`` field with a JSON frame: one ``events`` delta frame per
upstream SSE chunk, status-only frames, and the terminal frame. The stream is
capped at ``REDIS_STREAM_MAXLEN`` entries and EXPIREd
``REDIS_STREAM_TERMINAL_TTL_SECONDS`` after the run ends, so a client that
reconnects inside that window replays what it missed from its ``since``
cursor; after it, the durable record is the message row in the database.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

import redis.asyncio as aioredis

from core.cache import create_redis_client
from core.cache.client import stream_read_socket_timeout
from core.logging import get_logger
from core.settings import settings

logger = get_logger(__name__)

_KEY_PREFIX = "inference:run"


def _stream_key(run_id: str) -> str:
    return f"{_KEY_PREFIX}:{run_id}:events"


def _decode(value: Any) -> Any:
    return value.decode() if isinstance(value, bytes) else value


class RedisEventLog:
    """Thin wrapper over Redis Streams for run events.

    Two connection pools per process, created lazily: one for ordinary
    commands (append, expire, range — redis-py's short default socket timeout,
    so a stuck server fails a publish fast instead of stalling the run) and one
    for the blocking ``XREAD`` of the live tail, whose socket timeout outlasts
    the block time (:func:`core.cache.client.stream_read_socket_timeout`).
    """

    def __init__(self) -> None:
        self._client: aioredis.Redis | None = None
        self._reader: aioredis.Redis | None = None
        self._lock = asyncio.Lock()

    async def _get_client(self) -> aioredis.Redis:
        if self._client is not None:
            return self._client
        async with self._lock:
            if self._client is None:
                self._client = create_redis_client()
        return self._client

    async def _get_reader(self) -> aioredis.Redis:
        """The client for blocking stream reads only."""
        if self._reader is not None:
            return self._reader
        async with self._lock:
            if self._reader is None:
                self._reader = create_redis_client(socket_timeout=stream_read_socket_timeout())
        return self._reader

    async def append(self, run_id: str, event: dict[str, Any]) -> str:
        """Append a frame; returns its entry id (e.g. ``"1717276800123-0"``),
        the ``seq`` cursor a client sends back as ``since`` on reconnect."""
        client = await self._get_client()
        entry_id = await client.xadd(
            _stream_key(run_id),
            {"payload": json.dumps(event, ensure_ascii=False)},
            maxlen=settings.redis.stream_maxlen,
            approximate=True,
        )
        return _decode(entry_id)

    async def read_since(
        self,
        run_id: str,
        since: str | None,
        *,
        terminal_statuses: set[str],
        on_idle: Callable[[], Awaitable[bool]] | None = None,
    ) -> AsyncIterator[tuple[str, dict[str, Any]]]:
        """Yield ``(entry_id, frame)`` pairs after ``since`` (exclusive).

        ``None`` or empty replays the whole stream. Blocks on ``XREAD BLOCK``
        for new frames and returns after the first frame whose ``run.status``
        is terminal, or when ``on_idle`` returns True after a read timed out —
        the escape hatch for a run that ended without its terminal frame
        reaching this reader (publish racing the subscribe, a trimmed stream).
        """
        client = await self._get_reader()
        key = _stream_key(run_id)
        cursor = since or "0"
        while True:
            result = await client.xread(
                {key: cursor}, count=100, block=settings.redis.read_block_ms
            )
            if not result:
                if on_idle is not None and await on_idle():
                    return
                continue
            for _stream_name, entries in result:
                for raw_entry_id, fields in entries:
                    # fakeredis (and a client without decode_responses) hands
                    # back bytes; coerce so the payload key is never missed.
                    entry_id = _decode(raw_entry_id)
                    cursor = entry_id
                    payload_raw = fields.get("payload") or fields.get(b"payload")
                    if not payload_raw:
                        continue
                    try:
                        payload = json.loads(payload_raw)
                    except json.JSONDecodeError:
                        continue
                    yield entry_id, payload
                    run = payload.get("run") if isinstance(payload, dict) else None
                    if isinstance(run, dict) and run.get("status") in terminal_statuses:
                        return

    async def last_entry_id(self, run_id: str) -> str | None:
        """The newest entry id, or None for an empty/absent stream. Anchors the
        live-tail cursor before a synthesized snapshot is built, so no frame
        can fall into the gap between the two."""
        client = await self._get_client()
        entries = await client.xrevrange(_stream_key(run_id), count=1)
        return _decode(entries[0][0]) if entries else None

    async def mark_terminal(self, run_id: str) -> None:
        """EXPIRE the stream: reconnects within the TTL can still replay it."""
        client = await self._get_client()
        await client.expire(_stream_key(run_id), settings.redis.terminal_ttl_seconds)

    async def close(self) -> None:
        """Close both pools (shutdown)."""
        clients, self._client, self._reader = (self._client, self._reader), None, None
        for client in clients:
            if client is None:
                continue
            try:
                await client.aclose()
            except Exception:
                logger.warning("redis_close_failed", "Redis client close failed", exc_info=True)


event_log = RedisEventLog()
