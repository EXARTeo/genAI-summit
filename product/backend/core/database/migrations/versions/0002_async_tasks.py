"""Async sub-agents: conversation_tasks and messages.kind / messages.task_notice.

Revision ID: 0002_async_tasks
Revises: 0001_baseline
Create Date: 2026-11-13

Sub-agents run as background tasks in the agents service. The backend keeps
what the UI needs about them:

* ``conversation_tasks``: the mirror of each task, fed from the
  ``tasks:status`` Redis stream. ``client_id`` is the owning browser; the row
  cascades with its conversation.
* ``messages.kind`` (enum ``message_kind_enum``: ``task_notification``) and
  ``messages.task_notice``: the wake-up input row, sender ``user`` because
  the orchestrator receives it as a HumanMessage, rendered by the UI as a
  compact notice. NULL on every existing message.

Hand-written: the Postgres enum type must exist before the column that uses
it, which autogenerate does not do for ``add_column``. Additive only.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002_async_tasks"
down_revision: str | None = "0001_baseline"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

KIND_ENUM = "message_kind_enum"
JSONB = postgresql.JSONB(none_as_null=True)


def upgrade() -> None:
    bind = op.get_bind()
    postgresql.ENUM("task_notification", name=KIND_ENUM).create(bind, checkfirst=True)
    kind_type = postgresql.ENUM("task_notification", name=KIND_ENUM, create_type=False)
    op.add_column("messages", sa.Column("kind", kind_type, nullable=True))
    op.add_column("messages", sa.Column("task_notice", JSONB, nullable=True))

    op.create_table(
        "conversation_tasks",
        sa.Column("task_id", sa.String(), nullable=False),
        sa.Column("conversation_id", sa.String(), nullable=False),
        sa.Column("client_id", sa.String(), nullable=False),
        sa.Column("parent_task_id", sa.String(), nullable=True),
        sa.Column("root_run_id", sa.String(), nullable=True),
        sa.Column("branch_thread_id", sa.String(), nullable=True),
        sa.Column("spawned_by_message_id", sa.String(), nullable=True),
        sa.Column("depth", sa.Integer(), server_default="1", nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("subagent_path", sa.String(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("model", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("result_preview", sa.Text(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("usage", JSONB, nullable=True),
        sa.Column("raw_events", JSONB, nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("settled_at", sa.DateTime(), nullable=True),
        sa.Column("notified_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["conversations.id"],
            name="conversation_tasks_conversation_id_fkey",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("task_id"),
    )
    op.create_index("ix_conversation_tasks_client_id", "conversation_tasks", ["client_id"])
    op.create_index(
        "ix_conversation_tasks_conversation_id", "conversation_tasks", ["conversation_id"]
    )
    op.create_index(
        "ix_conversation_tasks_parent_task_id", "conversation_tasks", ["parent_task_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_conversation_tasks_parent_task_id", table_name="conversation_tasks")
    op.drop_index("ix_conversation_tasks_conversation_id", table_name="conversation_tasks")
    op.drop_index("ix_conversation_tasks_client_id", table_name="conversation_tasks")
    op.drop_table("conversation_tasks")
    op.drop_column("messages", "task_notice")
    op.drop_column("messages", "kind")
    op.execute(f"DROP TYPE IF EXISTS {KIND_ENUM}")
