"""Announce a new RegChange: POST to the backend and/or a Telegram message.

Both are optional and best effort: unset = ``skipped``, an error = ``failed``
(logged), never an exception. Inline Telegram buttons come later.
"""

from __future__ import annotations

from typing import Any

import httpx

from core.logging import get_logger
from core.settings import NotifySettings, settings

logger = get_logger(__name__)

BACKEND_PATH = "/internal/regulation/changes"
MAX_TELEGRAM = 3800  # Telegram's limit is 4096 characters


def backend_active(cfg: NotifySettings) -> bool:
    return bool(cfg.backend_internal_url)


def telegram_active(cfg: NotifySettings) -> bool:
    return bool(cfg.telegram_bot_token.get_secret_value() and cfg.telegram_chat_id)


def telegram_text(change: dict[str, Any]) -> str:
    lines = [
        "Regulation change detected",
        f"{change['id']}: kb {change.get('from_kb_version') or '-'} -> {change['to_kb_version']}",
        change.get("summary", ""),
        "",
    ]
    for e in [*change.get("provisions", []), *change.get("interpretations", [])][:8]:
        lines.append(f"- {e['id']} [{e['change']}, {e['change_type']}]: {e['rationale']}")
    impacted = change.get("impacted_requirements") or []
    if impacted:
        ids = ", ".join(i["requirement_id"] for i in impacted[:6])
        lines += ["", f"Requirements affected ({len(impacted)}): {ids}"]
    lines += ["", "Review and accept the candidate release in the copilot."]
    return "\n".join(lines)[:MAX_TELEGRAM]


def _backend_payload(change: dict[str, Any]) -> dict[str, Any]:
    keep = ("id", "from_kb_version", "to_kb_version", "created_at", "summary", "counts")
    payload = {k: change.get(k) for k in keep}
    payload["change_types"] = change.get("change_types")
    payload["impacted_requirements"] = change.get("impacted_requirements")
    payload["items"] = [
        {k: e.get(k) for k in ("id", "kind", "change", "change_type", "rationale", "diff")}
        for e in [*change.get("provisions", []), *change.get("interpretations", [])]
    ]
    return payload


async def notify_change(
    client: httpx.AsyncClient, change: dict[str, Any], cfg: NotifySettings | None = None
) -> dict[str, str]:
    cfg = cfg or settings.notify
    result = {"backend": "skipped", "telegram": "skipped"}
    if backend_active(cfg):
        url = cfg.backend_internal_url.rstrip("/") + BACKEND_PATH
        headers = {}
        if cfg.backend_internal_secret.get_secret_value():
            headers["X-Internal-Secret"] = cfg.backend_internal_secret.get_secret_value()
        try:
            resp = await client.post(
                url, json=_backend_payload(change), headers=headers, timeout=15
            )
            result["backend"] = "sent" if resp.status_code < 300 else f"http_{resp.status_code}"
        except httpx.HTTPError as exc:
            result["backend"] = "failed"
            logger.warning("notify_backend_failed", "Backend notify failed", error=str(exc))
    if telegram_active(cfg):
        token = cfg.telegram_bot_token.get_secret_value()
        url = f"{cfg.telegram_api_url.rstrip('/')}/bot{token}/sendMessage"
        body = {
            "chat_id": cfg.telegram_chat_id,
            "text": telegram_text(change),
            "disable_web_page_preview": True,
        }
        try:
            resp = await client.post(url, json=body, timeout=15)
            result["telegram"] = "sent" if resp.status_code < 300 else f"http_{resp.status_code}"
        except httpx.HTTPError as exc:
            result["telegram"] = "failed"
            logger.warning(
                "notify_telegram_failed", "Telegram notify failed", error=type(exc).__name__
            )
    logger.info("change_notified", "RegChange notifications", change_id=change["id"], **result)
    return result
