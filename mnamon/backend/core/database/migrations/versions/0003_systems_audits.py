"""Audited systems, versioned workspace files, memory, audits and approvals.

Revision ID: 0003_systems_audits
Revises: 0002_async_tasks
Create Date: 2026-11-14

* ``systems``: one audited AI system (text id ``SYS-001``), ``data`` JSONB.
  Not scoped by client id (deliberate, for now).
* ``workspace_file_blobs`` (content by sha256), ``workspace_files`` (one row
  per version of ``(namespace, path)``, at most one current) and
  ``workspace_events`` (append-only audit ledger). Namespaces:
  ``system:<id>``, ``memory:system:<id>``, ``memory:org``, ``memory:proposals``.
* ``audits``, ``audit_artifacts`` (versioned per audit/kind/name, status
  proposed|approved|rejected|changes_requested|superseded) and ``approvals``
  (every human gate decision with its reason).
* ``conversations.system_id`` / ``conversations.audit_id``: nullable, the
  subject of a chat.

Few typed columns (what is filtered or joined on); everything else in JSONB.
Additive only.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003_systems_audits"
down_revision: str | None = "0002_async_tasks"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSONB = postgresql.JSONB()


def _timestamps(*names: str) -> list[sa.Column]:
    return [
        sa.Column(name, sa.DateTime(), server_default=sa.text("now()"), nullable=False)
        for name in names
    ]


def upgrade() -> None:
    op.create_table(
        "systems",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("status", sa.String(), server_default="active", nullable=False),
        sa.Column("data", JSONB, nullable=False),
        *_timestamps("created_at", "updated_at"),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "workspace_file_blobs",
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("data", sa.LargeBinary(), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        *_timestamps("created_at"),
        sa.PrimaryKeyConstraint("sha256"),
    )

    op.create_table(
        "workspace_files",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("namespace", sa.String(), nullable=False),
        sa.Column("path", sa.String(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("blob_sha256", sa.String(length=64), nullable=False),
        sa.Column(
            "content_type", sa.String(), server_default="application/octet-stream", nullable=False
        ),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("created_by", sa.String(), nullable=False),
        sa.Column("is_current", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("data", JSONB, nullable=False),
        *_timestamps("created_at"),
        sa.ForeignKeyConstraint(
            ["blob_sha256"],
            ["workspace_file_blobs.sha256"],
            name="workspace_files_blob_sha256_fkey",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_workspace_files_namespace", "workspace_files", ["namespace"])
    op.create_index("ix_workspace_files_blob_sha256", "workspace_files", ["blob_sha256"])
    op.create_index(
        "uq_workspace_files_namespace_path_version",
        "workspace_files",
        ["namespace", "path", "version"],
        unique=True,
    )
    op.create_index(
        "uq_workspace_files_current",
        "workspace_files",
        ["namespace", "path"],
        unique=True,
        postgresql_where=sa.text("is_current"),
    )

    op.create_table(
        "workspace_events",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("namespace", sa.String(), nullable=False),
        sa.Column("path", sa.String(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=True),
        sa.Column("action", sa.String(), nullable=False),
        sa.Column("actor", sa.String(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("audit_id", sa.String(), nullable=True),
        sa.Column("run_id", sa.String(), nullable=True),
        sa.Column("trace_id", sa.String(), nullable=True),
        sa.Column("data", JSONB, nullable=False),
        *_timestamps("at"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_workspace_events_namespace_path", "workspace_events", ["namespace", "path"])
    op.create_index("ix_workspace_events_audit_id", "workspace_events", ["audit_id"])

    op.create_table(
        "audits",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("system_id", sa.String(), nullable=False),
        sa.Column("status", sa.String(), server_default="open", nullable=False),
        sa.Column("stage", sa.String(), server_default="context", nullable=False),
        sa.Column("created_by", sa.String(), nullable=True),
        sa.Column("data", JSONB, nullable=False),
        *_timestamps("created_at", "updated_at"),
        sa.ForeignKeyConstraint(
            ["system_id"], ["systems.id"], name="audits_system_id_fkey", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_audits_system_id", "audits", ["system_id"])

    op.create_table(
        "audit_artifacts",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("audit_id", sa.String(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("name", sa.String(), server_default="main", nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(), server_default="proposed", nullable=False),
        sa.Column("data", JSONB, nullable=False),
        sa.Column("file_refs", JSONB, nullable=False),
        sa.Column("parent_id", sa.String(), nullable=True),
        sa.Column("created_by", sa.String(), nullable=False),
        *_timestamps("created_at", "updated_at"),
        sa.ForeignKeyConstraint(
            ["audit_id"], ["audits.id"], name="audit_artifacts_audit_id_fkey", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["parent_id"],
            ["audit_artifacts.id"],
            name="audit_artifacts_parent_id_fkey",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_audit_artifacts_audit_id", "audit_artifacts", ["audit_id"])
    op.create_index(
        "uq_audit_artifacts_slot_version",
        "audit_artifacts",
        ["audit_id", "kind", "name", "version"],
        unique=True,
    )

    op.create_table(
        "approvals",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("audit_id", sa.String(), nullable=False),
        sa.Column("artifact_id", sa.String(), nullable=True),
        sa.Column("gate", sa.String(), nullable=False),
        sa.Column("decision", sa.String(), nullable=False),
        sa.Column("reason_category", sa.String(), nullable=True),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("edits", JSONB, nullable=False),
        sa.Column("decided_by", sa.String(), nullable=False),
        *_timestamps("at"),
        sa.ForeignKeyConstraint(
            ["audit_id"], ["audits.id"], name="approvals_audit_id_fkey", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["artifact_id"],
            ["audit_artifacts.id"],
            name="approvals_artifact_id_fkey",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_approvals_audit_id", "approvals", ["audit_id"])
    op.create_index("ix_approvals_artifact_id", "approvals", ["artifact_id"])

    op.add_column("conversations", sa.Column("system_id", sa.String(), nullable=True))
    op.add_column("conversations", sa.Column("audit_id", sa.String(), nullable=True))
    op.create_foreign_key(
        "conversations_system_id_fkey",
        "conversations",
        "systems",
        ["system_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "conversations_audit_id_fkey",
        "conversations",
        "audits",
        ["audit_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_conversations_system_id", "conversations", ["system_id"])
    op.create_index("ix_conversations_audit_id", "conversations", ["audit_id"])


def downgrade() -> None:
    op.drop_index("ix_conversations_audit_id", table_name="conversations")
    op.drop_index("ix_conversations_system_id", table_name="conversations")
    op.drop_constraint("conversations_audit_id_fkey", "conversations", type_="foreignkey")
    op.drop_constraint("conversations_system_id_fkey", "conversations", type_="foreignkey")
    op.drop_column("conversations", "audit_id")
    op.drop_column("conversations", "system_id")
    op.drop_table("approvals")
    op.drop_table("audit_artifacts")
    op.drop_table("audits")
    op.drop_table("workspace_events")
    op.drop_table("workspace_files")
    op.drop_table("workspace_file_blobs")
    op.drop_table("systems")
