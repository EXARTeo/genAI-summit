"""The chat copilot's tools over the product's own APIs (systems, audits, regulation)."""

from harness.tools.workspace_api.client import WorkspaceAPI, WorkspaceAPIError
from harness.tools.workspace_api.history import (
    ATTACH_UPLOAD_TO_AUDIT_DRAFT,
    AUDIT_NEEDS_RERUN,
    HISTORY_TOOL_NAMES,
)
from harness.tools.workspace_api.tools import (
    PROPOSE_SYSTEM_NOTE,
    START_AUDIT,
    WORKSPACE_TOOL_NAMES,
    WorkspaceScope,
    build_workspace_tool,
)

__all__ = [
    "ATTACH_UPLOAD_TO_AUDIT_DRAFT",
    "AUDIT_NEEDS_RERUN",
    "HISTORY_TOOL_NAMES",
    "PROPOSE_SYSTEM_NOTE",
    "START_AUDIT",
    "WORKSPACE_TOOL_NAMES",
    "WorkspaceAPI",
    "WorkspaceAPIError",
    "WorkspaceScope",
    "build_workspace_tool",
]
