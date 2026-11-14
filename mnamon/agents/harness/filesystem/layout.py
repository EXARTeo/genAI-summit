"""Where the service's build-time content lives on disk, and the id check for paths.

The only thing left on disk is the folder of declarative agent definitions
(``AGENTS_DIR``, by default the ``definitions/`` folder in the image)::

    <agents_dir>/<agent_slug>/
        agent.yaml · AGENT.md · subagents/ · any notes the prompt refers to

It is build-time content, identical for every client and never written at
runtime. Everything a run produces lives in ``agent_runtime`` instead (the
conversation's files, the branch scratch, checkpoints, tasks).
"""

from __future__ import annotations

from pathlib import Path

from core.settings import settings


def safe_segment(value: str) -> str:
    """Reject ids that could break out of their intended directory or key.

    An id or slug that becomes a path component is an input to a path
    operation; validating it is cheap defence in depth.
    """
    if not value or "/" in value or "\\" in value or ".." in value or value.startswith("."):
        raise ValueError(f"Illegal path segment: {value!r}")
    return value


def agents_root() -> Path:
    """The folder of declarative agent definitions."""
    return settings.registry.agents_dir


def agent_dir(agent_slug: str) -> Path:
    """One agent's definition folder (mounted read-only at ``/reference/``)."""
    return agents_root() / safe_segment(agent_slug)


__all__ = ["agent_dir", "agents_root", "safe_segment"]
