"""Deepagents workspace assembly: the mount table and its write-deny ladder.

It assembles the two things a deep agent hands to ``create_deep_agent`` for its
filesystem:

* the ``CompositeBackend`` — the map of virtual routes onto the stores and the
  image folder that back them, and
* the write-deny permission ladder (:func:`workspace_write_deny`).

These live together on purpose: each write-deny rule targets a mount route by
path, so the routes and their permissions must stay in sync.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from deepagents import FilesystemPermission
from deepagents.backends import CompositeBackend, FilesystemBackend
from deepagents.backends.protocol import SandboxBackendProtocol

from core.settings import settings
from harness.conversation_files import ConversationFiles, ConversationFilesBackend
from harness.conversation_files.paths import (
    CONVERSATION_HISTORY_ROOT,
    CONVERSATION_ROOT,
    LARGE_TOOL_RESULTS_ROOT,
)
from harness.filesystem.sandbox_backend import RemoteSandboxBackend
from harness.filesystem.scratch_backend import BranchScratchBackend
from harness.filesystem.scratch_store import BranchScratchStore

# Write-deny rules over the built-in filesystem tools, shared by every deep
# agent. Confinement is mainly structural (CompositeBackend + virtual mounts);
# these pin the read-only surfaces: the deepagents offload/archive dirs and
# /conversation/input/ (the user's uploads; the agent writes to output/). No
# catch-all deny, which would block reading those. `execute` does not go
# through these rules: it runs in the sandbox runner, which receives only the
# conversation's input/ and output/ and writes back only output/.
WORKSPACE_WRITE_DENY: list[FilesystemPermission] = [
    FilesystemPermission(operations=["write"], paths=["/large_tool_results{,/**}"], mode="deny"),
    FilesystemPermission(operations=["write"], paths=["/conversation_history{,/**}"], mode="deny"),
    FilesystemPermission(operations=["write"], paths=["/conversation/input{,/**}"], mode="deny"),
]

# The agent's own definition folder. Read-only: letting a run rewrite its own
# definition would let an agent edit its next system prompt.
_REFERENCE_WRITE_DENY = FilesystemPermission(
    operations=["write"], paths=["/reference{,/**}"], mode="deny"
)


def workspace_write_deny(*, include_reference: bool = False) -> list[FilesystemPermission]:
    """The write-deny ladder for a run, matched to the routes it mounts.

    A function rather than a constant because ``/reference/`` is conditional:
    callers derive both the mount and the rule from the same flag.
    """
    rules = list(WORKSPACE_WRITE_DENY)
    if include_reference:
        rules.append(_REFERENCE_WRITE_DENY)
    return rules


def build_workspace_backend(
    *,
    client_id: str,
    agent_slug: str,
    files: ConversationFiles,
    reference_dir: Path | None = None,
    branch_thread_id: str | None = None,
) -> CompositeBackend:
    """This run's ``CompositeBackend``. Nothing in it is a directory a run can write::

        /conversation/          → agent_runtime rows   (this conversation's files)
          /conversation/input/  → agent_runtime rows   (the user's uploads, read-only)
          /conversation/output/ → agent_runtime rows   (deliverables; present_artifact)
        /large_tool_results/    → agent_runtime rows   (offloaded tool results, read-only)
        /conversation_history/  → agent_runtime rows   (offloaded history, read-only)
        /reference/             → the agent's definition folder (read-only, optional)
        default (/…)            → agent_runtime rows   (the branch scratch store)
                                  via BranchScratchBackend, or RemoteSandboxBackend
                                  (the same + `execute`, when sandbox execution is active)

    ``/conversation/`` is keyed by the conversation, so the orchestrator and
    every sub-agent of the conversation (blocking or async) see the same files.
    The default route is keyed by ``(conversation_id, branch_thread_id)``: the
    orchestrator and every async task of its tree carry the same branch thread
    id (``resolve_branch_thread_id``), so they share it live too.
    """
    try:
        # The conversation mounts run their sync methods on this loop.
        loop: asyncio.AbstractEventLoop | None = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    # Sandbox-execution kill switch (fail-closed). deepagents exposes `execute`
    # exactly when the default backend implements SandboxBackendProtocol, so
    # while execution is off a sandbox-capable default is refused outright:
    # no refactor can silently open a code-execution path.
    sandbox_active = settings.filesystem.sandbox_execution_active
    conversation_mount = ConversationFilesBackend(files, CONVERSATION_ROOT, loop=loop)
    scratch = {
        "client_id": client_id,
        "agent_slug": agent_slug,
        "conversation_id": files.conversation_id,
        "branch_thread_id": branch_thread_id,
        "loop": loop,
    }
    default_backend = (
        RemoteSandboxBackend(
            **scratch,
            scratch_store=BranchScratchStore(),
            files=files,
            conversation_mount=conversation_mount,
        )
        if sandbox_active
        else BranchScratchBackend(**scratch, store=BranchScratchStore())
    )
    if not sandbox_active and isinstance(default_backend, SandboxBackendProtocol):
        raise RuntimeError(
            "Workspace default backend is sandbox-capable but SANDBOX_EXECUTION_ENABLED "
            "is false (or SANDBOX_RUNNER_URL is unset): refusing to expose an execution path."
        )
    routes: dict[str, object] = {
        # One route for the whole conversation (uploads included), so a grep
        # from the root sees each file once.
        "/conversation/": conversation_mount,
        # deepagents' offload prefixes: the conversation's too, kept out of
        # /conversation/ so their write-deny cannot be sidestepped from there.
        "/large_tool_results/": ConversationFilesBackend(files, LARGE_TOOL_RESULTS_ROOT, loop=loop),
        "/conversation_history/": ConversationFilesBackend(
            files, CONVERSATION_HISTORY_ROOT, loop=loop
        ),
    }
    if reference_dir is not None:
        # The agent's definition ships in the image: build-time content,
        # identical for every client and not writable at runtime.
        routes["/reference/"] = FilesystemBackend(root_dir=str(reference_dir), virtual_mode=True)
    return CompositeBackend(default=default_backend, routes=routes)
