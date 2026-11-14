"""Firecrawl webhooks, outside the X-Internal-Secret dependency: a valid
``X-Firecrawl-Signature`` (HMAC-SHA256 of the raw body with ``FIRECRAWL_WEBHOOK_SECRET``)
or a valid ``X-Internal-Secret`` header is required (checked in utils/webhooks.py)."""

from fastapi import APIRouter, Depends, Request, status

from core.security.rate_limit import write_rate_limit
from schema.watch import WebhookAccepted
from utils.webhooks import handle_firecrawl

router = APIRouter(dependencies=[Depends(write_rate_limit)])


@router.post("/firecrawl", response_model=WebhookAccepted, status_code=status.HTTP_202_ACCEPTED)
async def firecrawl_webhook(request: Request) -> WebhookAccepted:
    return await handle_firecrawl(request)
