"""System memory as rows in ``agent_runtime`` (table ``system_memories``).

One namespace per audited system: every pipeline step and every agent or
sub-agent working on any audit of ``SYS-00X`` reads and writes the same rows.
An entry belongs to the audit that recorded it (``audit_id`` is part of the
key), so the same lesson name can be recorded once per audit.

The service is the table's only reader and writer, so it owns the DDL and
creates it on boot (``agent_runtime`` has no alembic chain).

:func:`save_memory` is the one write path with the cap, shared by the
``remember`` tool and a ``write_file`` into ``/memory/audits/<current audit>/``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Protocol

from harness.memory.entries import MemoryRecord

_DDL = (
    """
    CREATE TABLE IF NOT EXISTS system_memories (
        system_id        text NOT NULL,
        audit_id         text NOT NULL,
        name             text NOT NULL,
        summary          text NOT NULL DEFAULT '',
        content_md       text NOT NULL DEFAULT '',
        step             text,
        agent_name       text,
        source_run_id    text,
        source_thread_id text,
        created_by       text NOT NULL DEFAULT 'agent',
        trust_level      text NOT NULL DEFAULT 'unknown',
        created_at       timestamptz NOT NULL DEFAULT now(),
        updated_at       timestamptz NOT NULL DEFAULT now(),
        PRIMARY KEY (system_id, audit_id, name)
    )
    """,
    "CREATE INDEX IF NOT EXISTS system_memories_recent_idx "
    "ON system_memories (system_id, updated_at DESC)",
)

_COMMENTS = (
    "COMMENT ON TABLE system_memories IS "
    "'Agent memory per audited system, surfaced to agents as /memory/. Not user-visible.'",
    "COMMENT ON COLUMN system_memories.content_md IS "
    "'The markdown the agent reads back, verbatim. Provenance lives in the other columns only.'",
)

_COLUMNS = (
    "system_id, audit_id, name, summary, content_md, step, agent_name, source_run_id, "
    "source_thread_id, created_by, trust_level, created_at, updated_at"
)


def _record(row: dict[str, Any]) -> MemoryRecord:
    return MemoryRecord(**{key: row[key] for key in _COLUMNS.replace(" ", "").split(",")})


class MemoryStoreProtocol(Protocol):
    """The typed API every memory consumer uses (the SQL store, or a test twin)."""

    async def get(self, system_id: str, audit_id: str, name: str) -> MemoryRecord | None: ...
    async def list_system(self, system_id: str) -> list[MemoryRecord]: ...
    async def count_system(self, system_id: str) -> int: ...
    async def upsert(self, record: MemoryRecord) -> MemoryRecord: ...
    async def delete(self, system_id: str, audit_id: str, name: str) -> bool: ...


class SystemMemoryStore:
    """``system_memories`` over the service's ``agent_runtime`` pool."""

    def __init__(self, pool: Any) -> None:
        self._pool = pool

    async def setup(self) -> None:
        async with self._pool.connection() as conn:
            for statement in (*_DDL, *_COMMENTS):
                await conn.execute(statement)

    async def get(self, system_id: str, audit_id: str, name: str) -> MemoryRecord | None:
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                f"SELECT {_COLUMNS} FROM system_memories "  # noqa: S608
                "WHERE system_id = %s AND audit_id = %s AND name = %s",
                (system_id, audit_id, name),
            )
            row = await cur.fetchone()
        return _record(row) if row else None

    async def list_system(self, system_id: str) -> list[MemoryRecord]:
        """Every entry of the system, newest first."""
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                f"SELECT {_COLUMNS} FROM system_memories WHERE system_id = %s "  # noqa: S608
                "ORDER BY updated_at DESC, audit_id, name",
                (system_id,),
            )
            rows = await cur.fetchall()
        return [_record(row) for row in rows]

    async def count_system(self, system_id: str) -> int:
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                "SELECT count(*) AS n FROM system_memories WHERE system_id = %s", (system_id,)
            )
            row = await cur.fetchone()
        return int(row["n"]) if row else 0

    async def upsert(self, record: MemoryRecord) -> MemoryRecord:
        """Insert or update by ``(system, audit, name)``; ``created_at`` survives an update.

        Idempotent on purpose: a node re-entered after an approval pause or a
        restart runs the same ``remember`` again and must produce the same row.
        """
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                f"""
                INSERT INTO system_memories ({_COLUMNS})
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, now(), now())
                ON CONFLICT (system_id, audit_id, name) DO UPDATE SET
                    summary = EXCLUDED.summary,
                    content_md = EXCLUDED.content_md,
                    step = EXCLUDED.step,
                    agent_name = EXCLUDED.agent_name,
                    source_run_id = EXCLUDED.source_run_id,
                    source_thread_id = EXCLUDED.source_thread_id,
                    trust_level = EXCLUDED.trust_level,
                    updated_at = now()
                RETURNING {_COLUMNS}
                """,  # noqa: S608
                (
                    record.system_id,
                    record.audit_id,
                    record.name,
                    record.summary,
                    record.content_md,
                    record.step,
                    record.agent_name,
                    record.source_run_id,
                    record.source_thread_id,
                    record.created_by,
                    record.trust_level,
                ),
            )
            row = await cur.fetchone()
        return _record(row) if row else record

    async def delete(self, system_id: str, audit_id: str, name: str) -> bool:
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                "DELETE FROM system_memories WHERE system_id = %s AND audit_id = %s AND name = %s",
                (system_id, audit_id, name),
            )
            return cur.rowcount > 0


@dataclass(frozen=True)
class MemoryBinding:
    """Whose memory a run reads and writes, and the provenance its writes carry.

    Built from the run context (``system_id``, ``audit_id``, ``step``), never
    from anything the model says. ``audit_id`` None means the run can read the
    system's memory but not record into it.
    """

    system_id: str
    audit_id: str | None = None
    step: str | None = None
    agent_name: str | None = None
    run_id: str | None = None
    thread_id: str | None = None
    trust_level: str = "unknown"

    @property
    def can_write(self) -> bool:
        return self.audit_id is not None


SaveOutcome = Literal["created", "updated", "full", "read_only"]


async def save_memory(
    store: MemoryStoreProtocol,
    binding: MemoryBinding,
    *,
    name: str,
    summary: str,
    content_md: str,
    max_entries: int,
) -> SaveOutcome:
    """Write one entry into the binding's current audit, within the system's cap.

    An update to an existing entry always goes through; a new entry is refused
    once the system holds ``max_entries``, so a full memory can still be corrected.
    """
    if binding.audit_id is None:
        return "read_only"
    existing = await store.get(binding.system_id, binding.audit_id, name)
    if existing is None and await store.count_system(binding.system_id) >= max_entries:
        return "full"
    await store.upsert(
        MemoryRecord(
            system_id=binding.system_id,
            audit_id=binding.audit_id,
            name=name,
            summary=summary,
            content_md=content_md,
            step=binding.step,
            agent_name=binding.agent_name,
            source_run_id=binding.run_id,
            source_thread_id=binding.thread_id,
            trust_level=binding.trust_level,
        )
    )
    return "updated" if existing is not None else "created"


__all__ = [
    "MemoryBinding",
    "MemoryStoreProtocol",
    "SaveOutcome",
    "SystemMemoryStore",
    "save_memory",
]
