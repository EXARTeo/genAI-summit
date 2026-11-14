"""System and workspace-file DTOs: create / patch a system, the file tree,
one file's content and its version history, and the seed-import summary."""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from schema.base import UTCDateTime

#: ``SYS-001``-style ids: letters, digits, ``.``, ``_``, ``-``.
SYSTEM_ID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$"


class SystemIn(BaseModel):
    id: str = Field(..., pattern=SYSTEM_ID_PATTERN)
    name: str = Field(..., min_length=1, max_length=200)
    status: str = Field("active", max_length=40)
    data: dict[str, Any] = Field(default_factory=dict)


class SystemPatch(BaseModel):
    """Every field optional; ``data`` is merged (top-level keys) into the stored one."""

    name: str | None = Field(None, min_length=1, max_length=200)
    status: str | None = Field(None, max_length=40)
    data: dict[str, Any] | None = None


class SystemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    status: str
    data: dict[str, Any] = Field(default_factory=dict)
    createdAt: UTCDateTime = Field(..., validation_alias="created_at")
    updatedAt: UTCDateTime = Field(..., validation_alias="updated_at")


class FileOut(BaseModel):
    """One version of a workspace file, without its bytes."""

    model_config = ConfigDict(from_attributes=True)

    namespace: str
    path: str
    version: int
    contentType: str = Field(..., validation_alias="content_type")
    size: int = Field(..., validation_alias="size_bytes")
    sha256: str = Field(..., validation_alias="blob_sha256")
    createdBy: str = Field(..., validation_alias="created_by")
    isCurrent: bool = Field(..., validation_alias="is_current")
    data: dict[str, Any] = Field(default_factory=dict)
    createdAt: UTCDateTime = Field(..., validation_alias="created_at")


class FileContentOut(FileOut):
    """A file with its content: ``text`` when it decodes as UTF-8, else ``dataB64``."""

    text: str | None = None
    dataB64: str | None = None


class FileWriteOut(BaseModel):
    """The result of a write: the current version, and whether it changed."""

    file: FileOut
    changed: bool


class FileTextIn(BaseModel):
    """A text write (the JSON form of ``PUT .../files/{path}``)."""

    content: str
    contentType: str | None = Field(None, max_length=255)
    reason: str | None = Field(None, max_length=2000)
    data: dict[str, Any] = Field(default_factory=dict)


class FromAttachmentIn(BaseModel):
    """Copy a conversation attachment (the caller's) into a system folder."""

    attachmentId: str
    path: str | None = Field(None, description="Target path; default uploads/<file name>")
    reason: str | None = Field(None, max_length=2000)


class FileEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    namespace: str
    path: str
    version: int | None = None
    action: str
    actor: str
    reason: str | None = None
    auditId: str | None = Field(None, validation_alias="audit_id")
    runId: str | None = Field(None, validation_alias="run_id")
    traceId: str | None = Field(None, validation_alias="trace_id")
    data: dict[str, Any] = Field(default_factory=dict)
    at: UTCDateTime


class SeedSystemResult(BaseModel):
    id: str
    created: bool
    filesWritten: int
    filesUnchanged: int


class SeedImportOut(BaseModel):
    root: str
    systems: list[SeedSystemResult]
    skippedDirs: list[str] = Field(default_factory=list)
