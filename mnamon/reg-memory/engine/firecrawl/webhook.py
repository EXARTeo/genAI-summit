"""Firecrawl webhook verification and payload parsing.

Firecrawl signs every webhook: ``X-Firecrawl-Signature: sha256=<hex>`` where
``hex = HMAC-SHA256(secret, raw body)`` (docs.firecrawl.dev/webhooks/security).
Monitor events are ``monitor.page`` (one item per page: url, status
same/new/changed/removed/error, diff) and ``monitor.check.completed``.
"""

from __future__ import annotations

import hashlib
import hmac
from typing import Any

SIGNATURE_HEADER = "X-Firecrawl-Signature"


def sign(secret: str, body: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def verify_signature(secret: str, body: bytes, header: str | None) -> bool:
    if not secret or not header:
        return False
    return hmac.compare_digest(sign(secret, body).encode(), header.strip().encode())


def changed_urls(payload: dict[str, Any]) -> list[str]:
    """URLs reported as new/changed/removed by a webhook payload (monitor or scrape)."""
    items = payload.get("data")
    if isinstance(items, dict):
        items = [items]
    urls: list[str] = []
    for item in items or []:
        if not isinstance(item, dict):
            continue
        status = item.get("status") or (item.get("changeTracking") or {}).get("changeStatus")
        meta = item.get("metadata") or {}
        url = item.get("url") or meta.get("sourceURL") or meta.get("url")
        if url and status in {"new", "changed", "removed"}:
            urls.append(url)
    return urls
