"""Who is calling: another service of the stack, proven by a shared secret.

The runner is internal (not published, on ``sandbox_net`` only). Every /v1 route
requires the ``X-Internal-Proxy-Secret`` header to equal ``TRUSTED_PROXY_SECRET``
(the agents service sends its ``SANDBOX_RUNNER_SECRET``). With no
secret configured the gate is open in development/test and closed (503)
everywhere else: fail-closed. Same shape as the backend's client.py, with the
secret in place of the anonymous ``X-Client-Id``.
"""

from __future__ import annotations

import hmac
from dataclasses import dataclass

from fastapi import HTTPException, Request, status

from core.logging import set_context
from core.settings import settings

#: The caller id of a request that passed the gate.
INTERNAL_CALLER_ID = "internal"


@dataclass(frozen=True, slots=True)
class Caller:
    """The caller of one request."""

    id: str
    ip: str


def resolve_client_ip(conn: Request) -> str:
    """The caller's IP: the socket peer, or X-Forwarded-For's first hop when trusted."""
    if settings.client.trust_forwarded_for:
        forwarded = conn.headers.get("x-forwarded-for", "")
        first = forwarded.split(",")[0].strip()
        if first:
            return first
    return conn.client.host if conn.client else "unknown"


def check_internal_secret(presented: str | None) -> None:
    """Raise 401/503 unless ``presented`` matches the configured secret."""
    expected = settings.security.trusted_proxy_secret.get_secret_value()
    if not expected:
        if settings.app.is_local:
            return
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Service is not configured (TRUSTED_PROXY_SECRET unset).",
        )
    if not presented or not hmac.compare_digest(presented.encode(), expected.encode()):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Missing or invalid {settings.security.secret_header}.",
        )


async def get_caller(request: Request) -> Caller:
    """FastAPI dependency: the gate, then the request's :class:`Caller`."""
    check_internal_secret(request.headers.get(settings.security.secret_header))
    caller = Caller(id=INTERNAL_CALLER_ID, ip=resolve_client_ip(request))
    set_context(user_id=caller.id)
    return caller
