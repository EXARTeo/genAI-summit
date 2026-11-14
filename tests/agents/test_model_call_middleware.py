"""Model-call and tool-call middleware: waiting out rate limits, and tool errors as results.

Pinned:

* a 429 is retried after a wait, up to ``max_attempts`` attempts in all, and
  the call's answer is returned as if nothing happened;
* the wait is the configured delay, or the provider's ``Retry-After`` when that
  is larger, never past the cap; defaults come from ``settings.rate_limit_retry``;
* ``insufficient_quota`` (out of credit) and every non-429 error are raised at
  once, never retried;
* a failing tool becomes an error ``ToolMessage`` instead of aborting the run,
  while LangGraph's control flow (``GraphInterrupt``) still reaches the runner;
* every deep agent and every sub-agent gets both guarantees exactly once, the
  retry outermost.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from langchain_core.messages import ToolMessage
from langgraph.errors import GraphInterrupt

from core.settings import settings
from harness.abstractions.deep_agent import DeepAgent
from harness.middlewares import RetryOnRateLimitMiddleware, ToolErrorMiddleware
from harness.middlewares.rate_limit import is_rate_limit_error, retry_after_seconds


class RateLimitError(Exception):
    """Stands in for openai.RateLimitError: matched by name, carries the response."""

    def __init__(self, *, retry_after: str | None = None, code: str | None = None):
        super().__init__("429 Too Many Requests")
        self.code = code
        self.status_code = 429
        headers = {"retry-after": retry_after} if retry_after is not None else {}
        self.response = SimpleNamespace(status_code=429, headers=headers)


class Flaky:
    """A model-call handler that fails ``failures`` times, then answers."""

    def __init__(self, failures: int, error_factory=RateLimitError):
        self.failures = failures
        self.error_factory = error_factory
        self.calls = 0

    async def __call__(self, _request):
        self.calls += 1
        if self.calls <= self.failures:
            raise self.error_factory()
        return "answer"


@pytest.fixture
def no_sleep(monkeypatch):
    """Record the waits instead of sleeping through them."""
    waits: list[float] = []

    async def fake_sleep(seconds):
        waits.append(seconds)

    monkeypatch.setattr("harness.middlewares.rate_limit.asyncio.sleep", fake_sleep)
    return waits


def _retry(**kwargs) -> RetryOnRateLimitMiddleware:
    defaults = {"max_attempts": 4, "delay_seconds": 15.0, "max_delay_seconds": 120.0}
    return RetryOnRateLimitMiddleware(**{**defaults, **kwargs})


def _tool_request(name: str = "search") -> SimpleNamespace:
    return SimpleNamespace(tool_call={"id": "call-1", "name": name, "args": {}})


# ---------------------------------------------------------------- rate limits
async def test_a_rate_limited_call_is_retried_until_it_answers(no_sleep):
    handler = Flaky(failures=2)
    result = await _retry().awrap_model_call(SimpleNamespace(), handler)
    assert result == "answer"
    assert handler.calls == 3
    assert no_sleep == [15.0, 15.0]


async def test_the_retry_gives_up_after_max_attempts(no_sleep):
    handler = Flaky(failures=10)
    with pytest.raises(RateLimitError):
        await _retry(max_attempts=3).awrap_model_call(SimpleNamespace(), handler)
    assert handler.calls == 3
    assert len(no_sleep) == 2


def test_a_larger_retry_after_wins_but_is_capped():
    middleware = _retry()
    assert middleware.delay_for(RateLimitError(retry_after="40")) == 40.0
    assert middleware.delay_for(RateLimitError(retry_after="3")) == 15.0
    assert middleware.delay_for(RateLimitError(retry_after="600")) == 120.0
    # An HTTP-date Retry-After is not numeric: the configured delay applies.
    assert middleware.delay_for(RateLimitError(retry_after="Wed, 21 Oct 2026 07:28:00 GMT")) == 15.0


def test_the_defaults_come_from_settings():
    settings.rate_limit_retry.max_attempts = 2
    settings.rate_limit_retry.delay_seconds = 1.5
    settings.rate_limit_retry.max_delay_seconds = 9.0
    middleware = RetryOnRateLimitMiddleware()
    assert (middleware.max_attempts, middleware.delay_seconds, middleware.max_delay_seconds) == (
        2,
        1.5,
        9.0,
    )


async def test_out_of_credit_and_other_errors_are_raised_at_once(no_sleep):
    out_of_credit = Flaky(
        failures=1, error_factory=lambda: RateLimitError(code="insufficient_quota")
    )
    with pytest.raises(RateLimitError):
        await _retry().awrap_model_call(SimpleNamespace(), out_of_credit)
    assert out_of_credit.calls == 1

    broken = Flaky(failures=1, error_factory=lambda: ValueError("bad request"))
    with pytest.raises(ValueError):
        await _retry().awrap_model_call(SimpleNamespace(), broken)
    assert broken.calls == 1
    assert no_sleep == []


def test_a_429_is_recognised_by_class_name_or_status_code():
    assert is_rate_limit_error(RateLimitError())
    by_status = Exception("busy")
    by_status.response = SimpleNamespace(status_code=429, headers={})
    assert is_rate_limit_error(by_status)
    direct = Exception("busy")
    direct.status_code = 429
    assert is_rate_limit_error(direct)
    assert not is_rate_limit_error(RuntimeError("boom"))
    assert not is_rate_limit_error(RateLimitError(code="insufficient_quota"))
    assert retry_after_seconds(RuntimeError("no response")) is None


def test_the_sync_path_retries_too(monkeypatch):
    waits: list[float] = []
    monkeypatch.setattr("harness.middlewares.rate_limit.time.sleep", waits.append)
    calls = {"n": 0}

    def handler(_request):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RateLimitError(retry_after="20")
        return "answer"

    assert _retry().wrap_model_call(SimpleNamespace(), handler) == "answer"
    assert waits == [20.0]


# ---------------------------------------------------------------- tool errors
def test_a_failing_tool_becomes_an_error_result():
    def handler(_request):
        raise ValueError("HTTP 400 from the server")

    result = ToolErrorMiddleware().wrap_tool_call(_tool_request(), handler)
    assert isinstance(result, ToolMessage)
    assert result.status == "error"
    assert result.tool_call_id == "call-1"
    assert result.name == "search"
    assert result.content == "Tool 'search' failed: ValueError: HTTP 400 from the server"


async def test_the_async_path_returns_the_error_result_too():
    async def handler(_request):
        raise RuntimeError("gateway down")

    result = await ToolErrorMiddleware().awrap_tool_call(_tool_request("fetch"), handler)
    assert result.status == "error"
    assert "RuntimeError: gateway down" in result.content


async def test_a_tool_that_answers_passes_through_untouched():
    answer = ToolMessage(content="ok", tool_call_id="call-1", name="search")

    async def handler(_request):
        return answer

    assert await ToolErrorMiddleware().awrap_tool_call(_tool_request(), handler) is answer


async def test_an_interrupt_is_control_flow_and_is_never_swallowed():
    # A HITL pause inside a tool (e.g. a sub-agent's approval) must reach the
    # graph runner; turning it into a failed result made the approval stale.
    def sync_handler(_request):
        raise GraphInterrupt(())

    async def async_handler(_request):
        raise GraphInterrupt(())

    with pytest.raises(GraphInterrupt):
        ToolErrorMiddleware().wrap_tool_call(_tool_request(), sync_handler)
    with pytest.raises(GraphInterrupt):
        await ToolErrorMiddleware().awrap_tool_call(_tool_request(), async_handler)


# ----------------------------------------------------------- the guarantees
def test_every_stack_gets_both_guarantees_once_and_the_retry_outermost():
    stack = DeepAgent._ensure_platform_middleware([])
    assert [type(m) for m in stack] == [RetryOnRateLimitMiddleware, ToolErrorMiddleware]
    again = DeepAgent._ensure_platform_middleware(stack)
    assert sum(isinstance(m, RetryOnRateLimitMiddleware) for m in again) == 1
    assert sum(isinstance(m, ToolErrorMiddleware) for m in again) == 1
    assert isinstance(DeepAgent._ensure_platform_middleware(None)[0], RetryOnRateLimitMiddleware)


def test_an_existing_tool_error_middleware_is_kept_where_it_is():
    marker = object()
    own = ToolErrorMiddleware()
    stack = DeepAgent._ensure_platform_middleware([marker, own])
    assert stack == [stack[0], marker, own]
    assert isinstance(stack[0], RetryOnRateLimitMiddleware)
