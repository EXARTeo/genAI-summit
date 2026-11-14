"""The ``POST /v1/exec`` contract, as the agents service's client sends and reads it
(mnamon/agents/harness/filesystem/sandbox_backend.py)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

KilledReason = Literal["timeout", "memory", "output_limit", "disk_limit", "error"]

ID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$"
SLUG_PATTERN = r"^[a-z0-9]+(?:-[a-z0-9]+)*$"


class ExecFile(BaseModel):
    """One file into the box: ``input/<rel>`` or ``output/<rel>``, base64."""

    model_config = ConfigDict(extra="forbid")

    path: str = Field(min_length=1, max_length=512)
    content_b64: str


class ExecRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    user_id: str = Field(pattern=ID_PATTERN)
    agent_slug: str = Field(min_length=1, max_length=64, pattern=SLUG_PATTERN)
    conversation_id: str = Field(pattern=ID_PATTERN)
    command: str = Field(min_length=1, max_length=16000)
    # None = the runner's default; above the runner's max is a 422.
    timeout_seconds: int | None = Field(None, ge=1)
    # The command's cwd, relative to the call's workdir.
    workdir: Literal["", ".", "input", "output"] = "output"
    files: list[ExecFile] = Field(default_factory=list)


class ReturnedFile(BaseModel):
    path: str
    content_b64: str
    size: int = Field(ge=0)


class ExecResult(BaseModel):
    exit_code: int | None = None
    stdout: str = ""
    stderr: str = ""
    truncated: bool = False
    duration_ms: int = Field(0, ge=0)
    killed_reason: KilledReason | None = None
    files: list[ReturnedFile] = Field(default_factory=list)
    files_truncated: bool = False
