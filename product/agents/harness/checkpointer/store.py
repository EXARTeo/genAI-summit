"""Process-level handle to the durable LangGraph checkpointer.

The agents service runs a single shared ``AsyncPostgresSaver`` over a
long-lived ``psycopg_pool.AsyncConnectionPool`` (opened in the FastAPI
lifespan). Every ``/agents/{slug}/stream`` and ``/agents/{slug}/resume``
request builds a fresh agent instance, but they all compile against this one
saver; the thread is selected per-request via
``run_config.configurable.thread_id`` — the standard AsyncPostgresSaver model.

Threads persist indefinitely (no TTL). This module holds the accessors that
``main._lifespan`` populates and the agent runtime reads, kept separate so the
agent classes never import ``main``: the saver, and the same pool the stores
over ``agent_runtime`` (conversation files, branch scratch) borrow.
"""

from __future__ import annotations

from typing import Any

_checkpointer: Any | None = None
_runtime_pool: Any | None = None


def set_checkpointer(checkpointer: Any) -> None:
    """Install the process-wide saver. Called once from the lifespan."""
    global _checkpointer
    _checkpointer = checkpointer


def get_checkpointer() -> Any:
    """Return the shared saver. Raises if the lifespan hasn't wired it yet."""
    if _checkpointer is None:
        raise RuntimeError(
            "Durable checkpointer is not initialized. The FastAPI lifespan must "
            "call set_checkpointer() before any agent run."
        )
    return _checkpointer


def has_checkpointer_initialized() -> bool:
    """Cheap probe: is the shared saver wired? (Not a per-thread existence check.)"""
    return _checkpointer is not None


def set_runtime_pool(pool: Any) -> None:
    """Install the ``agent_runtime`` pool the stores share. Called once from the lifespan."""
    global _runtime_pool
    _runtime_pool = pool


def get_runtime_pool() -> Any:
    """The shared ``agent_runtime`` pool. Raises if the lifespan has not opened it."""
    if _runtime_pool is None:
        raise RuntimeError("The agent_runtime pool is not initialized.")
    return _runtime_pool


def has_runtime_pool() -> bool:
    """Whether the ``agent_runtime`` pool is wired (false in unit tests without one)."""
    return _runtime_pool is not None
