"""The MCP gateway (sibling ``mcp_gateway``): a run's session, and how its tools are keyed.

A run opens one SSE session to ``MCP_GATEWAY_URL`` for its whole stream
(:func:`optional_mcp_session`) and loads the gateway's tools from it. MCP is
optional: no URL, or a gateway that is down or slow to finish its handshake,
means the run goes ahead with the agent's own tools, never a failed run.

A tool is keyed ``server_id/tool_name`` (:func:`get_tool_cache_key`), the form
an ``agent.yaml`` names it in. The gateway serves tool names unprefixed, so the
server of a known tool is inferred from its name.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import mcp
from mcp.client.sse import sse_client

from core.logging import get_logger
from core.settings import settings

logger = get_logger(__name__)

#: Server ids of the catalog's tools whose names the gateway serves unprefixed.
_TOOL_SERVER_OVERRIDES: dict[str, str] = {
    "tavily-crawl": "tavily",
    "tavily-extract": "tavily",
    "tavily-map": "tavily",
    "tavily-search": "tavily",
    "download_paper": "arxiv",
    "search_papers": "arxiv",
    "read_paper": "arxiv",
    "list_papers": "arxiv",
}


def build_tool_cache_key(server_id: str, tool_name: str) -> str:
    """The canonical key of a tool: ``server_id/tool_name``, or the bare name without a server."""
    server = (server_id or "").strip()
    name = (tool_name or "").strip()
    return f"{server}/{name}" if server else name


def get_tool_cache_key(tool: Any) -> str:
    """The canonical key of a live tool (an MCP tool or a LangChain tool built from one)."""
    raw = getattr(tool, "name", "") or ""
    tool_name = raw if isinstance(raw, str) else str(raw)
    return build_tool_cache_key(_TOOL_SERVER_OVERRIDES.get(tool_name.lower(), ""), tool_name)


@asynccontextmanager
async def _gateway_session(endpoint: str) -> AsyncIterator[mcp.ClientSession]:
    """Connect to the gateway and finish the MCP handshake within the connect timeout.

    Connecting plus ``initialize()`` get ``connect_timeout_seconds`` between
    them; then the deadline is lifted, so whatever the caller does with the
    live session is never cut short by it.
    """
    timeout_seconds = settings.mcp.connect_timeout_seconds
    async with asyncio.timeout(timeout_seconds) as deadline:
        async with (
            sse_client(url=endpoint, timeout=timeout_seconds) as (read_stream, write_stream),
            mcp.ClientSession(read_stream, write_stream) as session,
        ):
            await session.initialize()
            deadline.reschedule(None)  # connected: the caller's work has no deadline
            yield session


@asynccontextmanager
async def optional_mcp_session() -> AsyncIterator[mcp.ClientSession | None]:
    """Yield an initialized MCP session, or ``None`` when MCP is not available.

    Only connecting and the handshake are covered: anything raised by the
    caller's own work inside the block propagates unchanged, never mistaken
    for a gateway outage.
    """
    if not settings.mcp.enabled:
        logger.info("mcp_disabled", "MCP gateway not configured; running without MCP tools")
        yield None
        return
    endpoint = settings.mcp.mcp_gateway_url
    ready = False
    try:
        logger.info("mcp_session_starting", "Opening MCP session", upstream_service="mcp_gateway")
        async with _gateway_session(endpoint) as session:
            ready = True
            logger.info(
                "mcp_session_ready", "MCP session initialized", upstream_service="mcp_gateway"
            )
            try:
                yield session
            finally:
                logger.info(
                    "mcp_session_closed", "MCP session closed", upstream_service="mcp_gateway"
                )
    except Exception as exc:
        if ready:
            raise  # the caller's work (or closing a live session) failed: not ours to swallow
        logger.warning(
            "mcp_session_unavailable",
            "MCP gateway unavailable; running without MCP tools",
            upstream_service="mcp_gateway",
            exception_type=type(exc).__name__,
            timeout_seconds=settings.mcp.connect_timeout_seconds,
        )
    if not ready:
        yield None


__all__ = ["build_tool_cache_key", "get_tool_cache_key", "optional_mcp_session"]
