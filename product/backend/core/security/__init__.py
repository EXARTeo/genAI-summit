"""Caller identity (no login) and rate limiting — the backend's security boundary.

``client`` resolves the anonymous caller (``X-Client-Id`` + IP) and
``rate_limit`` throttles abuse. Import ``rate_limit`` names from their module;
this init stays lean so ``core.cache.integration`` can import it without cycles.
"""

from core.security.client import (
    ANONYMOUS_CLIENT_ID,
    Caller,
    get_caller,
    get_ws_caller,
    parse_client_id,
    resolve_client_ip,
)

__all__ = [
    "ANONYMOUS_CLIENT_ID",
    "Caller",
    "get_caller",
    "get_ws_caller",
    "parse_client_id",
    "resolve_client_ip",
]
