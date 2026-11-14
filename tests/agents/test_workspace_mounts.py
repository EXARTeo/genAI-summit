"""Mount-table invariants for a deep agent's workspace filesystem.

The agent's only view of storage is the ``CompositeBackend`` assembled in
``harness.filesystem.workspace``, so these tests pin what is easy to break
silently:

* a route that is supposed to exist resolves to what it claims (a missing
  route degrades to the branch scratch default, where every read answers
  "not found": inert, with no error anywhere), and one that must not exist is
  absent;
* the write-deny ladder stays scoped to mounted routes, which deepagents itself
  requires as soon as the default backend supports execution.
"""

from __future__ import annotations

import pytest
from conftest import CLIENT_ID
from deepagents.backends import FilesystemBackend

from harness.conversation_files import ConversationFiles, ConversationFilesBackend
from harness.conversation_files.store import ConversationFileStore
from harness.filesystem.workspace import (
    WORKSPACE_WRITE_DENY,
    build_workspace_backend,
    workspace_write_deny,
)


def _files(agent_slug: str = "agent-1") -> ConversationFiles:
    """A run's conversation files over a pool that is never queried here."""
    return ConversationFiles(
        client_id=CLIENT_ID,
        conversation_id="conv-1",
        agent_slug=agent_slug,
        store=ConversationFileStore(object()),
    )


def _backend(*, reference_dir=None):
    return build_workspace_backend(
        client_id=CLIENT_ID, agent_slug="agent-1", files=_files(), reference_dir=reference_dir
    )


def _denies_writes_under(rules, fragment: str) -> bool:
    return any(
        rule.mode == "deny"
        and "write" in rule.operations
        and any(fragment in path for path in rule.paths)
        for rule in rules
    )


def test_reference_route_absent_without_a_definition_dir():
    """An agent defined in code has no definition folder, and its package dir
    holds source, which must never be mountable.

    Absence is the whole assertion: an unrouted path falls through to the
    branch scratch default, which answers "not found" without any
    misconfiguration being reported anywhere.
    """
    assert "/reference/" not in _backend().routes


def test_a_definition_folder_is_mounted_from_the_image(tmp_path):
    definition = tmp_path / "definition"
    definition.mkdir()
    route = _backend(reference_dir=definition).routes["/reference/"]
    # Build-time content: identical for every client and not tamperable at
    # runtime, so it stays a directory rather than becoming rows.
    assert isinstance(route, FilesystemBackend)


def test_agent_can_read_a_file_from_its_definition_dir(tmp_path):
    """The whole point of the mount: material shipped beside AGENT.md is readable
    at ``/reference/<path>`` during a run.

    Asserted through an actual backend read rather than the route table,
    because "the route exists" and "the file is reachable" are not the same
    claim.
    """
    definition = tmp_path / "agents_seed" / "my-agent"
    definition.mkdir(parents=True)
    (definition / "notes.md").write_text("house style", encoding="utf-8")

    result = _backend(reference_dir=definition).read("/reference/notes.md")

    assert result.error is None
    assert result.file_data["content"] == "house style"


def test_the_reference_mount_cannot_escape_its_folder(tmp_path):
    definition = tmp_path / "definition"
    definition.mkdir()
    (tmp_path / "secret.txt").write_text("outside", encoding="utf-8")

    # deepagents' virtual mode refuses the traversal outright; the run's
    # ToolErrorMiddleware turns the raise into a tool error for the model.
    with pytest.raises(ValueError, match="traversal"):
        _backend(reference_dir=definition).read("/reference/../secret.txt")


def test_reference_write_deny_tracks_the_mount():
    """Routes and permissions are derived from one flag, so they cannot drift:
    no mount, no rule; mount, read-only."""
    assert not _denies_writes_under(workspace_write_deny(), "/reference")
    assert _denies_writes_under(workspace_write_deny(include_reference=True), "/reference")


def test_the_base_ladder_pins_the_read_only_surfaces():
    for fragment in ("/conversation/input", "/large_tool_results", "/conversation_history"):
        assert _denies_writes_under(WORKSPACE_WRITE_DENY, fragment), fragment
    # Output is where the agent writes: denying it would break every deliverable.
    assert not _denies_writes_under(WORKSPACE_WRITE_DENY, "/conversation/output")


def test_the_ladder_is_a_fresh_list_each_time():
    rules = workspace_write_deny()
    rules.clear()
    assert workspace_write_deny() == list(WORKSPACE_WRITE_DENY)


@pytest.mark.parametrize("include_reference", [False, True])
def test_every_deny_rule_targets_a_mounted_route(tmp_path, include_reference):
    """No write-deny rule may name a route this run didn't mount.

    A rule for an unmounted route is dead config today, and becomes a hard
    failure the day the default backend gains execution support (deepagents
    checks that every rule is scoped to a route only in that case). Compared
    on the leading path segment rather than by literal prefix, because the
    rules are brace patterns (``/reference{,/**}``) that never literally start
    with a route string (``/reference/``).
    """
    definition = tmp_path / "definition"
    definition.mkdir()
    backend = _backend(reference_dir=definition if include_reference else None)
    mounted = {prefix.strip("/").split("/")[0] for prefix in backend.routes}
    rules = workspace_write_deny(include_reference=include_reference)

    unscoped = [
        path
        for rule in rules
        for path in rule.paths
        if path.lstrip("/").split("{")[0].split("/")[0] not in mounted
    ]
    assert not unscoped, f"deny rules outside every mounted route: {unscoped}"


def test_the_conversation_mounts_are_one_store_with_no_overlapping_routes():
    """One ``/conversation/`` route (uploads inside it) rather than overlapping
    ones, so a grep from the root sees each file once; the offload prefixes
    are routes of their own, outside ``/conversation/``, so their write-deny
    cannot be sidestepped through it."""
    routes = _backend().routes

    conversation_routes = [prefix for prefix in routes if prefix.startswith("/conversation")]
    assert sorted(conversation_routes) == ["/conversation/", "/conversation_history/"]
    for prefix in ("/conversation/", "/large_tool_results/", "/conversation_history/"):
        assert isinstance(routes[prefix], ConversationFilesBackend)
    assert set(routes) == {"/conversation/", "/large_tool_results/", "/conversation_history/"}


def test_the_conversation_routes_share_the_runs_files():
    files = _files()
    routes = build_workspace_backend(client_id=CLIENT_ID, agent_slug="agent-1", files=files).routes
    for prefix in ("/conversation/", "/large_tool_results/", "/conversation_history/"):
        assert routes[prefix]._files is files
