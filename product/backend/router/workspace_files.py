"""The file routes shared by every workspace namespace (a system folder):
tree, read (raw or JSON, any version), write (new version),
delete, version history and the event ledger.

``build_file_router(namespace_dep)`` returns a router whose routes resolve
their namespace through ``namespace_dep`` (which also 404s an unknown system).
Every route is rate-limited and logged; the caller's ``X-Client-Id`` is the
actor of every write. Logic lives in ``utils.workspace``.
"""

from collections.abc import Awaitable, Callable
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from core.logging import get_logger
from core.security.client import Caller, get_caller
from core.security.rate_limit import workspace_rate_limit
from schema.systems import FileContentOut, FileEventOut, FileOut, FileWriteOut
from utils.systems import actor_for, read_write_request
from utils.workspace import (
    delete_file,
    file_content_out,
    get_file,
    list_events,
    list_tree,
    list_versions,
    put_file,
    raw_file_response,
)

logger = get_logger(__name__)

NamespaceDep = Callable[..., Awaitable[str]]


def build_file_router(namespace_dep: NamespaceDep) -> APIRouter:
    router = APIRouter()
    Namespace = Annotated[str, Depends(namespace_dep)]
    CallerDep = Annotated[Caller, Depends(get_caller)]
    Limited = Annotated[None, Depends(workspace_rate_limit)]
    Db = Annotated[AsyncSession, Depends(get_db)]

    @router.get("/files", response_model=list[FileOut], summary="The file tree (current versions)")
    async def file_tree(
        namespace: Namespace,
        _caller: CallerDep,
        _limited: Limited,
        db: Db,
        prefix: Annotated[str | None, Query(description="Only files under this folder")] = None,
    ) -> list[FileOut]:
        rows = await list_tree(db, namespace, prefix)
        logger.info(
            "workspace_tree_fetched",
            "Workspace tree fetched",
            namespace=namespace,
            item_count=len(rows),
        )
        return [FileOut.model_validate(r) for r in rows]

    @router.get(
        "/events",
        response_model=list[FileEventOut],
        summary="The namespace's audit ledger, newest first",
    )
    async def file_events(
        namespace: Namespace,
        _caller: CallerDep,
        _limited: Limited,
        db: Db,
        path: str | None = None,
        limit: Annotated[int, Query(ge=1, le=1000)] = 200,
    ) -> list[FileEventOut]:
        rows = await list_events(db, namespace, path, limit)
        return [FileEventOut.model_validate(r) for r in rows]

    @router.get(
        "/files/{path:path}/versions",
        response_model=list[FileOut],
        summary="Every version of one file, newest first",
    )
    async def file_versions(
        path: str, namespace: Namespace, _caller: CallerDep, _limited: Limited, db: Db
    ) -> list[FileOut]:
        return [FileOut.model_validate(r) for r in await list_versions(db, namespace, path)]

    @router.get(
        "/files/{path:path}",
        response_model=FileContentOut,
        summary="Read a file (raw bytes by default, ?format=json for metadata + content)",
    )
    async def read_file(
        path: str,
        namespace: Namespace,
        _caller: CallerDep,
        _limited: Limited,
        db: Db,
        version: Annotated[int | None, Query(ge=1)] = None,
        format: Literal["raw", "json"] = "raw",  # noqa: A002 - query parameter name
    ) -> Response | FileContentOut:
        row, content = await get_file(db, namespace, path, version)
        logger.info(
            "workspace_file_read",
            "Workspace file read",
            namespace=namespace,
            path=row.path,
            version=row.version,
        )
        if format == "json":
            return file_content_out(row, content)
        return raw_file_response(row, content)

    @router.put(
        "/files/{path:path}",
        response_model=FileWriteOut,
        summary="Write a new version (JSON {content, contentType, reason} or multipart 'file')",
    )
    async def write_file(
        path: str,
        request: Request,
        response: Response,
        namespace: Namespace,
        caller: CallerDep,
        _limited: Limited,
        db: Db,
    ) -> FileWriteOut:
        content, content_type, reason, meta = await read_write_request(request)
        row, changed = await put_file(
            db,
            namespace=namespace,
            path=path,
            content=content,
            content_type=content_type,
            actor=actor_for(caller.id),
            reason=reason,
            meta=meta,
        )
        await db.commit()
        logger.info(
            "workspace_file_written",
            "Workspace file written",
            namespace=namespace,
            path=row.path,
            version=row.version,
            changed=changed,
        )
        response.status_code = status.HTTP_201_CREATED if changed else status.HTTP_200_OK
        return FileWriteOut(file=FileOut.model_validate(row), changed=changed)

    @router.delete(
        "/files/{path:path}",
        status_code=status.HTTP_204_NO_CONTENT,
        summary="Delete a file (old versions are kept)",
    )
    async def remove_file(
        path: str,
        namespace: Namespace,
        caller: CallerDep,
        _limited: Limited,
        db: Db,
        reason: str | None = None,
    ) -> Response:
        await delete_file(db, namespace, path, actor=actor_for(caller.id), reason=reason)
        await db.commit()
        logger.info(
            "workspace_file_deleted", "Workspace file deleted", namespace=namespace, path=path
        )
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    return router
