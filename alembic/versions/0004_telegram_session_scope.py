"""Persist Telegram session scope for approval binding.

Revision ID: 0004
Revises: 0003
Create Date: 2026-09-02
"""

import sqlalchemy as sa
from sqlalchemy import inspect

from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None

_TABLE = "async_task_runs"
_COLUMN = "source_session_id"
_INDEX = "ix_async_task_runs_source_telegram"


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if _TABLE not in inspector.get_table_names():
        return
    columns = {item["name"] for item in inspector.get_columns(_TABLE)}
    if _COLUMN not in columns:
        op.add_column(
            _TABLE,
            sa.Column(_COLUMN, sa.String(length=128), nullable=True),
        )
    indexes = {item["name"] for item in inspector.get_indexes(_TABLE)}
    if _INDEX not in indexes:
        op.create_index(
            _INDEX,
            _TABLE,
            ["source_chat_id", "source_session_id", "status"],
            unique=False,
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if _TABLE not in inspector.get_table_names():
        return
    indexes = {item["name"] for item in inspector.get_indexes(_TABLE)}
    if _INDEX in indexes:
        op.drop_index(_INDEX, table_name=_TABLE)
    columns = {item["name"] for item in inspector.get_columns(_TABLE)}
    if _COLUMN in columns:
        op.drop_column(_TABLE, _COLUMN)
