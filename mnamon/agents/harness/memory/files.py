"""The ``/memory/`` mount: a LangGraph ``BaseStore`` over one system's memory rows.

deepagents' ``StoreBackend`` turns a ``BaseStore`` into a filesystem, so the
agent uses ``ls``, ``read_file``, ``glob`` and ``grep`` on its memory like on any
other path, with no directory behind it:

* ``/MEMORY.md`` is derived from the rows on every read. A write to it is
  accepted and ignored: the index cannot drift from the entries it indexes.
* ``/audits/<audit_id>/<name>.md`` is one row. A ``write_file`` / ``edit_file``
  is allowed only into the run's own audit folder; the body is stored verbatim
  and the provenance columns come from the run's binding, never from the body.
  Anything else (another audit's folder, a delete, an unknown path, a full
  memory) is refused with an error the model reads.

Bound per run: one instance knows exactly one system, so a run can never reach
another system's memory whatever path it asks for.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterable
from datetime import datetime
from typing import Any

from langgraph.store.base import (
    BaseStore,
    GetOp,
    Item,
    ListNamespacesOp,
    PutOp,
    Result,
    SearchItem,
    SearchOp,
)

from core.logging import get_logger
from harness.memory.entries import (
    INDEX_KEY,
    MAX_CONTENT,
    MemoryRecord,
    build_index,
    entry_path,
    newest,
    normalise_key,
    parse_entry_key,
    summary_of,
)
from harness.memory.store import MemoryBinding, MemoryStoreProtocol, save_memory

logger = get_logger(__name__)


class MemoryWriteRefused(PermissionError):
    """A file-tool write the memory mount does not accept (the model reads the message)."""


def memory_namespace(system_id: str) -> tuple[str, ...]:
    """The store namespace of one system's memory."""
    return ("system_memory", system_id)


def _value(text: str, created: datetime, updated: datetime) -> dict[str, Any]:
    """The value shape deepagents' ``StoreBackend`` reads a file from."""
    return {
        "content": text,
        "encoding": "utf-8",
        "created_at": created.isoformat(),
        "modified_at": updated.isoformat(),
    }


