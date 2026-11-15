"""System classifications: the risk classifier's proposals and their append-only events.

Revision ID: 0008_system_classifications
Revises: 0007_finding_register
Create Date: 2026-11-15

``system_classifications`` holds one row per classifier run (status, pinned
``kb_version`` and ``dossier_version``, the result written once);
``classification_events`` is append-only (the ``reject_append_only_change()``
trigger from 0006): every status move, decision and ``stale`` mark is a new
row (plan 02 §7.2). Additive only.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0008_system_classifications"
down_revision: str | None = "0007_finding_register"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSONB = postgresql.JSONB()
NULLABLE_JSONB = postgresql.JSONB(none_as_null=True)


def upgrade() -> None:
    op.create_table(
        "system_classifications",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("system_id", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("kb_version", sa.String(), nullable=True),
        sa.Column("dossier_version", JSONB, nullable=False),
        sa.Column("input", JSONB, nullable=False),
        sa.Column("result", NULLABLE_JSONB, nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("trace_id", sa.String(), nullable=True),
        sa.Column("previous_id", sa.String(), nullable=True),
        sa.Column("created_by", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["system_id"], ["systems.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_system_classifications_system_id", "system_classifications", ["system_id"])
    op.create_table(
        "classification_events",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("classification_id", sa.String(), nullable=False),
        sa.Column("system_id", sa.String(), nullable=False),
        sa.Column("action", sa.String(), nullable=False),
        sa.Column("actor", sa.String(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("data", JSONB, nullable=False),
        sa.Column("at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["classification_id"], ["system_classifications.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_classification_events_classification_id",
        "classification_events",
        ["classification_id"],
    )
    op.create_index("ix_classification_events_system_id", "classification_events", ["system_id"])
    # The function exists since 0006; replacing it keeps this migration self-contained.
    op.execute(
        "CREATE OR REPLACE FUNCTION reject_append_only_change() RETURNS trigger "
        "LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION "
        "'% is append-only: % is not allowed', TG_TABLE_NAME, TG_OP; END; $$"
    )
    for verb in ("UPDATE", "DELETE"):
        op.execute(
            f"CREATE TRIGGER trg_classification_events_no_{verb.lower()} BEFORE {verb} "
            "ON classification_events FOR EACH ROW EXECUTE FUNCTION reject_append_only_change()"
        )


def downgrade() -> None:
    for verb in ("update", "delete"):
        op.execute(
            f"DROP TRIGGER IF EXISTS trg_classification_events_no_{verb} ON classification_events"
        )
    op.drop_index("ix_classification_events_system_id", table_name="classification_events")
    op.drop_index("ix_classification_events_classification_id", table_name="classification_events")
    op.drop_table("classification_events")
    op.drop_index("ix_system_classifications_system_id", table_name="system_classifications")
    op.drop_table("system_classifications")
