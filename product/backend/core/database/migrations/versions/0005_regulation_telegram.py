"""Regulation changes (from reg-memory) and Telegram HITL prompts.

Revision ID: 0005_regulation_telegram
Revises: 0004_drop_memory_namespaces
Create Date: 2026-11-14

``regulation_changes``: the RegChanges reg-memory announces and the human
decisions on them. ``telegram_prompts``: one row per gate sent to Telegram
(callback token, dedupe key, decision, the sent messages).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005_regulation_telegram"
down_revision: str | None = "0004_drop_memory_namespaces"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSONB = postgresql.JSONB()


def upgrade() -> None:
    op.create_table(
        "regulation_changes",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("status", sa.String(), server_default="proposed", nullable=False),
        sa.Column("data", JSONB, nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "telegram_prompts",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("key", sa.String(), nullable=False),
        sa.Column("status", sa.String(), server_default="open", nullable=False),
        sa.Column("decision", sa.String(), nullable=True),
        sa.Column("decided_by", sa.String(), nullable=True),
        sa.Column("data", JSONB, nullable=False),
        sa.Column("messages", JSONB, nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("decided_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_telegram_prompts_key", "telegram_prompts", ["key"])


def downgrade() -> None:
    op.drop_index("ix_telegram_prompts_key", table_name="telegram_prompts")
    op.drop_table("telegram_prompts")
    op.drop_table("regulation_changes")
