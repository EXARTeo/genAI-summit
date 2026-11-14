"""The agents service's catalog (``GET /agents``), proxied for the UI."""

from __future__ import annotations

from typing import Any

import httpx

from core.logging import get_logger
from core.settings import settings
from utils.agents import internal_headers

logger = get_logger(__name__)

#: A test seam: tests swap in an ``httpx.MockTransport``.
transport: httpx.AsyncBaseTransport | None = None


async def list_agents() -> list[dict[str, Any]] | None:
    """The manifests (``slug``, ``name``, ``description``, ``default``), or None
    when the agents service cannot be reached."""
    url = f"{settings.upstream.agents_service_url.rstrip('/')}/agents"
    try:
        async with httpx.AsyncClient(
            timeout=settings.http.agents_timeout, transport=transport
        ) as client:
            response = await client.get(url, headers=internal_headers())
        response.raise_for_status()
        body = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning(
            "agents_catalog_failed", "Agents catalog unavailable", error=type(exc).__name__
        )
        return None
    return [a for a in body if isinstance(a, dict)] if isinstance(body, list) else []
