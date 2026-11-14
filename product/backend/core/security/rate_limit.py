"""Rate-limit policy for the whole API, backed by fastapi-redis-sdk.

Two layers on one Redis-counted engine (installed by
``core.cache.integration.install_redis_sdk``):

1. **Global per-IP budget** — one aggregate fixed-window budget per client IP
   across every endpoint (default 1200/min). The IP is the only identity a
   caller cannot choose, so this is the backstop. ``/health`` is exempt.
2. **Strict per-route limits** — ``rate_limit`` dependencies on the expensive
   paths (starting runs, posting messages, search, conversation writes), keyed
   by the caller's client id (``X-Client-Id``) with the IP as fallback. These
   emit ``X-RateLimit-*`` / ``Retry-After`` so the UI can back off; the global
   budget stays header-silent so the two never conflict on one response.

Counters live in Redis, so limits survive restarts and hold across replicas.
Everything fails OPEN on a Redis outage: availability first.
"""

from __future__ import annotations

from fastapi import Request, WebSocket
from redis_fastapi import rate_limit
from redis_fastapi.deps import get_rate_limit_backend

from core.logging import get_logger
from core.security.client import parse_client_id, resolve_client_ip
from core.settings import settings

logger = get_logger(__name__)

# The global per-IP budget, consumed by the SDK middleware installer.
IP_BUDGET_RATE: tuple[int, int] = (
    settings.rate_limit.ip_max_calls,
    settings.rate_limit.ip_window_seconds,
)

_EXEMPT_PATHS = frozenset({"/health"})


def exempt_from_budget(request: Request) -> bool:
    """Skip predicate for the global budget: the container probe."""
    return request.url.path in _EXEMPT_PATHS


def ip_identity(request: Request) -> str:
    """Global budget key: the client IP."""
    return f"ip:{resolve_client_ip(request)}"


def client_identity(request: Request) -> str:
    """Per-route key: the client id, else the IP."""
    client_id = parse_client_id(request.headers.get(settings.client.client_id_header))
    return f"client:{client_id}" if client_id else ip_identity(request)


def _limit(max_attempts: int, window_seconds: int, scope: str):  # noqa: ANN202 - SDK dependency
    return rate_limit(
        (max_attempts, window_seconds),
        scope=scope,
        identifier=client_identity,
        emit_headers=True,
    )


# --- Named per-route dependencies ------------------------------------------
# Routers declare policy by name; the numbers live in core/settings.py.

inference_rate_limit = _limit(
    settings.rate_limit.inference_max_attempts,
    settings.rate_limit.inference_window_seconds,
    "inference",
)
message_post_rate_limit = _limit(
    settings.rate_limit.message_post_max_attempts,
    settings.rate_limit.message_post_window_seconds,
    "message-post",
)
conversation_rate_limit = _limit(
    settings.rate_limit.conversation_max_attempts,
    settings.rate_limit.conversation_window_seconds,
    "conversation",
)
search_rate_limit = _limit(
    settings.rate_limit.search_max_attempts,
    settings.rate_limit.search_window_seconds,
    "search",
)

task_read_rate_limit = _limit(
    settings.rate_limit.task_read_max_attempts,
    settings.rate_limit.task_read_window_seconds,
    "task-read",
)
task_mutate_rate_limit = _limit(
    settings.rate_limit.task_mutate_max_attempts,
    settings.rate_limit.task_mutate_window_seconds,
    "task-mutate",
)


workspace_rate_limit = _limit(
    settings.rate_limit.workspace_max_attempts,
    settings.rate_limit.workspace_window_seconds,
    "workspace",
)
# The agents service sends no client id: its per-route key is the IP.
internal_rate_limit = rate_limit(
    (settings.rate_limit.internal_max_attempts, settings.rate_limit.internal_window_seconds),
    scope="internal",
    identifier=ip_identity,
    emit_headers=True,
)


async def allow_ws_connect(websocket: WebSocket, client_id: str) -> bool:
    """Connect-rate guard for every WebSocket handshake (run, conversation, task).

    The SDK's middleware and ``rate_limit`` dependencies are HTTP-only, so the
    socket route enforces its own window against the same Redis engine. Keyed
    by client id and IP together, so rotating the client id alone does not
    reset it. Fails OPEN like every limiter.
    """
    try:
        backend = await get_rate_limit_backend(websocket)  # type: ignore[arg-type]
        result = await backend.hit(
            f"client:{client_id}:ip:{resolve_client_ip(websocket)}",
            limit=settings.rate_limit.ws_connect_max_attempts,
            window=settings.rate_limit.ws_connect_window_seconds,
            scope="ws-connect",
        )
        return result.allowed
    except Exception:
        logger.warning(
            "ws_connect_rate_limit_degraded",
            "WebSocket connect rate limit unavailable; failing open",
            exc_info=True,
        )
        return True
