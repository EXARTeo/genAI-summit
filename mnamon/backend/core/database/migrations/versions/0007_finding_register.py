"""Findings register: one row per (system, obligation) with its state across audits.

Revision ID: 0007_finding_register
Revises: 0006_sealed_findings
Create Date: 2026-11-15

The register is the system's current compliance state: an open gap stays open
until a human closes it with a reason or a later audit finds it fixed. Mutable
state plus an append-only ``history`` list in the row; the sealed findings are
not touched. Additive only.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0007_finding_register"
down_revision: str | None = "0006_sealed_findings"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSONB = postgresql.JSONB()


def upgrade() -> None:
    op.create_table(
        "finding_register",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("system_id", sa.String(), nullable=False),
        sa.Column("obligation_id", sa.String(), nullable=False),
        sa.Column("state", sa.String(), nullable=False),
        sa.Column("verdict", sa.String(), nullable=False),
        sa.Column("severity", sa.String(), nullable=True),
        sa.Column("article", sa.String(), nullable=True),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("gap_id", sa.String(), nullable=True),
        sa.Column("first_seen_audit_id", sa.String(), nullable=False),
        sa.Column("last_seen_audit_id", sa.String(), nullable=False),
        sa.Column("last_finding_id", sa.String(), nullable=True),
        sa.Column("opened_at", sa.DateTime(), nullable=True),
        sa.Column("closed_by", sa.String(), nullable=True),
        sa.Column("close_reason", sa.Text(), nullable=True),
        sa.Column("closed_at", sa.DateTime(), nullable=True),
        sa.Column("history", JSONB, nullable=False),
        sa.Column("data", JSONB, nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["system_id"], ["systems.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_finding_register_system_id", "finding_register", ["system_id"])
    op.create_index(
        "uq_finding_register_system_obligation",
        "finding_register",
        ["system_id", "obligation_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("uq_finding_register_system_obligation", table_name="finding_register")
    op.drop_index("ix_finding_register_system_id", table_name="finding_register")
    op.drop_table("finding_register")
