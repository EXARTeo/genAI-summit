"""Optional injected latency, so the gateway behaves like a remote endpoint."""

import asyncio

from core.settings import settings


async def inject_latency() -> None:
    """FastAPI dependency: sleep ``MODEL_GATEWAY_LATENCY_MS`` before the handler."""
    if settings.app.latency_ms > 0:
        await asyncio.sleep(settings.app.latency_ms / 1000)
