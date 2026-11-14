"""The agents filesystem: the definitions folder on disk and the run's mount table.

``layout`` says where the build-time agent definitions live. ``workspace``
assembles what a deep agent sees (virtual routes over ``agent_runtime`` and
the definition folder) and the write-deny ladder that goes with it;
``middleware`` is the filesystem middleware every stack runs those through.
``scratch_store`` / ``scratch_backend`` are the workspace's default route (one
branch's working files as rows, shared live by the orchestrator and its async
tasks) and ``sandbox_backend`` that same route plus ``execute`` in the sandbox
runner. A conversation's own files are :mod:`harness.conversation_files`.
"""

from harness.filesystem import layout
from harness.filesystem.middleware import (
    FILESYSTEM_TOOLS,
    PlatformFilesystemMiddleware,
    filesystem_middleware,
)
from harness.filesystem.scratch_backend import (
    BranchScratchBackend,
    current_branch_thread_id,
    resolve_branch_thread_id,
)
from harness.filesystem.scratch_store import BranchScratchStore
from harness.filesystem.workspace import (
    WORKSPACE_WRITE_DENY,
    build_workspace_backend,
    workspace_write_deny,
)

__all__ = [
    "FILESYSTEM_TOOLS",
    "WORKSPACE_WRITE_DENY",
    "BranchScratchBackend",
    "BranchScratchStore",
    "PlatformFilesystemMiddleware",
    "build_workspace_backend",
    "current_branch_thread_id",
    "filesystem_middleware",
    "layout",
    "resolve_branch_thread_id",
    "workspace_write_deny",
]
