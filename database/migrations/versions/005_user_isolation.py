"""Introduce owner scope for the first persisted user data.

Revision ID: 005_user_isolation
Revises: 004_persist_pending_email_drafts
Create Date: 2026-09-13 09:00:00.000000

This revision was applied to an early local installation but its source file
was not retained.  Keeping it in version control restores an unbroken Alembic
history and makes fresh installations reproduce the same base schema.
"""

from alembic import op


revision = "005_user_isolation"
down_revision = "004_persist_pending_email_drafts"
branch_labels = None
depends_on = None

LEGACY_OWNER = "__legacy_unassigned__"


def upgrade() -> None:
    for table in ("user_memories", "action_items"):
        op.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS user_id VARCHAR(64)")
        op.execute(
            f"UPDATE {table} SET user_id = '{LEGACY_OWNER}' "
            "WHERE user_id IS NULL OR user_id = 'default'"
        )
        op.execute(f"ALTER TABLE {table} ALTER COLUMN user_id SET NOT NULL")
        op.execute(f"ALTER TABLE {table} ALTER COLUMN user_id DROP DEFAULT")
        op.execute(f"CREATE INDEX IF NOT EXISTS ix_{table}_user_id ON {table} (user_id)")

    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'user_memories_key_key'
            ) THEN
                ALTER TABLE user_memories DROP CONSTRAINT user_memories_key_key;
            END IF;
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'uq_user_memory_user_key'
            ) THEN
                ALTER TABLE user_memories
                ADD CONSTRAINT uq_user_memory_user_key UNIQUE (user_id, key);
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    # Do not drop ownership columns on a production rollback: that would erase
    # the only association between private data and its Telegram user.
    pass
