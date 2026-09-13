"""Complete per-Telegram-user persistence for Phase 2.

Revision ID: 006_user_scoped_persistence
Revises: 005_user_isolation
Create Date: 2026-09-13 09:15:00.000000
"""

from alembic import op


revision = "006_user_scoped_persistence"
down_revision = "005_user_isolation"
branch_labels = None
depends_on = None

LEGACY_OWNER = "__legacy_unassigned__"


def _add_owner_column(table: str) -> None:
    op.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS user_id VARCHAR(64)")
    op.execute(
        f"UPDATE {table} SET user_id = '{LEGACY_OWNER}' "
        "WHERE user_id IS NULL OR user_id = 'default'"
    )
    op.execute(f"ALTER TABLE {table} ALTER COLUMN user_id SET NOT NULL")
    op.execute(f"ALTER TABLE {table} ALTER COLUMN user_id DROP DEFAULT")
    op.execute(f"CREATE INDEX IF NOT EXISTS ix_{table}_user_id ON {table} (user_id)")


def _replace_unique_constraint(table: str, old_name: str, new_name: str, columns: str) -> None:
    op.execute(
        f"""
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_constraint WHERE conname = '{old_name}') THEN
                ALTER TABLE {table} DROP CONSTRAINT {old_name};
            END IF;
            IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = '{new_name}') THEN
                ALTER TABLE {table} ADD CONSTRAINT {new_name} UNIQUE ({columns});
            END IF;
        END $$;
        """
    )


def upgrade() -> None:
    # Widen alembic_version column to support future longer revision ids safely
    op.execute("ALTER TABLE alembic_version ALTER COLUMN version_num TYPE VARCHAR(64)")

    # Reconcile the source-less 005 that was already present on one local DB.
    _add_owner_column("user_memories")
    _add_owner_column("action_items")
    _replace_unique_constraint(
        "user_memories",
        "user_memories_key_key",
        "uq_user_memory_user_key",
        "user_id, key",
    )

    _add_owner_column("emails")
    op.execute("ALTER TABLE emails ADD COLUMN IF NOT EXISTS recipients JSON")
    op.execute("ALTER TABLE emails ADD COLUMN IF NOT EXISTS importance VARCHAR(32)")
    op.execute("ALTER TABLE emails ADD COLUMN IF NOT EXISTS actions JSON")
    _replace_unique_constraint(
        "emails",
        "emails_message_id_key",
        "uq_emails_user_account_message",
        "user_id, account_type, message_id",
    )

    _add_owner_column("practice_questions")
    op.execute("ALTER TABLE practice_answers ADD COLUMN IF NOT EXISTS user_id VARCHAR(64)")
    op.execute(
        """
        UPDATE practice_answers AS answer
        SET user_id = question.user_id
        FROM practice_questions AS question
        WHERE answer.question_id = question.id AND answer.user_id IS NULL
        """
    )
    op.execute(
        f"UPDATE practice_answers SET user_id = '{LEGACY_OWNER}' "
        "WHERE user_id IS NULL OR user_id = 'default'"
    )
    op.execute("ALTER TABLE practice_answers ALTER COLUMN user_id SET NOT NULL")
    op.execute("ALTER TABLE practice_answers ALTER COLUMN user_id DROP DEFAULT")
    op.execute("CREATE INDEX IF NOT EXISTS ix_practice_answers_user_id ON practice_answers (user_id)")

    _add_owner_column("conversations")
    _replace_unique_constraint(
        "conversations",
        "conversations_session_id_key",
        "uq_conversations_user_session",
        "user_id, session_id",
    )

    _add_owner_column("news_articles")
    op.execute("ALTER TABLE news_articles ADD COLUMN IF NOT EXISTS source_name VARCHAR(256)")
    op.execute("ALTER TABLE news_articles ADD COLUMN IF NOT EXISTS fingerprint VARCHAR(64)")
    op.execute("ALTER TABLE news_articles ADD COLUMN IF NOT EXISTS content TEXT")
    op.execute("UPDATE news_articles SET source_name = 'RSS' WHERE source_name IS NULL")
    op.execute("ALTER TABLE news_articles ALTER COLUMN source_name SET NOT NULL")
    _replace_unique_constraint(
        "news_articles",
        "news_articles_url_key",
        "uq_news_article_user_url",
        "user_id, url",
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_news_articles_fingerprint ON news_articles (fingerprint)")

    _add_owner_column("audit_logs")


def downgrade() -> None:
    # The migration is intentionally data-preserving.  Removing owner columns
    # would destroy the access boundaries introduced by Phase 2.
    pass
