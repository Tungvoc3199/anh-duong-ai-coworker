"""Add persistent async task runner state.

Revision ID: 0003
Revises: 0002
Create Date: 2026-07-27
"""

import sqlalchemy as sa
from sqlalchemy import inspect

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

_TABLE = "async_task_runs"


def upgrade() -> None:
    bind = op.get_bind()
    if _TABLE in inspect(bind).get_table_names():
        return

    op.create_table(
        _TABLE,
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("task_id", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("mode", sa.String(length=16), nullable=False),
        sa.Column("goal", sa.Text(), nullable=False),
        sa.Column("workspace", sa.String(length=1024)),
        sa.Column("request_json", sa.Text(), nullable=False),
        sa.Column("checkpoint_json", sa.Text()),
        sa.Column("result_json", sa.Text()),
        sa.Column(
            "attempt",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "max_attempts",
            sa.Integer(),
            nullable=False,
            server_default="3",
        ),
        sa.Column("run_after", sa.DateTime(timezone=True), nullable=False),
        sa.Column("lease_owner", sa.String(length=128)),
        sa.Column(
            "lease_expires_at",
            sa.DateTime(timezone=True),
        ),
        sa.Column(
            "idempotency_key",
            sa.String(length=255),
            nullable=False,
        ),
        sa.Column("external_run_id", sa.String(length=255)),
        sa.Column("last_error_code", sa.String(length=128)),
        sa.Column("last_error_message", sa.Text()),
        sa.Column("source_chat_id", sa.String(length=128)),
        sa.Column(
            "notification_status",
            sa.String(length=32),
            nullable=False,
            server_default="not_required",
        ),
        sa.Column(
            "notification_attempts",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "version",
            sa.Integer(),
            nullable=False,
            server_default="1",
        ),
        sa.ForeignKeyConstraint(
            ["task_id"],
            ["tasks.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "task_id",
            name="uq_async_task_runs_task_id",
        ),
        sa.UniqueConstraint(
            "idempotency_key",
            name="uq_async_task_runs_idempotency_key",
        ),
    )
    op.create_index(
        "ix_async_task_runs_status",
        _TABLE,
        ["status"],
        unique=False,
    )
    op.create_index(
        "ix_async_task_runs_run_after",
        _TABLE,
        ["run_after"],
        unique=False,
    )
    op.create_index(
        "ix_async_task_runs_lease_expires_at",
        _TABLE,
        ["lease_expires_at"],
        unique=False,
    )
    op.create_index(
        "ix_async_task_runs_notification_status",
        _TABLE,
        ["notification_status"],
        unique=False,
    )


def downgrade() -> None:
    bind = op.get_bind()
    if _TABLE not in inspect(bind).get_table_names():
        return

    op.drop_index(
        "ix_async_task_runs_notification_status",
        table_name=_TABLE,
    )
    op.drop_index(
        "ix_async_task_runs_lease_expires_at",
        table_name=_TABLE,
    )
    op.drop_index(
        "ix_async_task_runs_run_after",
        table_name=_TABLE,
    )
    op.drop_index(
        "ix_async_task_runs_status",
        table_name=_TABLE,
    )
    op.drop_table(_TABLE)
