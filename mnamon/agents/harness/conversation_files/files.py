"""One run's view of its conversation's files.

Built once per run and shared by everything in it that touches files (the
filesystem mounts, ``view_image``, ``present_artifact``, the sandbox backend).
Every file, uploads included, is a row of :class:`ConversationFileStore`; the
user's uploads sit under ``/conversation/input/``, written by the run route
(:mod:`harness.conversation_files.inputs`) and read-only to the agent. Paths
here are absolute virtual paths, already normalised.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from harness.conversation_files.store import ConversationFileStore, WriteOutcome


@dataclass(frozen=True)
class Entry:
    """A file as a listing shows it."""

    path: str
    size: int
    modified_at: str


@dataclass
class ConversationFiles:
    """The files of one (client, conversation), as one run reads and writes them."""

    client_id: str
    conversation_id: str
    agent_slug: str
    store: ConversationFileStore
    run_id: str | None = None

    # -- reads ---------------------------------------------------------------
    async def entries(self, directory: str) -> list[Entry]:
        """Every file at ``directory`` or below it, in path order."""
        rows = await self.store.list_files(self.client_id, self.conversation_id, directory)
        return [Entry(row.path, row.size, _iso(row.updated_at)) for row in rows]

    async def read_bytes(self, path: str) -> bytes | None:
        """A file's bytes, or None when there is none at ``path``."""
        return await self.store.read(self.client_id, self.conversation_id, path)

    async def read_many(self, file_paths: list[str]) -> dict[str, bytes]:
        """Several files' bytes, keyed by path, in one query."""
        return await self.store.read_many(self.client_id, self.conversation_id, file_paths)

    async def exists(self, path: str) -> bool:
        return await self.store.stat(self.client_id, self.conversation_id, path) is not None

    # -- writes --------------------------------------------------------------
    async def create(self, path: str, data: bytes) -> WriteOutcome:
        return await self.store.create(
            self.client_id,
            self.conversation_id,
            path,
            data,
            agent_slug=self.agent_slug,
            run_id=self.run_id,
        )

    async def replace(self, path: str, data: bytes) -> WriteOutcome:
        return await self.store.replace(
            self.client_id,
            self.conversation_id,
            path,
            data,
            agent_slug=self.agent_slug,
            run_id=self.run_id,
        )

    async def edit(self, path: str, transform: Callable[[bytes], bytes | None]) -> bool:
        return await self.store.edit(
            self.client_id,
            self.conversation_id,
            path,
            transform,
            agent_slug=self.agent_slug,
            run_id=self.run_id,
        )


def _iso(moment: datetime) -> str:
    return moment.isoformat()
