"""The Redis-backed run event log (``utils/event_log.py``) against fakeredis:
monotonic cursors, replay from a cursor, stop at the terminal frame, TTL."""

from __future__ import annotations

import pytest_asyncio
from fakeredis import aioredis as fake_aioredis

from core.cache import client as cache_client
from utils import event_log as event_log_module
from utils.event_log import RedisEventLog, _stream_key

TERMINAL = {"completed", "cancelled", "failed"}


@pytest_asyncio.fixture
async def fake_redis():
    client = fake_aioredis.FakeRedis(decode_responses=True)
    try:
        yield client
    finally:
        await client.aclose()


@pytest_asyncio.fixture
async def log(fake_redis):
    log = RedisEventLog()
    log._client = fake_redis
    log._reader = fake_redis
    return log


async def _read_all(log: RedisEventLog, run_id: str, since: str | None = None) -> list[dict]:
    return [
        payload async for _id, payload in log.read_since(run_id, since, terminal_statuses=TERMINAL)
    ]


async def test_append_returns_monotonic_sequence_ids(log):
    ids = [await log.append("run-1", {"n": n}) for n in range(3)]
    assert all(isinstance(i, str) for i in ids)
    assert ids == sorted(ids) and len(set(ids)) == 3


async def test_read_since_replays_the_whole_backlog_without_a_cursor(log):
    await log.append("run-1", {"n": 1})
    await log.append("run-1", {"n": 2})
    await log.append("run-1", {"n": 3, "run": {"status": "completed"}})
    assert [e["n"] for e in await _read_all(log, "run-1")] == [1, 2, 3]


async def test_read_since_resumes_after_the_cursor(log):
    first = await log.append("run-1", {"n": 1})
    await log.append("run-1", {"n": 2})
    await log.append("run-1", {"n": 3, "run": {"status": "completed"}})
    assert [e["n"] for e in await _read_all(log, "run-1", first)] == [2, 3]


async def test_read_since_stops_at_the_first_terminal_frame(log):
    await log.append("run-1", {"n": 1})
    await log.append("run-1", {"n": 2, "run": {"status": "cancelled"}})
    await log.append("run-1", {"n": 3})
    received = await _read_all(log, "run-1")
    assert [e["n"] for e in received] == [1, 2]


async def test_streams_are_isolated_per_run(log):
    await log.append("run-A", {"n": 1, "run": {"status": "completed"}})
    await log.append("run-B", {"n": 99, "run": {"status": "completed"}})
    assert [e["n"] for e in await _read_all(log, "run-A")] == [1]
    assert [e["n"] for e in await _read_all(log, "run-B")] == [99]


async def test_mark_terminal_sets_a_ttl(log, fake_redis):
    await log.append("run-1", {"n": 1})
    await log.mark_terminal("run-1")
    assert 0 < await fake_redis.ttl(_stream_key("run-1")) <= 3600


async def test_on_idle_ends_a_tail_whose_terminal_frame_never_comes(log, monkeypatch):
    monkeypatch.setattr(event_log_module.settings.redis, "read_block_ms", 10)
    await log.append("run-1", {"n": 1})
    calls: list[int] = []

    async def went_terminal() -> bool:
        calls.append(1)
        return True

    received = [
        payload
        async for _id, payload in log.read_since(
            "run-1", None, terminal_statuses=TERMINAL, on_idle=went_terminal
        )
    ]
    assert [e["n"] for e in received] == [1]
    assert calls == [1]


async def test_last_entry_id_is_none_for_an_absent_stream(log):
    assert await log.last_entry_id("nothing") is None
    entry = await log.append("run-1", {"n": 1})
    assert await log.last_entry_id("run-1") == entry


async def test_the_reader_uses_its_own_long_timeout_client(monkeypatch):
    made: list[dict] = []

    def factory(**kwargs):
        made.append(kwargs)
        return object()

    monkeypatch.setattr(event_log_module, "create_redis_client", factory)
    log = RedisEventLog()
    await log._get_client()
    await log._get_reader()
    assert made == [{}, {"socket_timeout": cache_client.stream_read_socket_timeout()}]
