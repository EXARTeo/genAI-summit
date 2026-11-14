"""Rate-limit policy for the whole API, on an in-memory engine.

Same two layers as the backend's (which counts in Redis via fastapi-redis-sdk)
and reg-memory's; the gateway is one process with no Redis, so the counters
live in memory and reset on restart:

1. **Global per-IP budget**: one fixed-window budget per client IP across every
   endpoint (``IpBudgetMiddleware``). ``/health`` is exempt.
2. **Per-token limit**: ``token_rate_limit`` on every model/chat route, keyed by
   the caller (a hash of the bearer token), like a production API's published
   limit (default 5 requests per second). Emits ``X-RateLimit-*`` /
   ``Retry-After`` on 429.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from core.logging import get_logger
from core.security.client import Caller, get_caller, resolve_client_ip
from core.settings import settings

logger = get_logger(__name__)

IP_BUDGET_RATE: tuple[int, int] = (
    settings.rate_limit.ip_max_calls,
    settings.rate_limit.ip_window_seconds,
)
TOKEN_RATE: tuple[int, int] = (
    settings.rate_limit.token_max_calls,
    settings.rate_limit.token_window_seconds,
)

_EXEMPT_PATHS = frozenset({"/health"})
_MAX_KEYS = 10_000


@dataclass(frozen=True, slots=True)
class RateLimitResult:
    allowed: bool
    limit: int
    remaining: int
    reset_seconds: int


class InMemoryRateLimitBackend:
    """Fixed-window counters keyed by ``scope:identity``."""

    def __init__(self) -> None:
        self._windows: dict[str, tuple[float, int]] = {}

    def hit(self, key: str, *, limit: int, window: int, scope: str) -> RateLimitResult:
        now = time.monotonic()
        full_key = f"{scope}:{key}"
        started, count = self._windows.get(full_key, (now, 0))
        if now - started >= window:
            started, count = now, 0
        count += 1
        self._windows[full_key] = (started, count)
        if len(self._windows) > _MAX_KEYS:
            self._evict(now, window)
        reset = max(1, int(window - (now - started)))
        return RateLimitResult(count <= limit, limit, max(0, limit - count), reset)

    def _evict(self, now: float, window: int) -> None:
        for key in [k for k, (s, _) in self._windows.items() if now - s >= window]:
            del self._windows[key]

    def reset(self) -> None:
        self._windows.clear()


backend = InMemoryRateLimitBackend()


def exempt_from_budget(request: Request) -> bool:
    """Skip predicate for the global budget: the container probe."""
    return request.url.path in _EXEMPT_PATHS


def ip_identity(request: Request) -> str:
    """Global budget key: the client IP."""
    return f"ip:{resolve_client_ip(request)}"


class IpBudgetMiddleware(BaseHTTPMiddleware):
    """The global per-IP budget; header-silent like the backend's."""

    async def dispatch(self, request: Request, call_next):
        if not exempt_from_budget(request):
            limit, window = IP_BUDGET_RATE
            result = backend.hit(ip_identity(request), limit=limit, window=window, scope="ip")
            if not result.allowed:
                logger.warning("ip_budget_exceeded", "Global per-IP budget exceeded")
                return JSONResponse(
                    {"detail": "Too many requests. Please slow down."},
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    headers={"Retry-After": str(result.reset_seconds)},
                )
        return await call_next(request)


def rate_limit(rate: tuple[int, int], *, scope: str):  # noqa: ANN201 - FastAPI dependency
    """A per-caller limit; depends on ``get_caller`` so auth always runs first."""
    max_attempts, window_seconds = rate

    async def _dependency(caller: Annotated[Caller, Depends(get_caller)]) -> None:
        result = backend.hit(
            f"caller:{caller.id}", limit=max_attempts, window=window_seconds, scope=scope
        )
        if not result.allowed:
            logger.warning("rate_limit_exceeded", "Rate limit exceeded", scope=scope)
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Rate limit exceeded. Retry after the time in Retry-After.",
                headers={
                    "Retry-After": str(result.reset_seconds),
                    "X-RateLimit-Limit": str(result.limit),
                    "X-RateLimit-Remaining": "0",
                    "X-RateLimit-Reset": str(result.reset_seconds),
                },
            )

    return _dependency


# --- Named per-route dependencies ------------------------------------------
# Routers declare policy by name; the numbers live in core/settings.py.

token_rate_limit = rate_limit(TOKEN_RATE, scope="token")
