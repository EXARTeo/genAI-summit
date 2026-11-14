"""``POST /telegram/webhook``: Telegram updates in webhook mode
(``TELEGRAM_WEBHOOK_URL`` set). Long polling needs no route.

Checked with ``X-Telegram-Bot-Api-Secret-Token`` = ``TELEGRAM_WEBHOOK_SECRET``
(required); the chat allow-list still applies to every update.
"""

import hmac
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from core.logging import get_logger
from core.security.rate_limit import internal_rate_limit
from core.settings import settings
from utils.telegram_gates import handle_update

router = APIRouter(dependencies=[Depends(internal_rate_limit)])
logger = get_logger(__name__)


@router.post("/webhook", include_in_schema=False)
async def webhook(
    update: dict[str, Any],
    db: Annotated[AsyncSession, Depends(get_db)],
    secret: Annotated[str | None, Header(alias="X-Telegram-Bot-Api-Secret-Token")] = None,
) -> dict[str, bool]:
    expected = settings.telegram.webhook_secret.get_secret_value()
    if not settings.telegram.enabled or not settings.telegram.webhook_url or not expected:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found.")
    if not secret or not hmac.compare_digest(secret.encode(), expected.encode()):
        logger.warning("telegram_webhook_refused", "Telegram webhook without a valid secret")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid secret.")
    await handle_update(db, update)
    return {"ok": True}
