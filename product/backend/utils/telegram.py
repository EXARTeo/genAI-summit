"""A minimal Telegram Bot API client (httpx, JSON in / JSON out).

Every call is best effort: an HTTP or API error is logged and returns None,
never raises. With no ``TELEGRAM_BOT_TOKEN`` :func:`get_bot` returns None and
the callers do nothing (logged once).
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit

import httpx

from core.logging import get_logger
from core.settings import settings

logger = get_logger(__name__)

#: A test seam: tests swap in an ``httpx.MockTransport`` (no network).
transport: httpx.AsyncBaseTransport | None = None
_disabled_logged = False


class TelegramClient:
    def __init__(self, token: str, api_url: str) -> None:
        self._base = f"{api_url.rstrip('/')}/bot{token}"

    async def call(self, method: str, http_timeout: float = 15.0, **params: Any) -> Any:
        body = {k: v for k, v in params.items() if v is not None}
        try:
            async with httpx.AsyncClient(timeout=http_timeout, transport=transport) as client:
                response = await client.post(f"{self._base}/{method}", json=body)
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            # Never log the URL: it carries the token.
            logger.warning(
                "telegram_call_failed",
                "Telegram call failed",
                method=method,
                error=type(exc).__name__,
            )
            return None
        if not payload.get("ok"):
            logger.warning(
                "telegram_api_error",
                "Telegram answered an error",
                method=method,
                code=payload.get("error_code"),
                description=str(payload.get("description"))[:200],
            )
            return None
        return payload.get("result")

    async def send_message(
        self, chat_id: str | int, text: str, reply_markup: dict[str, Any] | None = None
    ) -> dict[str, Any] | None:
        return await self.call(
            "sendMessage",
            chat_id=chat_id,
            text=text[:4000],
            reply_markup=reply_markup,
            disable_web_page_preview=True,
        )

    async def edit_message_text(
        self,
        chat_id: str | int,
        message_id: int,
        text: str,
        reply_markup: dict[str, Any] | None = None,
    ) -> Any:
        return await self.call(
            "editMessageText",
            chat_id=chat_id,
            message_id=message_id,
            text=text[:4000],
            reply_markup=reply_markup,
            disable_web_page_preview=True,
        )

    async def edit_reply_markup(
        self, chat_id: str | int, message_id: int, reply_markup: dict[str, Any]
    ) -> Any:
        return await self.call(
            "editMessageReplyMarkup",
            chat_id=chat_id,
            message_id=message_id,
            reply_markup=reply_markup,
        )

    async def answer_callback(self, callback_id: str, text: str) -> Any:
        return await self.call(
            "answerCallbackQuery", callback_query_id=callback_id, text=text[:190]
        )

    async def get_updates(self, offset: int | None, timeout: int) -> list[dict[str, Any]] | None:
        return await self.call(
            "getUpdates",
            http_timeout=timeout + 10,
            offset=offset,
            timeout=timeout,
            allowed_updates=["message", "callback_query"],
        )

    async def set_webhook(self, url: str, secret: str | None) -> Any:
        return await self.call(
            "setWebhook",
            url=url,
            secret_token=secret or None,
            allowed_updates=["message", "callback_query"],
        )

    async def delete_webhook(self) -> Any:
        return await self.call("deleteWebhook")


def get_bot() -> TelegramClient | None:
    """The bot, or None when Telegram is off (no token)."""
    global _disabled_logged
    if not settings.telegram.enabled:
        if not _disabled_logged:
            _disabled_logged = True
            logger.info("telegram_disabled", "TELEGRAM_BOT_TOKEN not set: Telegram is off")
        return None
    return TelegramClient(settings.telegram.bot_token.get_secret_value(), settings.telegram.api_url)


def inline_keyboard(rows: list[list[dict[str, str]]]) -> dict[str, Any]:
    return {"inline_keyboard": rows}


def button(text: str, data: str) -> dict[str, str]:
    return {"text": text, "callback_data": data}


def url_button(text: str, url: str) -> dict[str, str] | None:
    """A link button, or None for a local URL (Telegram refuses localhost links:
    the caller then puts the link in the message text)."""
    host = (urlsplit(url).hostname or "").lower()
    if host in {"localhost", "127.0.0.1", "0.0.0.0", "::1"} or "." not in host:  # noqa: S104
        return None
    return {"text": text, "url": url}
