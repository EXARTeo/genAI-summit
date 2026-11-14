"""Versioned workspace files in Postgres: system folders and memory.

A file is ``(namespace, path)``; every write adds a version row pointing at a
content-addressed blob (sha256), and every create / update / delete / read is
an append-only ``workspace_events`` row. Writing the same bytes as the current
version is a no-op (``changed=False``), which makes the seed import idempotent.

Namespaces:

* ``system:<id>``: the system dossier, plugins under ``plugins/<name>/``;
* ``memory:system:<id>``, ``memory:org``: active memory (humans write);
* ``memory:proposals``: the only namespace an agent may write.
"""

import base64
import hashlib
import mimetypes
import re
from typing import Any

from fastapi import HTTPException, Response, status
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import (
    SystemTable,
    WorkspaceEventTable,
    WorkspaceFileBlobTable,
    WorkspaceFileTable,
)
from core.settings import settings
from schema.systems import FileContentOut
from utils.attachments import ACTIVE_CONTENT_MIMES, encode_disposition

MEMORY_ORG = "memory:org"
MEMORY_PROPOSALS = "memory:proposals"
MAX_PATH_LENGTH = 512
_SEGMENT = re.compile(r"^[A-Za-z0-9._ ()+@=,-]{1,255}$")

#: Extensions ``mimetypes`` does not know (or knows differently) on every OS.
_EXTRA_TYPES = {
    ".yaml": "application/yaml",
    ".yml": "application/yaml",
    ".md": "text/markdown",
    ".csv": "text/csv",
    ".json": "application/json",
    ".txt": "text/plain",
    ".py": "text/x-python",
}
#: Served inline by the raw download (still sandboxed, nosniff).
_INLINE_TYPES = ("text/plain", "text/markdown", "text/csv", "application/json", "application/yaml")


def system_namespace(system_id: str) -> str:
    return f"system:{system_id}"


def system_memory_namespace(system_id: str) -> str:
    return f"memory:system:{system_id}"


def normalize_path(raw: str) -> str:
    """A safe relative path (``a/b/c.yaml``): no ``..``, no absolute, no empty
    segments, no control characters. 400 otherwise."""
    path = (raw or "").replace("\\", "/").strip().strip("/")
    segments = path.split("/") if path else []
    if (
        not segments
        or len(path) > MAX_PATH_LENGTH
        or any(seg in {".", ".."} or not _SEGMENT.fullmatch(seg) for seg in segments)
    ):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid file path.")
    return "/".join(segments)


def guess_content_type(path: str) -> str:
    lower = path.lower()
    for ext, mime in _EXTRA_TYPES.items():
        if lower.endswith(ext):
            return mime
    return mimetypes.guess_type(path)[0] or "application/octet-stream"


async def get_system_or_404(db: AsyncSession, system_id: str) -> SystemTable:
    system = await db.get(SystemTable, system_id)
    if system is None:
        raise HTTPException(status_code=404, detail="System not found.")
    return system


async def log_event(
    db: AsyncSession,
    *,
    namespace: str,
    path: str,
    action: str,
    actor: str,
    version: int | None = None,
    reason: str | None = None,
    audit_id: str | None = None,
    run_id: str | None = None,
    trace_id: str | None = None,
    data: dict[str, Any] | None = None,
) -> None:
    db.add(
        WorkspaceEventTable(
            namespace=namespace,
            path=path,
            version=version,
            action=action,
            actor=actor,
            reason=reason,
            audit_id=audit_id,
            run_id=run_id,
            trace_id=trace_id,
            data=data or {},
        )
    )


async def _current(db: AsyncSession, namespace: str, path: str) -> WorkspaceFileTable | None:
    return await db.scalar(
        select(WorkspaceFileTable).where(
            WorkspaceFileTable.namespace == namespace,
            WorkspaceFileTable.path == path,
            WorkspaceFileTable.is_current.is_(True),
        )
    )


async def put_file(
    db: AsyncSession,
    *,
    namespace: str,
    path: str,
    content: bytes,
    actor: str,
    content_type: str | None = None,
    reason: str | None = None,
    meta: dict[str, Any] | None = None,
    audit_id: str | None = None,
    run_id: str | None = None,
    trace_id: str | None = None,
) -> tuple[WorkspaceFileTable, bool]:
    """Write a new version (flushed, not committed). Same bytes and type as the
    current version → the current row, ``changed=False``, no new event."""
    path = normalize_path(path)
    if len(content) > settings.workspace.max_file_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="File exceeds the workspace size limit.",
        )
    content_type = (content_type or guess_content_type(path)).lower()
    sha = hashlib.sha256(content).hexdigest()
    current = await _current(db, namespace, path)
    if current is not None and current.blob_sha256 == sha and current.content_type == content_type:
        return current, False

    if await db.get(WorkspaceFileBlobTable, sha) is None:
        db.add(WorkspaceFileBlobTable(sha256=sha, data=content, size_bytes=len(content)))
    last_version = await db.scalar(
        select(func.max(WorkspaceFileTable.version)).where(
            WorkspaceFileTable.namespace == namespace, WorkspaceFileTable.path == path
        )
    )
    if current is not None:
        current.is_current = False
        await db.flush()  # free the one-current-row slot before the insert
    row = WorkspaceFileTable(
        namespace=namespace,
        path=path,
        version=(last_version or 0) + 1,
        blob_sha256=sha,
        content_type=content_type,
        size_bytes=len(content),
        created_by=actor,
        is_current=True,
        data=meta or {},
    )
    db.add(row)
    await log_event(
        db,
        namespace=namespace,
        path=path,
        version=row.version,
        action="update" if last_version else "create",
        actor=actor,
        reason=reason,
        audit_id=audit_id,
        run_id=run_id,
        trace_id=trace_id,
        data={"sha256": sha, "size": len(content)},
    )
    await db.flush()
    return row, True


