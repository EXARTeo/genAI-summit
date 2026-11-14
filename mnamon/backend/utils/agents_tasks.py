"""The backend's client for the agents service's internal task API.

The agents service owns and runs every background task; the backend reads and
acts on them through these calls (``docs/contracts/agents-contract.md`` § Async
sub-agents). Every call names the acting browser (``client_id``), and the
agents service answers 404 for a task of another one. ``client_id`` goes only
here, never into a log or a trace.

| Call | Upstream |
| --- | --- |
| :func:`agents_get_task` | ``GET /tasks/{id}?client_id=`` |
| :func:`agents_list_unnotified` | ``GET /tasks/unnotified?limit=&client_id=&conversation_id=`` |
| :func:`agents_mark_notified` | ``POST /tasks/{id}/notified {"client_id"}`` |
| :func:`agents_task_action` | ``POST /tasks/{id}/cancel`` / ``/resume`` |
| :func:`agents_cancel_scope` | ``POST /tasks/cancel-scope {"client_id", "conversation_id"}`` |

Transport errors and 5xx raise :class:`AgentsTaskError`; the callers decide
what a 404 or 409 means.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

import httpx
from fastapi import status

from core.logging import get_logger
from core.settings import settings
from schema.tasks import OutboxItem, TaskOut
from utils.agents import internal_headers

logger = get_logger(__name__)


class AgentsTaskError(Exception):
    """The agents service's task API failed or answered something unusable."""


def _tasks_url(suffix: str = "") -> str:
    return f"{settings.upstream.agents_service_url.rstrip('/')}/tasks{suffix}"


def _task_url(task_id: str, suffix: str = "") -> str:
    return _tasks_url(f"/{quote(task_id, safe='')}{suffix}")


async def _call(method: str, url: str, **kwargs: Any) -> httpx.Response:
    """One call to the agents service. Transport errors and 5xx raise
    :class:`AgentsTaskError`; any other status is the caller's to read."""
    try:
        async with httpx.AsyncClient(timeout=settings.http.agents_timeout) as client:
            response = await client.request(method, url, headers=internal_headers(), **kwargs)
    except httpx.HTTPError as exc:
        raise AgentsTaskError(type(exc).__name__) from exc
    if response.status_code >= status.HTTP_500_INTERNAL_SERVER_ERROR:
        raise AgentsTaskError(f"agents service answered {response.status_code}")
    return response


def task_from_response(response: httpx.Response) -> TaskOut:
    """The ``TaskOut`` of a 200 answer; :class:`AgentsTaskError` when unusable."""
    try:
        return TaskOut.model_validate(response.json())
    except ValueError as exc:
        raise AgentsTaskError("unusable task in the agents service's answer") from exc


async def agents_get_task(task_id: str, client_id: str) -> TaskOut | None:
    """One task, or None when it is not that client's (or does not exist)."""
    response = await _call("GET", _task_url(task_id), params={"client_id": client_id})
    if response.status_code == status.HTTP_404_NOT_FOUND:
        return None
    if response.status_code != status.HTTP_200_OK:
        raise AgentsTaskError(f"agents service answered {response.status_code}")
    task = task_from_response(response)
    return task if task.client_id == client_id else None


async def agents_list_unnotified(
    limit: int, *, client_id: str | None = None, conversation_id: str | None = None
) -> list[OutboxItem]:
    """Settled depth-1 tasks whose wake-up has not been handled.

    ``client_id`` / ``conversation_id`` narrow it; the result is filtered here
    too, so an agents service that ignores them is still correct. Malformed
    items are skipped.
    """
    params: dict[str, Any] = {"limit": limit}
    if client_id:
        params["client_id"] = client_id
    if conversation_id:
        params["conversation_id"] = conversation_id
    response = await _call("GET", _tasks_url("/unnotified"), params=params)
    if response.status_code != status.HTTP_200_OK:
        raise AgentsTaskError(f"agents service answered {response.status_code}")
    try:
        body = response.json()
    except ValueError as exc:
        raise AgentsTaskError("unusable unnotified list") from exc
    items: list[OutboxItem] = []
    for raw in body if isinstance(body, list) else ():
        try:
            item = OutboxItem.model_validate(raw)
        except ValueError:
            logger.warning(
                "task_unnotified_item_invalid", "Skipped a malformed unnotified task item"
            )
            continue
        if client_id and item.client_id != client_id:
            continue
        if conversation_id and item.conversation_id != conversation_id:
            continue
        items.append(item)
    return items


async def agents_mark_notified(task_id: str, client_id: str) -> bool:
    """True once the agents service recorded the wake-up as handled (a 404
    means the task is gone, which is just as final)."""
    response = await _call("POST", _task_url(task_id, "/notified"), json={"client_id": client_id})
    return response.status_code in (
        status.HTTP_200_OK,
        status.HTTP_204_NO_CONTENT,
        status.HTTP_404_NOT_FOUND,
    )


async def agents_task_action(
    task_id: str, client_id: str, action: str, body: dict[str, Any]
) -> httpx.Response:
    """``POST /tasks/{id}/{action}`` with the acting client; the raw answer."""
    return await _call(
        "POST", _task_url(task_id, f"/{action}"), json={"client_id": client_id, **body}
    )


async def agents_cancel_scope(client_id: str, conversation_id: str) -> int:
    """Stop every task of a conversation; how many were stopped.

    A 404 (an agents service without the task API) means nothing to stop.
    """
    response = await _call(
        "POST",
        _tasks_url("/cancel-scope"),
        json={"client_id": client_id, "conversation_id": conversation_id},
    )
    if response.status_code == status.HTTP_404_NOT_FOUND:
        return 0
    if response.status_code != status.HTTP_200_OK:
        raise AgentsTaskError(f"agents service answered {response.status_code}")
    try:
        cancelled = response.json().get("cancelled", 0)
    except (ValueError, AttributeError):
        cancelled = 0
    return cancelled if isinstance(cancelled, int) else 0
