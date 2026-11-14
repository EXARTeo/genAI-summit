"""Who is calling, without login.

There are no accounts. The browser generates a random UUID once, keeps it in
localStorage and sends it on every request as ``X-Client-Id``. The backend
uses it to keep one browser's conversations apart from another's and to key
per-route rate limits.

It is **not** authentication: anyone who learns a client id can read that
client's conversations, and a client can rotate its id at will. The global
per-IP budget (core/security/rate_limit.py) is the backstop against that.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from fastapi import HTTPException, Request, WebSocket, status

from core.logging import set_context
from core.settings import settings

#: Used when a request carries no client id (curl, health checks, old UIs).
ANONYMOUS_CLIENT_ID = "anonymous"


@dataclass(frozen=True, slots=True)
class Caller:
    """The caller of one request. ``id`` scopes every conversation query."""

    id: str
    ip: str


def resolve_client_ip(conn: Request | WebSocket) -> str:
    """The caller's IP: the socket peer, or X-Forwarded-For's first hop when trusted."""
    if settings.client.trust_forwarded_for:
        forwarded = conn.headers.get("x-forwarded-for", "")
        first = forwarded.split(",")[0].strip()
        if first:
            return first
    return conn.client.host if conn.client else "unknown"


def parse_client_id(raw: str | None) -> str | None:
    """A canonical UUID string, or None when ``raw`` is missing or not a UUID."""
    if not raw:
        return None
    try:
        return str(uuid.UUID(raw.strip()))
    except ValueError:
        return None


def _client_id_from(conn: Request | WebSocket) -> str | None:
    header = conn.headers.get(settings.client.client_id_header)
    if header is not None:
        parsed = parse_client_id(header)
        if parsed is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"{settings.client.client_id_header} must be a UUID",
            )
        return parsed
    # Browsers cannot set headers on a WebSocket handshake: accept a query param.
    return parse_client_id(conn.query_params.get("client_id"))


async def get_caller(request: Request) -> Caller:
    """FastAPI dependency: the request's :class:`Caller`."""
    caller = Caller(
        id=_client_id_from(request) or ANONYMOUS_CLIENT_ID,
        ip=resolve_client_ip(request),
    )
    set_context(user_id=caller.id)
    return caller


def get_ws_caller(websocket: WebSocket) -> Caller:
    """The :class:`Caller` of a WebSocket handshake (header or ``?client_id=``)."""
    try:
        client_id = _client_id_from(websocket)
    except HTTPException:
        client_id = None
    caller = Caller(id=client_id or ANONYMOUS_CLIENT_ID, ip=resolve_client_ip(websocket))
    set_context(user_id=caller.id)
    return caller
