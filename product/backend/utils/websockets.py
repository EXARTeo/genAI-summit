"""The lifecycle every backend WebSocket follows (run, conversation channel, task).

1. **open**: the Origin must be an allowed one (browsers apply no CORS to a
   handshake), the caller is ``?client_id=``, and a per-client connect-rate
   limit applies;
2. **ownership**: checked by the route before the handshake completes, so a
   socket for another browser's run, conversation or task closes with 4404
   and learns nothing;
3. **subscribe**: the first client frame must be ``{"type": "subscribe",
   "since"?}`` within ``INFERENCE_WS_SUBSCRIBE_TIMEOUT_SECONDS``;
4. **pump**: frames are sent until they end or the client goes away.

The routers keep only the endpoints; this module holds the steps, so every
socket follows them identically.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect

from core.logging import get_logger
from core.security.client import Caller, get_ws_caller
from core.security.rate_limit import allow_ws_connect
from core.settings import settings

logger = get_logger(__name__)

# WebSocket close codes (4xxx is application-defined; they mirror HTTP).
WS_BAD_REQUEST = 4400
WS_FORBIDDEN = 4403
WS_NOT_FOUND = 4404
WS_RATE_LIMITED = 4429
# A `since` cursor is a Redis stream id; anything longer is not one.
_MAX_SINCE_LENGTH = 64


def _origin_allowed(websocket: WebSocket) -> bool:
    """An Origin outside ``CORS_ALLOWED_ORIGINS`` (``null`` included) is
    refused. A handshake without one is no browser and is allowed."""
    origin = websocket.headers.get("origin") or ""
    if not origin:
        return True
    allowed = {o.rstrip("/").lower() for o in settings.cors.allowed_origins}
    if origin.rstrip("/").lower() in allowed:
        return True
    logger.warning(
        "ws_origin_refused", "WebSocket handshake from a disallowed origin", origin=origin[:200]
    )
    return False


async def open_socket(websocket: WebSocket) -> Caller | None:
    """Origin, caller and connect-rate checks before the handshake completes;
    closes the socket and returns None on failure."""
    if not _origin_allowed(websocket):
        await websocket.close(code=WS_FORBIDDEN, reason="Origin not allowed")
        return None
    caller = get_ws_caller(websocket)
    if not await allow_ws_connect(websocket, caller.id):
        await websocket.close(code=WS_RATE_LIMITED, reason="Too many connections; retry shortly")
        return None
    return caller


async def accept_subscribe(websocket: WebSocket) -> tuple[bool, str | None]:
    """Accept, then read the first frame ``{"type": "subscribe", "since"?}``
    within ``INFERENCE_WS_SUBSCRIBE_TIMEOUT_SECONDS``; closes 4400 otherwise.
    Returns ``(ok, since)``."""
    await websocket.accept()
    try:
        first = await asyncio.wait_for(
            websocket.receive_json(), timeout=settings.inference.ws_subscribe_timeout_seconds
        )
    except TimeoutError:
        await websocket.close(code=WS_BAD_REQUEST, reason="No subscribe frame in time")
        return False, None
    except WebSocketDisconnect:
        return False, None
    except ValueError:
        await websocket.close(code=WS_BAD_REQUEST, reason="Invalid subscribe frame")
        return False, None
    if not isinstance(first, dict) or first.get("type") != "subscribe":
        await websocket.close(code=WS_BAD_REQUEST, reason="First frame must be subscribe")
        return False, None
    since = first.get("since")
    valid = isinstance(since, str) and 0 < len(since) <= _MAX_SINCE_LENGTH
    return True, since if valid else None


async def _until_disconnect(websocket: WebSocket) -> None:
    """Read (and ignore) client frames until the client goes away."""
    while True:
        message = await websocket.receive()
        if message.get("type") == "websocket.disconnect":
            return


async def close_quietly(websocket: WebSocket, **kwargs: Any) -> None:
    """Close the socket; a client that closed first is not an error."""
    try:
        await websocket.close(**kwargs)
    except (RuntimeError, WebSocketDisconnect):
        logger.debug("ws_close_skipped", "WebSocket already closed")


async def pump_frames(
    websocket: WebSocket, frames: AsyncIterator[dict[str, Any]], **log_fields: Any
) -> None:
    """Send ``frames`` until they end or the client leaves, then close.

    The sender races a reader of client frames, so a client that leaves never
    keeps a Redis read open.
    """

    async def send_all() -> None:
        async for frame in frames:
            await websocket.send_json(frame)

    sender = asyncio.create_task(send_all())
    receiver = asyncio.create_task(_until_disconnect(websocket))
    done, pending = await asyncio.wait({sender, receiver}, return_when=asyncio.FIRST_COMPLETED)
    for task in pending:
        task.cancel()
    await asyncio.gather(*pending, return_exceptions=True)
    if sender in done and sender.exception() is not None:
        exc = sender.exception()
        if not isinstance(exc, WebSocketDisconnect):
            logger.error("ws_stream_failed", "WebSocket stream failed", exc_info=exc, **log_fields)
            await close_quietly(websocket, code=1011, reason="Stream failed")
        return
    if sender in done:
        await close_quietly(websocket)
