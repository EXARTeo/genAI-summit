"""The internal memory view: one system's ``MEMORY.md`` and entries, read-only."""

from typing import Any

from harness.memory import MemoryRecord, build_index, entry_path
from schema.memory import MemoryEntryOut, SystemMemoryOut


def _entry(record: MemoryRecord) -> MemoryEntryOut:
    return MemoryEntryOut(
        path=entry_path(record.audit_id, record.name),
        auditId=record.audit_id,
        name=record.name,
        summary=record.summary,
        contentMd=record.content_md,
        step=record.step,
        agentName=record.agent_name,
        sourceRunId=record.source_run_id,
        sourceThreadId=record.source_thread_id,
        createdBy=record.created_by,
        trustLevel=record.trust_level,
        createdAt=record.created_at,
        updatedAt=record.updated_at,
    )


async def read_system_memory(store: Any, system_id: str) -> SystemMemoryOut:
    """Everything the agents remember about ``system_id`` (empty when nothing)."""
    records = await store.list_system(system_id)
    return SystemMemoryOut(
        systemId=system_id,
        index=build_index(system_id, records),
        entries=[_entry(record) for record in records],
    )
