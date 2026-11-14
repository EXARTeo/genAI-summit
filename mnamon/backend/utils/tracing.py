"""Langfuse traceability for runs — opt-in and fail-open.

One API: :func:`start_run_trace` opens the run's root observation
(``backend.run``) and returns a :class:`RunTrace`; the run engine sends
:meth:`RunTrace.upstream_context` to the agents service (so its LLM and tool
spans nest under this root) and calls :meth:`RunTrace.finish` once the run is
terminal. :func:`shutdown_tracing` flushes at shutdown.

* **Off** unless ``LANGFUSE_PUBLIC_KEY`` and ``LANGFUSE_SECRET_KEY`` are both set
  (``settings.langfuse.enabled``): no client is created, every call is a no-op
  and nothing leaves the process.
* **Fail-open.** Every SDK call is wrapped: a Langfuse that is down,
  misconfigured or raising costs the trace, never the run. Nothing here does
  network I/O on the caller's path — the SDK exports spans from its own
  background thread (OpenTelemetry batch processor) and flushes at exit.
* **Pseudonymous.** The trace's ``user_id`` is the keyed ``h:<16 hex>`` hash the
  logs use (:func:`core.logging.redaction.hash_identifier`), never the raw
  client id: the client id is what scopes a browser's conversations, so it must
  not sit readable in a trace store.

The trace id is derived from the run id (``create_trace_id(seed=run_id)``),
so a run's trace can be found from its id alone.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from langfuse import Langfuse, propagate_attributes

from core.logging import get_logger
from core.logging.redaction import hash_identifier
from core.settings import settings

logger = get_logger(__name__)

#: Name of the root observation of every run.
RUN_TRACE_NAME = "backend.run"
#: Longest text kept as the trace's input or output.
_MAX_IO_CHARS = 20000

_client: Langfuse | None = None
_client_failed = False


def _get_client() -> Langfuse | None:
    """The process-wide client, created on first use; None when tracing is off
    or the client could not be created (then it is not retried)."""
    global _client, _client_failed
    if _client is not None or _client_failed or not settings.langfuse.enabled:
        return _client
    try:
        _client = Langfuse(
            public_key=settings.langfuse.public_key,
            secret_key=settings.langfuse.secret_key.get_secret_value(),
            base_url=settings.langfuse.host,
            release=settings.app.version,
        )
    except Exception:
        _client_failed = True
        logger.warning(
            "langfuse_init_failed",
            "Langfuse client could not be created; tracing stays off",
            exc_info=True,
        )
        return None
    logger.info("langfuse_enabled", "Langfuse tracing is on")
    return _client


def _clip(text: str | None) -> str | None:
    if text is None:
        return None
    return text if len(text) <= _MAX_IO_CHARS else text[:_MAX_IO_CHARS] + "…"


@dataclass
class RunTrace:
    """The Langfuse root observation of one run, or a no-op stand-in.

    ``span`` is None when tracing is off or the root could not be opened.
    """

    span: Any = None
    metadata: dict[str, Any] = field(default_factory=dict)
    _finished: bool = False

    @property
    def active(self) -> bool:
        return self.span is not None

    def upstream_context(self) -> dict[str, str] | None:
        """What the agents service needs to nest its spans under this run.

        ``trace_id`` (32 hex) and ``parent_observation_id`` (16 hex) for the
        Langfuse SDK's ``trace_context``; ``traceparent`` (W3C) for any
        OpenTelemetry propagator; ``user_id`` / ``session_id`` so its spans
        carry the same trace attributes. None when tracing is off.
        """
        if self.span is None:
            return None
        try:
            trace_id, span_id = str(self.span.trace_id), str(self.span.id)
        except Exception:
            logger.warning(
                "langfuse_context_failed", "Could not read the run's trace ids", exc_info=True
            )
            return None
        return {
            "trace_id": trace_id,
            "parent_observation_id": span_id,
            "traceparent": f"00-{trace_id}-{span_id}-01",
            "user_id": str(self.metadata.get("user_id", "")),
            "session_id": str(self.metadata.get("conversation_id", "")),
        }

    def finish(self, *, status: str, output: str | None, error: str | None = None) -> None:
        """Record the run's outcome on the root observation and end it (once)."""
        if self.span is None or self._finished:
            return
        self._finished = True
        try:
            self.span.update(
                output=_clip(output),
                metadata={**self.metadata, "status": status},
                level="ERROR" if status == "failed" else None,
                status_message=error,
            )
            self.span.end()
        except Exception:
            logger.warning(
                "langfuse_finish_failed",
                "Could not end the run's Langfuse observation",
                exc_info=True,
                run_id=self.metadata.get("run_id"),
            )


def start_run_trace(
    *,
    run_id: str,
    conversation_id: str,
    client_id: str,
    agent_slug: str,
    user_text: str | None,
) -> RunTrace:
    """Open the run's root observation, or return a no-op :class:`RunTrace`.

    ``session_id`` is the conversation, ``user_id`` the client's pseudonym,
    ``input`` the user message that started the run.
    """
    client = _get_client()
    pseudonym = hash_identifier(client_id)
    metadata = {
        "run_id": run_id,
        "assistant_message_id": run_id,
        "conversation_id": conversation_id,
        "agent_slug": agent_slug,
        "user_id": pseudonym,
    }
    if client is None:
        return RunTrace(metadata=metadata)
    try:
        with propagate_attributes(
            user_id=pseudonym, session_id=conversation_id, trace_name=RUN_TRACE_NAME
        ):
            span = client.start_observation(
                trace_context={"trace_id": Langfuse.create_trace_id(seed=run_id)},
                name=RUN_TRACE_NAME,
                as_type="span",
                input=_clip(user_text),
                metadata=metadata,
            )
    except Exception:
        logger.warning(
            "langfuse_start_failed",
            "Could not open the run's Langfuse observation; the run is not traced",
            exc_info=True,
            run_id=run_id,
        )
        return RunTrace(metadata=metadata)
    return RunTrace(span=span, metadata=metadata)


def shutdown_tracing() -> None:
    """Flush queued spans and stop the exporter. Blocking (bounded by the
    exporter's timeout): call it from a thread at shutdown. The SDK also
    registers this at interpreter exit."""
    global _client
    client, _client = _client, None
    if client is None:
        return
    try:
        client.shutdown()
    except Exception:
        logger.warning(
            "langfuse_shutdown_failed", "Langfuse flush on shutdown failed", exc_info=True
        )
