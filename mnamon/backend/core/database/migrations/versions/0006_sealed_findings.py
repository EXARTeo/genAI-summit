"""Sealed findings: append-only ``findings``, ``finding_annotations``,
``finding_status_events``, and ``audits.pins``.

Revision ID: 0006_sealed_findings
Revises: 0005_regulation_telegram
Create Date: 2026-11-15

A trigger rejects UPDATE and DELETE on the three finding tables (plan 01 §7.2):
a verdict is never edited; humans annotate it and a regulation change adds a
``stale`` status event. ``audits.pins`` holds what a run pinned (kb, dossier,
config and model versions, seeds). Additive only.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006_sealed_findings"
down_revision: str | None = "0005_regulation_telegram"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSONB = postgresql.JSONB(none_as_null=True)
TABLES = ("findings", "finding_annotations", "finding_status_events")


def _created_at() -> sa.Column:
    return sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False)


def upgrade() -> None:
    op.add_column("audits", sa.Column("pins", JSONB, nullable=True))
    op.create_table(
        "findings",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("audit_id", sa.String(), nullable=False),
        sa.Column("system_id", sa.String(), nullable=False),
        sa.Column("obligation_id", sa.String(), nullable=False),
        sa.Column("verdict", sa.String(), nullable=False),
        sa.Column("severity", sa.String(), nullable=True),
        sa.Column("gap_id", sa.String(), nullable=True),
        sa.Column("metrics_ref", JSONB, nullable=True),
        sa.Column("evidence_refs", JSONB, nullable=False),
        sa.Column("citations", JSONB, nullable=False),
        sa.Column("kb_version", sa.String(), nullable=True),
        sa.Column("reasoning", sa.Text(), nullable=True),
        sa.Column("counter_arguments", JSONB, nullable=True),
        sa.Column("would_change_if", JSONB, nullable=True),
        sa.Column("judges", JSONB, nullable=False),
        sa.Column("critic", JSONB, nullable=False),
        sa.Column("data", JSONB, nullable=False),
        sa.Column("prev_hash", sa.String(), nullable=True),
        sa.Column("hash", sa.String(), nullable=False),
        sa.Column("created_by", sa.String(), nullable=False),
        _created_at(),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_findings_audit_id", "findings", ["audit_id"])
    op.create_index("ix_findings_system_id", "findings", ["system_id"])
    op.create_index("ix_findings_system_obligation", "findings", ["system_id", "obligation_id"])
    op.create_index("uq_findings_hash", "findings", ["hash"], unique=True)
    op.create_table(
        "finding_annotations",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("finding_id", sa.String(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("actor", sa.String(), nullable=False),
        _created_at(),
        sa.ForeignKeyConstraint(["finding_id"], ["findings.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_finding_annotations_finding_id", "finding_annotations", ["finding_id"])
    op.create_table(
        "finding_status_events",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("finding_id", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("superseded_by", sa.String(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("data", JSONB, nullable=False),
        sa.Column("actor", sa.String(), nullable=False),
        _created_at(),
        sa.ForeignKeyConstraint(["finding_id"], ["findings.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_finding_status_events_finding_id", "finding_status_events", ["finding_id"])
    op.execute(
        "CREATE OR REPLACE FUNCTION reject_append_only_change() RETURNS trigger "
        "LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION "
        "'% is append-only: % is not allowed', TG_TABLE_NAME, TG_OP; END; $$"
    )
    for table in TABLES:
        for verb in ("UPDATE", "DELETE"):
            op.execute(
                f"CREATE TRIGGER trg_{table}_no_{verb.lower()} BEFORE {verb} ON {table} "
                "FOR EACH ROW EXECUTE FUNCTION reject_append_only_change()"
            )


def downgrade() -> None:
    for table in TABLES:
        for verb in ("update", "delete"):
            op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_no_{verb} ON {table}")
    op.execute("DROP FUNCTION IF EXISTS reject_append_only_change()")
    op.drop_index("ix_finding_status_events_finding_id", table_name="finding_status_events")
    op.drop_table("finding_status_events")
    op.drop_index("ix_finding_annotations_finding_id", table_name="finding_annotations")
    op.drop_table("finding_annotations")
    op.drop_index("uq_findings_hash", table_name="findings")
    op.drop_index("ix_findings_system_obligation", table_name="findings")
    op.drop_index("ix_findings_system_id", table_name="findings")
    op.drop_index("ix_findings_audit_id", table_name="findings")
    op.drop_table("findings")
    op.drop_column("audits", "pins")
