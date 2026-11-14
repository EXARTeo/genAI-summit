"""Firecrawl webhook: authenticate, map the changed URLs to catalog sources, start a check."""

from __future__ import annotations

import json

from fastapi import HTTPException, Request, status

from core.logging import get_logger
from core.security.client import check_internal_secret
from core.settings import settings
from engine.firecrawl.webhook import SIGNATURE_HEADER, changed_urls, verify_signature
from schema.watch import WebhookAccepted
from utils.state import get_catalog
from utils.watch import start_check

logger = get_logger(__name__)


def _authenticate(request: Request, body: bytes) -> None:
    secret = settings.fetch.firecrawl_webhook_secret.get_secret_value()
    if secret and verify_signature(secret, body, request.headers.get(SIGNATURE_HEADER)):
        return
    presented = request.headers.get(settings.security.internal_secret_header)
    if presented or not secret:
        check_internal_secret(presented)  # 401/503 unless valid (open only in local dev)
        return
    logger.warning("webhook_rejected", "Firecrawl webhook with an invalid signature")
    raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid webhook signature")


async def handle_firecrawl(request: Request) -> WebhookAccepted:
    body = await request.body()
    _authenticate(request, body)
    try:
        payload = json.loads(body or b"{}")
    except json.JSONDecodeError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "body is not JSON") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "body must be a JSON object")
    event = payload.get("type")
    urls = {u.rstrip("/") for u in changed_urls(payload)}
    catalog = get_catalog()
    matched = [s.id for s in catalog.sources if s.url and s.url.rstrip("/") in urls]
    check_id = None
    if matched:
        check_id, _ = start_check(matched, trigger="firecrawl_webhook")
    logger.info(
        "firecrawl_webhook",
        "Firecrawl webhook received",
        webhook_event=event,
        changed=len(urls),
        matched=len(matched),
    )
    return WebhookAccepted(accepted=True, event=event, matched_sources=matched, check_id=check_id)
