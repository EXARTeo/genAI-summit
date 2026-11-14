"""Drop the old memory namespaces' rows (data only, no schema change).

Revision ID: 0004_drop_memory_namespaces
Revises: 0003_systems_audits
Create Date: 2026-11-14

Agent memory moved to the agents service (per system, in ``agent_runtime``).
The ``memory:system:<id>``, ``memory:org`` and ``memory:proposals`` namespaces
of ``workspace_files`` / ``workspace_events`` are no longer read or written, so
their rows are deleted. Blobs stay (they may be shared with system files).
Downgrade is a no-op: the deleted rows are not restored.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0004_drop_memory_namespaces"
down_revision: str | None = "0003_systems_audits"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("DELETE FROM workspace_events WHERE namespace LIKE 'memory:%'")
    op.execute("DELETE FROM workspace_files WHERE namespace LIKE 'memory:%'")


def downgrade() -> None:
    pass
