"""Add FTS5 external-content index for memories.

Revision ID: 0002
Revises: 0001
Create Date: 2026-07-24
"""

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE VIRTUAL TABLE memories_fts USING fts5(
            title,
            content,
            tags,
            content='memories',
            content_rowid='rowid',
            tokenize='unicode61 remove_diacritics 2'
        )
        """
    )

    op.execute(
        """
        CREATE TRIGGER memories_fts_ai
        AFTER INSERT ON memories
        BEGIN
            INSERT INTO memories_fts(
                rowid,
                title,
                content,
                tags
            )
            VALUES (
                new.rowid,
                new.title,
                new.content,
                COALESCE(new.tags, '[]')
            );
        END
        """
    )

    op.execute(
        """
        CREATE TRIGGER memories_fts_ad
        AFTER DELETE ON memories
        BEGIN
            INSERT INTO memories_fts(
                memories_fts,
                rowid,
                title,
                content,
                tags
            )
            VALUES (
                'delete',
                old.rowid,
                old.title,
                old.content,
                COALESCE(old.tags, '[]')
            );
        END
        """
    )

    op.execute(
        """
        CREATE TRIGGER memories_fts_au
        AFTER UPDATE ON memories
        BEGIN
            INSERT INTO memories_fts(
                memories_fts,
                rowid,
                title,
                content,
                tags
            )
            VALUES (
                'delete',
                old.rowid,
                old.title,
                old.content,
                COALESCE(old.tags, '[]')
            );

            INSERT INTO memories_fts(
                rowid,
                title,
                content,
                tags
            )
            VALUES (
                new.rowid,
                new.title,
                new.content,
                COALESCE(new.tags, '[]')
            );
        END
        """
    )

    # Index any rows created before this migration.
    op.execute(
        "INSERT INTO memories_fts(memories_fts) VALUES ('rebuild')"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS memories_fts_au")
    op.execute("DROP TRIGGER IF EXISTS memories_fts_ad")
    op.execute("DROP TRIGGER IF EXISTS memories_fts_ai")
    op.execute("DROP TABLE IF EXISTS memories_fts")
