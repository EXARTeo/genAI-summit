"""Who is calling: a holder of the gateway's bearer token.

The gateway pretends to be a production model API, so it is gated like one:
every /v1 route requires ``Authorization: Bearer <MODEL_GATEWAY_TOKEN>``. With
no token configured the gate is open in development/test and closed (503)
everywhere else: fail-closed. Same shape as the backend's and reg-memory's
client.py, with a bearer token in place of ``X-Client-Id`` / ``X-Internal-Secret``.
"""

from __future__ import annotations

import hmac
from dataclasses import dataclass

from fastapi import HTTPException, Request, status

from core.logging.context import set_context
from core.logging.redaction import hash_identifier
from core.settings import settings

#: The caller id of a request let through by the open development gate.
OPEN_GATE_CALLER_ID = "dev-open"

_BEARER_PREFIX = "bearer "


@dataclass(frozen=True, slots=True)
class Caller:
    """The caller of one request; ``id`` is a keyed hash of the token, never the token."""

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


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


def check_bearer_token(authorization: str | None) -> str:
    """Return the caller id, or raise 401/503 unless the bearer token matches."""
    expected = settings.security.token.get_secret_value()
    if not expected:
        if settings.app.is_local:
            return OPEN_GATE_CALLER_ID
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Service is not configured (MODEL_GATEWAY_TOKEN unset).",
        )
    if not authorization or not authorization.lower().startswith(_BEARER_PREFIX):
        raise _unauthorized("Missing bearer token.")
    presented = authorization[len(_BEARER_PREFIX) :].strip()
    if not presented or not hmac.compare_digest(presented.encode(), expected.encode()):
        raise _unauthorized("Invalid bearer token.")
    return hash_identifier(presented)


async def get_caller(request: Request) -> Caller:
    """FastAPI dependency: the gate, then the request's :class:`Caller`."""
    caller_id = check_bearer_token(request.headers.get("authorization"))
    caller = Caller(id=caller_id, ip=resolve_client_ip(request))
    request.state.user_id = caller.id
    set_context(user_id=caller.id)
    return caller
