"""The durable LangGraph checkpointer and the ``agent_runtime`` pool.

``bootstrap.init_durable_checkpointer`` (called from ``main._lifespan``) ensures
the ``agent_runtime`` database exists, opens the psycopg pool, creates the
stores' tables and installs one shared ``AsyncPostgresSaver``; ``store`` holds
the accessors; ``fork`` seeds a new branch thread from a parent checkpoint on
edit/retry.
"""

from harness.checkpointer.bootstrap import init_durable_checkpointer
from harness.checkpointer.store import (
    get_checkpointer,
    get_runtime_pool,
    has_checkpointer_initialized,
    has_runtime_pool,
    set_checkpointer,
    set_runtime_pool,
)

__all__ = [
    "get_checkpointer",
    "get_runtime_pool",
    "has_checkpointer_initialized",
    "has_runtime_pool",
    "init_durable_checkpointer",
    "set_checkpointer",
    "set_runtime_pool",
]