class SystemMemoryFiles(BaseStore):
    """One run's ``/memory/`` mount (see module doc)."""

    supports_ttl = False

    def __init__(
        self,
        store: MemoryStoreProtocol,
        binding: MemoryBinding,
        *,
        max_entries: int,
        loop: asyncio.AbstractEventLoop | None = None,
    ) -> None:
        self._store = store
        self._binding = binding
        self._max_entries = max_entries
        self._loop = loop

    @property
    def binding(self) -> MemoryBinding:
        return self._binding

    @property
    def store(self) -> MemoryStoreProtocol:
        return self._store

    # -- the one abstract method -----------------------------------------
    async def abatch(self, ops: Iterable[Any]) -> list[Result]:
        results: list[Result] = []
        for op in ops:
            if isinstance(op, GetOp):
                results.append(await self._get(op))
            elif isinstance(op, PutOp):
                results.append(await self._put(op))
            elif isinstance(op, SearchOp):
                results.append(await self._search(op))
            elif isinstance(op, ListNamespacesOp):
                results.append([memory_namespace(self._binding.system_id)])
            else:
                raise NotImplementedError(f"SystemMemoryFiles does not implement {type(op)}")
        return results

    def batch(self, ops: Iterable[Any]) -> list[Result]:
        """Sync entry point: ``StoreBackend.ls`` / ``glob`` / ``grep`` are sync and
        arrive on a worker thread (``asyncio.to_thread``), so the call is bridged
        onto the service loop. Refused on the loop thread, where it would deadlock."""
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            pass
        else:
            raise RuntimeError("SystemMemoryFiles.batch() called on the event loop; use abatch().")
        if self._loop is None or not self._loop.is_running():
            return asyncio.run(self.abatch(ops))
        return asyncio.run_coroutine_threadsafe(self.abatch(ops), self._loop).result()

    # -- ops --------------------------------------------------------------
    def _check_namespace(self, namespace: tuple[str, ...]) -> None:
        if tuple(namespace) != memory_namespace(self._binding.system_id):
            raise MemoryWriteRefused("This run can only reach its own system's memory.")

    async def index_text(self) -> tuple[str, list[MemoryRecord]]:
        records = await self._store.list_system(self._binding.system_id)
        return build_index(self._binding.system_id, records), records

    async def _get(self, op: GetOp) -> Item | None:
        self._check_namespace(op.namespace)
        key = normalise_key(op.key)
        if key == INDEX_KEY:
            text, records = await self.index_text()
            stamp = newest(records)
            return Item(
                value=_value(text, stamp, stamp),
                key=key,
                namespace=tuple(op.namespace),
                created_at=stamp,
                updated_at=stamp,
            )
        parsed = parse_entry_key(key)
        if parsed is None:
            return None
        record = await self._store.get(self._binding.system_id, *parsed)
        if record is None:
            return None
        return Item(
            value=_value(record.content_md, record.created_at, record.updated_at),
            key=key,
            namespace=tuple(op.namespace),
            created_at=record.created_at,
            updated_at=record.updated_at,
        )

    async def _put(self, op: PutOp) -> None:
        self._check_namespace(op.namespace)
        key = normalise_key(op.key)
        binding = self._binding
        if key == INDEX_KEY:
            logger.info(
                "system_memory_index_write_ignored",
                "Ignored a write to the derived MEMORY.md",
                system_id=binding.system_id,
            )
            return None
        if op.value is None:
            raise MemoryWriteRefused(
                "Memory entries cannot be deleted with file tools; use the `forget` tool."
            )
        parsed = parse_entry_key(key)
        own = f"/memory/audits/{binding.audit_id}/" if binding.audit_id else None
        if parsed is None or own is None or parsed[0] != binding.audit_id:
            logger.warning(
                "system_memory_write_refused",
                "Refused a memory write outside the run's audit folder",
                system_id=binding.system_id,
                memory_key=key,
            )
            where = f"`{own}<name>.md`" if own else "nowhere (this run has no audit)"
            raise MemoryWriteRefused(
                f"Memory can only be written to {where}; prefer the `remember` tool."
            )
        raw = op.value.get("content") or ""
        if isinstance(raw, list):
            raw = "\n".join(str(part) for part in raw)
        body = str(raw)[:MAX_CONTENT]
        outcome = await save_memory(
            self._store,
            binding,
            name=parsed[1],
            summary=summary_of(body),
            content_md=body,
            max_entries=self._max_entries,
        )
        if outcome == "full":
            raise MemoryWriteRefused(
                f"System memory is full ({self._max_entries} entries); update an existing entry."
            )
        logger.info(
            "system_memory_file_written",
            "Wrote a memory entry through the file tools",
            system_id=binding.system_id,
            audit_id=binding.audit_id,
            memory_name=parsed[1],
            outcome=outcome,
        )
        return None

    async def _search(self, op: SearchOp) -> list[SearchItem]:
        self._check_namespace(op.namespace_prefix)
        namespace = tuple(op.namespace_prefix)
        text, records = await self.index_text()
        stamp = newest(records)
        items = [
            SearchItem(
                namespace=namespace,
                key=INDEX_KEY,
                value=_value(text, stamp, stamp),
                created_at=stamp,
                updated_at=stamp,
            )
        ]
        items += [
            SearchItem(
                namespace=namespace,
                key=record.key,
                value=_value(record.content_md, record.created_at, record.updated_at),
                created_at=record.created_at,
                updated_at=record.updated_at,
            )
            for record in sorted(records, key=lambda r: r.key)
        ]
        offset = op.offset or 0
        limit = op.limit if op.limit is not None else len(items)
        return items[offset : offset + limit]


__all__ = ["MemoryWriteRefused", "SystemMemoryFiles", "entry_path", "memory_namespace"]
