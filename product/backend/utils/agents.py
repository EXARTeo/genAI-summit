"""The backend's client for the agents service: start a run, resume it, read
its AG-UI SSE stream.

The agents service runs the agents; the backend never calls a model itself.
This module is the whole HTTP surface between the two. The same contract is
written out for the agents service's authors in the repo's ``docs/agents-contract.md``.

Endpoints (base ``AGENTS_SERVICE_URL``; ``{slug}`` is the conversation's agent)
------------------------------------------------------------------------------
``POST /agents/{slug}/stream``  — start a run; answers an AG-UI SSE stream.
``POST /agents/{slug}/resume``  — resume a run paused on HITL interrupt(s);
answers an SSE stream framed exactly like ``/stream``.

Headers on both: ``Content-Type: application/json``,
``Accept: text/event-stream``, ``X-Request-Id`` (when the request has one) and
``X-Internal-Service-Secret`` when ``AGENTS_SERVICE_SECRET`` is set.

``/stream`` body::

    {
      "messages": [Message, ...],          # see "Messages" below
      "config": Config
    }

``/resume`` body::

    {
      "config": Config,                    # the same block the run started with
      "thread_id": "<branch thread id>",
      "interrupt_id": "...", "decision": "approve" | "reject",
      "reason": str | null, "value": any | null,
      "decisions": [{"decision": ..., "reason": ...}] | null,
      "resumes": [ResumeItem, ...]         # only when several interrupts are
    }                                      # answered at once (keyed by id)

``Config``::

    {
      "run_config": {"configurable": {"thread_id": "<branch thread id>"}},
      "context": {"client_id": ..., "conversation_id": ..., "run_id": ...},
      "fork_from": {"thread_id": ..., "checkpoint_id": ...},   # optional
      "trace": {"trace_id", "parent_observation_id", "traceparent",
                "user_id", "session_id"}                       # optional
    }

* ``thread_id`` keys the agent's durable checkpointer, one per conversation
  branch. ``messages`` holds only the new user message when the branch thread
  already has state (or ``fork_from`` names the checkpoint to copy into this
  new branch thread first); otherwise the whole branch history (a cold seed).
* ``run_id`` is the backend's run (= assistant message) id.
* ``trace`` is present when Langfuse is on: nest the run's spans under
  ``parent_observation_id`` in trace ``trace_id`` (``utils/tracing.py``).

Messages: ``{"id", "role": "user" | "assistant", "content", "attachments"}``.
``content`` is a string, or a list of parts ``{"type": "text", "text"}`` and
``{"type": "image_url", "image_url": {"url": "data:<mime>;base64,..."}}`` (images
inline, for vision). ``attachments`` lists the other files of the message:
``{"id", "name", "mime_type", "size_bytes", "sha256", "origin",
"data_base64"}``; ``data_base64`` is null (``"omitted": "budget"``) once the
request's inline budget (``ATTACHMENT_MAX_TOTAL_BYTES``) is spent.

Response: ``text/event-stream`` of ``data: <AG-UI event JSON>`` frames
separated by a blank line. The backend reads ``RUN_ERROR`` (fails the run),
``CUSTOM HITL_INTERRUPT`` (pauses it, directly or wrapped in
``SUBAGENT_EVENT``), ``CUSTOM CHECKPOINT_COMMITTED {thread_id, checkpoint_id}``
(the branch head; never forwarded to the browser), ``CUSTOM PRESENT_ARTIFACT``
(a generated file, optionally with inline bytes), text / thinking / tool-call
events (content, reasoning, tool results capped at
``INFERENCE_TOOL_RESULT_MAX_CHARS``). Every other event is stored and relayed
untouched. A ``/resume`` for interrupts that are no longer pending answers 409
``{"detail": {"stale_interrupt_ids": [...], "pending_interrupt_ids": [...]}}``.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any
from urllib.parse import quote

import httpx

from core.logging import get_context, get_logger
from core.settings import settings

logger = get_logger(__name__)

SERVICE_AUTH_HEADER = "X-Internal-Service-Secret"


class AgentsServiceError(Exception):
    """The agents service answered a run request with an HTTP error."""

    def __init__(self, status_code: int, body: Any) -> None:
        super().__init__(f"agents service answered {status_code}")
        self.status_code = status_code
        self.body = body


def _agent_url(slug: str, action: str) -> str:
    base = settings.upstream.agents_service_url.rstrip("/")
    return f"{base}/agents/{quote(slug, safe='')}/{action}"


def agent_stream_url(slug: str) -> str:
    """``POST`` here to start a run of agent ``slug``."""
    return _agent_url(slug, "stream")


def agent_resume_url(slug: str) -> str:
    """``POST`` here to resume a paused run of agent ``slug``."""
    return _agent_url(slug, "resume")


def agents_headers() -> dict[str, str]:
    """The headers of every run request (see the module docstring)."""
    return {"Accept": "text/event-stream", **internal_headers()}


def internal_headers() -> dict[str, str]:
    """The correlation and service-secret headers of every agents-service call."""
    headers: dict[str, str] = {}
    request_id = get_context().get("request_id")
    if request_id:
        headers["X-Request-Id"] = str(request_id)
    secret = settings.upstream.agents_service_secret.get_secret_value()
    if secret:
        headers[SERVICE_AUTH_HEADER] = secret
    return headers


def resume_item(decision: dict[str, Any]) -> dict[str, Any]:
    """One HITL decision in the ``/resume`` shape."""
    return {
        "interrupt_id": decision.get("interrupt_id"),
        "decision": decision.get("decision", "approve"),
        "reason": decision.get("reason"),
        "value": decision.get("value"),
        "decisions": decision.get("decisions"),
    }


def resume_body(config: dict[str, Any], decisions: list[dict[str, Any]]) -> dict[str, Any]:
    """The ``/resume`` body: the first decision in the top-level fields and,
    when several interrupts are answered at once, all of them in ``resumes``."""
    thread_id = config.get("run_config", {}).get("configurable", {}).get("thread_id", "")
    body: dict[str, Any] = {"config": config, "thread_id": thread_id, **resume_item(decisions[0])}
    if len(decisions) > 1:
        body["resumes"] = [resume_item(decision) for decision in decisions]
    return body


def parse_sse(buffer: bytes, chunk: bytes) -> tuple[bytes, list[dict[str, Any]]]:
    """Feed one network chunk; returns the unconsumed rest and the complete events.

    Bytes are buffered (a UTF-8 character can straddle two chunks) and CRLF is
    normalised. Only ``data:`` lines count; a frame that is not a JSON object
    with a ``type`` is skipped.
    """
    buffer = (buffer + chunk).replace(b"\r\n", b"\n")
    events: list[dict[str, Any]] = []
    while b"\n\n" in buffer:
        raw_event, buffer = buffer.split(b"\n\n", 1)
        data_lines = [
            line[5:].strip()
            for line in raw_event.decode("utf-8", errors="replace").split("\n")
            if line.startswith("data:")
        ]
        payload = "\n".join(data_lines).strip()
        if not payload:
            continue
        try:
            value = json.loads(payload)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict) and value.get("type"):
            events.append(value)
    return buffer, events


def _json_or_none(response: httpx.Response) -> Any:
    try:
        return response.json()
    except ValueError:
        return None


async def agent_event_batches(
    url: str, body: dict[str, Any]
) -> AsyncIterator[list[dict[str, Any]]]:
    """POST a run request and yield its AG-UI events, one batch per network chunk.

    Raises :class:`AgentsServiceError` (with the parsed JSON body, if any) on
    an HTTP error status, and ``httpx.HTTPError`` when the service is
    unreachable or the stream breaks. Use with ``contextlib.aclosing`` so the
    connection closes when the caller stops early.
    """
    async with (
        httpx.AsyncClient(timeout=settings.http.inference_timeout) as client,
        client.stream("POST", url, json=body, headers=agents_headers()) as response,
    ):
        if response.status_code >= 400:
            await response.aread()
            raise AgentsServiceError(response.status_code, _json_or_none(response))
        buffer = b""
        async for chunk in response.aiter_bytes():
            buffer, events = parse_sse(buffer, chunk)
            if events:
                yield events
