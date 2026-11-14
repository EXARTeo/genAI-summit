"""Per-route rate limits on the conversation, message, attachment, search and task routes.

The suite lifts every ceiling (conftest), so these tests swap one named
limiter for a tight one through ``dependency_overrides``: the real SDK
dependency, keying and 429 handler run, and the 429 carries ``Retry-After`` and
the ``X-RateLimit-*`` headers the UI backs off on. fakeredis has no Lua (no
``lupa``), so the SDK's window-counter script is replaced, for these tests
only, by the same counter written in Python. A route audit checks that every
route of these routers has a caller dependency and a named limiter.
"""

from __future__ import annotations

import pytest
from conftest import OTHER_CLIENT_ID
from fastapi.routing import APIRoute
from httpx import ASGITransport, AsyncClient
from redis_fastapi import rate_limit
from redis_fastapi.ratelimit_backend import _BackendCapabilities

from core.security.client import get_caller
from core.security.rate_limit import (
    client_identity,
    conversation_rate_limit,
    message_post_rate_limit,
    search_rate_limit,
    task_mutate_rate_limit,
    task_read_rate_limit,
)

MY_PREFIXES = ("/v1/conversations", "/v1/messages", "/v1/attachments", "/v1/search", "/v1/tasks")
NAMED_LIMITS = {
    conversation_rate_limit,
    message_post_rate_limit,
    search_rate_limit,
    task_read_rate_limit,
    task_mutate_rate_limit,
}


@pytest.fixture(autouse=True)
def _python_window_counter(app):
    """Serve the SDK's Lua window counter (GET, INCRBY, EXPIRE, PTTL) in Python."""
    pool_state = app.state._redis
    redis = pool_state._async_client

    async def window_counter(*, keys: list[str], args: list[int]) -> list[int]:
        cost, limit, window = args
        current = int(await redis.get(keys[0]) or 0)
        if current + cost > limit:
            return [current, 0, await redis.pttl(keys[0])]
        new_value = await redis.incrby(keys[0], cost)
        if new_value == cost:
            await redis.expire(keys[0], window)
        return [new_value, cost, await redis.pttl(keys[0])]

    previous = pool_state.ratelimit_capabilities
    pool_state.ratelimit_capabilities = _BackendCapabilities(
        supports_increx=False, script=window_counter
    )
    yield
    pool_state.ratelimit_capabilities = previous


def _tight(limit: int, scope: str):
    return rate_limit((limit, 60), scope=scope, identifier=client_identity, emit_headers=True)


def _all_calls(dependant) -> list:
    calls = []
    for dep in dependant.dependencies:
        calls.append(dep.call)
        calls.extend(_all_calls(dep))
    return calls


@pytest.mark.parametrize(
    ("limiter", "method", "path"),
    [
        (conversation_rate_limit, "GET", "/v1/conversations"),
        (search_rate_limit, "GET", "/v1/search?q=x"),
    ],
)
async def test_a_route_past_its_limit_answers_429_with_backoff_headers(
    app, client, other_client, limiter, method, path
):
    app.dependency_overrides[limiter] = _tight(2, f"test-{limiter.__name__}-{path}")

    first = await client.request(method, path)
    second = await client.request(method, path)
    third = await client.request(method, path)
    someone_else = await other_client.request(method, path)

    assert first.status_code == 200
    assert first.headers["x-ratelimit-limit"] == "2"
    assert first.headers["x-ratelimit-remaining"] == "1"
    assert second.status_code == 200
    assert third.status_code == 429
    assert int(third.headers["retry-after"]) > 0
    assert third.headers["x-ratelimit-limit"] == "2"
    assert third.headers["x-ratelimit-remaining"] == "0"
    assert "x-ratelimit-reset" in third.headers
    # Keyed by X-Client-Id: another browser has its own bucket.
    assert someone_else.status_code == 200


async def test_message_posts_are_limited_before_the_conversation_lookup(app, client):
    app.dependency_overrides[message_post_rate_limit] = _tight(1, "test-message-post")

    first = await client.post("/v1/messages/no-such-conversation", json={"sender": "ai"})
    second = await client.post("/v1/messages/no-such-conversation", json={"sender": "ai"})

    # Probing unknown ids still spends the budget.
    assert first.status_code == 404
    assert second.status_code == 429


async def test_without_a_client_id_the_limit_keys_on_the_ip(app):
    app.dependency_overrides[conversation_rate_limit] = _tight(1, "test-anonymous")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as anonymous:
        assert (await anonymous.get("/v1/conversations")).status_code == 200
        assert (await anonymous.get("/v1/conversations")).status_code == 429
    async with AsyncClient(
        transport=transport, base_url="http://testserver", headers={"X-Client-Id": OTHER_CLIENT_ID}
    ) as identified:
        assert (await identified.get("/v1/conversations")).status_code == 200


def test_every_route_has_a_caller_and_a_named_rate_limit(app):
    """Walks every route of these routers, so a new endpoint without a
    caller or a limit fails here."""
    checked = 0
    for route in app.routes:
        if not isinstance(route, APIRoute) or not route.path.startswith(MY_PREFIXES):
            continue
        calls = _all_calls(route.dependant)
        assert get_caller in calls, f"{route.path}: no caller"
        limits = [call for call in calls if call in NAMED_LIMITS]
        assert limits, f"{route.path}: no rate limit"
        # The limit counts before the conversation is looked up.
        top = [dep.call for dep in route.dependant.dependencies]
        first_limit = next(i for i, call in enumerate(top) if call in NAMED_LIMITS)
        assert not any(
            getattr(call, "__name__", "").startswith("validate_") for call in top[:first_limit]
        ), f"{route.path}: ownership check runs before the rate limit"
        checked += 1
    assert checked == 24
