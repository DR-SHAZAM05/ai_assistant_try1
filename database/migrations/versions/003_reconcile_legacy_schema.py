"""Reconcile installations created when the initial migration was a no-op.

Revision ID: 003_reconcile_legacy_schema
Revises: 002_m4_practice_document_tracking
Create Date: 2026-08-29 18:20:00.000000

Early installations could be stamped at revision 001 without receiving the
relational tables. This revision is intentionally idempotent, so it repairs
those installations while remaining harmless after a fresh upgrade.
"""

from alembic import op


revision = "003_reconcile_legacy_schema"
down_revision = "002_m4_practice_docs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            CREATE TYPE priorityenum AS ENUM ('low', 'medium', 'high');
        EXCEPTION
            WHEN duplicate_object THEN NULL;
        END $$;
        """
    )
    op.execute(
        """
        DO $$
        BEGIN
            CREATE TYPE actionstatusenum AS ENUM ('open', 'in_progress', 'completed', 'cancelled');
        EXCEPTION
            WHEN duplicate_object THEN NULL;
        END $$;
        """
    )

    statements = [
        """CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY, telegram_chat_id VARCHAR(64) UNIQUE,
            full_name VARCHAR(128) NOT NULL, preferred_language VARCHAR(10) DEFAULT 'ro', created_at TIMESTAMP)""",
        """CREATE TABLE IF NOT EXISTS academic_years (
            id SERIAL PRIMARY KEY, year_code VARCHAR(32) NOT NULL UNIQUE,
            is_active BOOLEAN DEFAULT FALSE, created_at TIMESTAMP)""",
        """CREATE TABLE IF NOT EXISTS email_accounts (
            id SERIAL PRIMARY KEY, account_type VARCHAR(32) NOT NULL,
            email_address VARCHAR(128) NOT NULL UNIQUE, is_active BOOLEAN DEFAULT TRUE)""",
        """CREATE TABLE IF NOT EXISTS emails (
            id SERIAL PRIMARY KEY, message_id VARCHAR(256) NOT NULL UNIQUE,
            account_type VARCHAR(32) NOT NULL, sender VARCHAR(256) NOT NULL,
            subject VARCHAR(512), body_text TEXT, received_at TIMESTAMP NOT NULL,
            summary TEXT, category VARCHAR(64), is_practice_related BOOLEAN DEFAULT FALSE,
            requires_action BOOLEAN DEFAULT FALSE, detected_deadline TIMESTAMP, created_at TIMESTAMP)""",
        """CREATE TABLE IF NOT EXISTS practice_questions (
            id SERIAL PRIMARY KEY, academic_year VARCHAR(32) NOT NULL,
            student_name VARCHAR(128), student_group VARCHAR(32), topic VARCHAR(128) NOT NULL,
            question_summary TEXT NOT NULL, source_type VARCHAR(64) NOT NULL,
            source_reference VARCHAR(256), tags JSON, created_at TIMESTAMP)""",
        """CREATE TABLE IF NOT EXISTS practice_answers (
            id SERIAL PRIMARY KEY, question_id INTEGER NOT NULL REFERENCES practice_questions(id) ON DELETE CASCADE,
            answer_summary TEXT NOT NULL, decision VARCHAR(128), academic_year VARCHAR(32) NOT NULL, created_at TIMESTAMP)""",
        """CREATE TABLE IF NOT EXISTS action_items (
            id SERIAL PRIMARY KEY, title VARCHAR(256) NOT NULL, source VARCHAR(64) NOT NULL,
            deadline TIMESTAMP, priority priorityenum DEFAULT 'medium', status actionstatusenum DEFAULT 'open',
            source_reference VARCHAR(256), created_at TIMESTAMP)""",
        """CREATE TABLE IF NOT EXISTS conversations (
            id SERIAL PRIMARY KEY, telegram_chat_id VARCHAR(64) NOT NULL,
            session_id VARCHAR(64) NOT NULL UNIQUE, created_at TIMESTAMP)""",
        """CREATE TABLE IF NOT EXISTS conversation_messages (
            id SERIAL PRIMARY KEY, conversation_id INTEGER NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
            sender_role VARCHAR(32) NOT NULL, content TEXT NOT NULL, tool_calls JSON, created_at TIMESTAMP)""",
        """CREATE TABLE IF NOT EXISTS user_memories (
            id SERIAL PRIMARY KEY, key VARCHAR(128) NOT NULL UNIQUE, value TEXT NOT NULL,
            category VARCHAR(64), created_at TIMESTAMP)""",
        """CREATE TABLE IF NOT EXISTS news_articles (
            id SERIAL PRIMARY KEY, title VARCHAR(512) NOT NULL, url VARCHAR(1024) NOT NULL UNIQUE,
            topic VARCHAR(64) NOT NULL, relevance_score DOUBLE PRECISION DEFAULT 0,
            summary TEXT, published_at TIMESTAMP, created_at TIMESTAMP)""",
        """CREATE TABLE IF NOT EXISTS audit_logs (
            id SERIAL PRIMARY KEY, timestamp TIMESTAMP, user_request TEXT, selected_tool VARCHAR(128),
            model_used VARCHAR(64), status VARCHAR(32) NOT NULL, execution_duration_ms DOUBLE PRECISION,
            external_operation VARCHAR(256), rag_sources JSON)""",
        "CREATE INDEX IF NOT EXISTS ix_users_id ON users (id)",
        "CREATE INDEX IF NOT EXISTS ix_users_telegram_chat_id ON users (telegram_chat_id)",
        "CREATE INDEX IF NOT EXISTS ix_academic_years_id ON academic_years (id)",
        "CREATE INDEX IF NOT EXISTS ix_academic_years_year_code ON academic_years (year_code)",
        "CREATE INDEX IF NOT EXISTS ix_email_accounts_id ON email_accounts (id)",
        "CREATE INDEX IF NOT EXISTS ix_emails_id ON emails (id)",
        "CREATE INDEX IF NOT EXISTS ix_emails_message_id ON emails (message_id)",
        "CREATE INDEX IF NOT EXISTS ix_practice_questions_id ON practice_questions (id)",
        "CREATE INDEX IF NOT EXISTS ix_practice_questions_academic_year ON practice_questions (academic_year)",
        "CREATE INDEX IF NOT EXISTS ix_practice_answers_id ON practice_answers (id)",
        "CREATE INDEX IF NOT EXISTS ix_practice_answers_academic_year ON practice_answers (academic_year)",
        "CREATE INDEX IF NOT EXISTS ix_action_items_id ON action_items (id)",
        "CREATE INDEX IF NOT EXISTS ix_conversations_id ON conversations (id)",
        "CREATE INDEX IF NOT EXISTS ix_conversations_telegram_chat_id ON conversations (telegram_chat_id)",
        "CREATE INDEX IF NOT EXISTS ix_conversation_messages_id ON conversation_messages (id)",
        "CREATE INDEX IF NOT EXISTS ix_user_memories_id ON user_memories (id)",
        "CREATE INDEX IF NOT EXISTS ix_user_memories_key ON user_memories (key)",
        "CREATE INDEX IF NOT EXISTS ix_news_articles_id ON news_articles (id)",
        "CREATE INDEX IF NOT EXISTS ix_audit_logs_id ON audit_logs (id)",
    ]
    for statement in statements:
        op.execute(statement)


def downgrade() -> None:
    # This migration may have repaired an existing production installation;
    # dropping tables during downgrade would destroy data and is not safe.
    pass