async def list_tree(
    db: AsyncSession, namespace: str, prefix: str | None = None
) -> list[WorkspaceFileTable]:
    """The current version of every file in the namespace (optionally under a prefix)."""
    query = select(WorkspaceFileTable).where(
        WorkspaceFileTable.namespace == namespace, WorkspaceFileTable.is_current.is_(True)
    )
    if prefix:
        query = query.where(WorkspaceFileTable.path.startswith(normalize_path(prefix) + "/"))
    return list((await db.scalars(query.order_by(WorkspaceFileTable.path))).all())


async def get_file(
    db: AsyncSession, namespace: str, path: str, version: int | None = None
) -> tuple[WorkspaceFileTable, bytes]:
    """A file version and its bytes: the current one, or ``version``. 404 on a miss."""
    path = normalize_path(path)
    query = select(WorkspaceFileTable, WorkspaceFileBlobTable.data).join(
        WorkspaceFileBlobTable, WorkspaceFileBlobTable.sha256 == WorkspaceFileTable.blob_sha256
    )
    query = query.where(WorkspaceFileTable.namespace == namespace, WorkspaceFileTable.path == path)
    if version is None:
        query = query.where(WorkspaceFileTable.is_current.is_(True))
    else:
        query = query.where(WorkspaceFileTable.version == version)
    row = (await db.execute(query)).one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="File not found.")
    data = row[1]
    return row[0], data.tobytes() if isinstance(data, memoryview) else bytes(data)


async def list_versions(db: AsyncSession, namespace: str, path: str) -> list[WorkspaceFileTable]:
    path = normalize_path(path)
    rows = (
        await db.scalars(
            select(WorkspaceFileTable)
            .where(WorkspaceFileTable.namespace == namespace, WorkspaceFileTable.path == path)
            .order_by(WorkspaceFileTable.version.desc())
        )
    ).all()
    if not rows:
        raise HTTPException(status_code=404, detail="File not found.")
    return list(rows)


async def list_events(
    db: AsyncSession, namespace: str, path: str | None = None, limit: int = 200
) -> list[WorkspaceEventTable]:
    query = select(WorkspaceEventTable).where(WorkspaceEventTable.namespace == namespace)
    if path:
        query = query.where(WorkspaceEventTable.path == normalize_path(path))
    query = query.order_by(WorkspaceEventTable.id.desc()).limit(limit)
    return list((await db.scalars(query)).all())


async def delete_file(
    db: AsyncSession, namespace: str, path: str, *, actor: str, reason: str | None = None
) -> None:
    """Clear the current version (old versions stay; the next write continues numbering)."""
    path = normalize_path(path)
    current = await _current(db, namespace, path)
    if current is None:
        raise HTTPException(status_code=404, detail="File not found.")
    await db.execute(
        update(WorkspaceFileTable)
        .where(WorkspaceFileTable.id == current.id)
        .values(is_current=False)
    )
    await log_event(
        db,
        namespace=namespace,
        path=path,
        version=current.version,
        action="delete",
        actor=actor,
        reason=reason,
    )
    await db.flush()


def file_content_out(row: WorkspaceFileTable, content: bytes) -> FileContentOut:
    out = FileContentOut.model_validate(row)
    try:
        out.text = content.decode("utf-8")
    except UnicodeDecodeError:
        out.dataB64 = base64.b64encode(content).decode("ascii")
    return out


def raw_file_response(row: WorkspaceFileTable, content: bytes) -> Response:
    """The bytes, sandboxed: text-like types inline, everything else as a download."""
    mime = row.content_type.split(";")[0].strip().lower()
    inline = mime in _INLINE_TYPES and mime not in ACTIVE_CONTENT_MIMES
    return Response(
        content=content,
        media_type=row.content_type,
        headers={
            "Content-Disposition": encode_disposition(
                row.path.rsplit("/", 1)[-1], "inline" if inline else "attachment"
            ),
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "sandbox; default-src 'none'",
            "X-File-Version": str(row.version),
            "X-File-Sha256": row.blob_sha256,
        },
    )


async def dossier_version(db: AsyncSession, namespace: str) -> str:
    """A short hash of the namespace's current (path, sha256) pairs: changes
    whenever any file of the folder changes, so an audit can lock it."""
    rows = (
        await db.execute(
            select(WorkspaceFileTable.path, WorkspaceFileTable.blob_sha256)
            .where(
                WorkspaceFileTable.namespace == namespace, WorkspaceFileTable.is_current.is_(True)
            )
            .order_by(WorkspaceFileTable.path)
        )
    ).all()
    digest = hashlib.sha256("\n".join(f"{p}:{s}" for p, s in rows).encode()).hexdigest()
    return digest[:16]


async def plugin_ids(db: AsyncSession, system_id: str) -> list[str]:
    """``<system>.<plugin>`` for every ``plugins/<plugin>/...`` folder of a system."""
    paths = (
        await db.scalars(
            select(WorkspaceFileTable.path).where(
                WorkspaceFileTable.namespace == system_namespace(system_id),
                WorkspaceFileTable.is_current.is_(True),
                WorkspaceFileTable.path.startswith("plugins/"),
            )
        )
    ).all()
    names = {p.split("/")[1] for p in paths if p.count("/") >= 2}
    return [f"{system_id}.{name}" for name in sorted(names)]
