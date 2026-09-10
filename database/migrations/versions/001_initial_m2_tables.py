"""Create the relational schema used by the academic assistant.

Revision ID: 001_initial_m2_tables
Revises:
Create Date: 2026-08-21 14:55:00.000000

The original revision was a no-op and relied on ``Base.metadata.create_all``.
Keeping the revision id makes existing installations upgradeable while making a
new database reproducible through Alembic alone.
"""

from alembic import op
import sqlalchemy as sa


revision = "001_initial_m2_tables"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    priority_enum = sa.Enum("low", "medium", "high", name="priorityenum")
    action_status_enum = sa.Enum(
        "open", "in_progress", "completed", "cancelled", name="actionstatusenum"
    )

    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("telegram_chat_id", sa.String(length=64), nullable=True, unique=True),
        sa.Column("full_name", sa.String(length=128), nullable=False),
        sa.Column("preferred_language", sa.String(length=10), nullable=True, server_default="ro"),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_users_id", "users", ["id"])
    op.create_index("ix_users_telegram_chat_id", "users", ["telegram_chat_id"])

    op.create_table(
        "academic_years",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("year_code", sa.String(length=32), nullable=False, unique=True),
        sa.Column("is_active", sa.Boolean(), nullable=True, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_academic_years_id", "academic_years", ["id"])
    op.create_index("ix_academic_years_year_code", "academic_years", ["year_code"])

    op.create_table(
        "email_accounts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("account_type", sa.String(length=32), nullable=False),
        sa.Column("email_address", sa.String(length=128), nullable=False, unique=True),
        sa.Column("is_active", sa.Boolean(), nullable=True, server_default=sa.true()),
    )
    op.create_index("ix_email_accounts_id", "email_accounts", ["id"])

    op.create_table(
        "emails",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("message_id", sa.String(length=256), nullable=False, unique=True),
        sa.Column("account_type", sa.String(length=32), nullable=False),
        sa.Column("sender", sa.String(length=256), nullable=False),
        sa.Column("subject", sa.String(length=512), nullable=True),
        sa.Column("body_text", sa.Text(), nullable=True),
        sa.Column("received_at", sa.DateTime(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("category", sa.String(length=64), nullable=True),
        sa.Column("is_practice_related", sa.Boolean(), nullable=True, server_default=sa.false()),
        sa.Column("requires_action", sa.Boolean(), nullable=True, server_default=sa.false()),
        sa.Column("detected_deadline", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_emails_id", "emails", ["id"])
    op.create_index("ix_emails_message_id", "emails", ["message_id"])

    op.create_table(
        "practice_questions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("academic_year", sa.String(length=32), nullable=False),
        sa.Column("student_name", sa.String(length=128), nullable=True),
        sa.Column("student_group", sa.String(length=32), nullable=True),
        sa.Column("topic", sa.String(length=128), nullable=False),
        sa.Column("question_summary", sa.Text(), nullable=False),
        sa.Column("source_type", sa.String(length=64), nullable=False),
        sa.Column("source_reference", sa.String(length=256), nullable=True),
        sa.Column("tags", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_practice_questions_id", "practice_questions", ["id"])
    op.create_index("ix_practice_questions_academic_year", "practice_questions", ["academic_year"])

    op.create_table(
        "practice_answers",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("question_id", sa.Integer(), sa.ForeignKey("practice_questions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("answer_summary", sa.Text(), nullable=False),
        sa.Column("decision", sa.String(length=128), nullable=True),
        sa.Column("academic_year", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_practice_answers_id", "practice_answers", ["id"])
    op.create_index("ix_practice_answers_academic_year", "practice_answers", ["academic_year"])

    op.create_table(
        "action_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("title", sa.String(length=256), nullable=False),
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.Column("deadline", sa.DateTime(), nullable=True),
        sa.Column("priority", priority_enum, nullable=True, server_default="medium"),
        sa.Column("status", action_status_enum, nullable=True, server_default="open"),
        sa.Column("source_reference", sa.String(length=256), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_action_items_id", "action_items", ["id"])

    op.create_table(
        "conversations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("telegram_chat_id", sa.String(length=64), nullable=False),
        sa.Column("session_id", sa.String(length=64), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_conversations_id", "conversations", ["id"])
    op.create_index("ix_conversations_telegram_chat_id", "conversations", ["telegram_chat_id"])

    op.create_table(
        "conversation_messages",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("conversation_id", sa.Integer(), sa.ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("sender_role", sa.String(length=32), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("tool_calls", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_conversation_messages_id", "conversation_messages", ["id"])

    op.create_table(
        "user_memories",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("key", sa.String(length=128), nullable=False, unique=True),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("category", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_user_memories_id", "user_memories", ["id"])
    op.create_index("ix_user_memories_key", "user_memories", ["key"])

    op.create_table(
        "news_articles",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("title", sa.String(length=512), nullable=False),
        sa.Column("url", sa.String(length=1024), nullable=False, unique=True),
        sa.Column("topic", sa.String(length=64), nullable=False),
        sa.Column("relevance_score", sa.Float(), nullable=True, server_default="0"),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("published_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_news_articles_id", "news_articles", ["id"])

    op.create_table(
        "audit_logs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("timestamp", sa.DateTime(), nullable=True),
        sa.Column("user_request", sa.Text(), nullable=True),
        sa.Column("selected_tool", sa.String(length=128), nullable=True),
        sa.Column("model_used", sa.String(length=64), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("execution_duration_ms", sa.Float(), nullable=True),
        sa.Column("external_operation", sa.String(length=256), nullable=True),
        sa.Column("rag_sources", sa.JSON(), nullable=True),
    )
    op.create_index("ix_audit_logs_id", "audit_logs", ["id"])


def downgrade() -> None:
    for table in (
        "audit_logs",
        "news_articles",
        "user_memories",
        "conversation_messages",
        "conversations",
        "action_items",
        "practice_answers",
        "practice_questions",
        "emails",
        "email_accounts",
        "academic_years",
        "users",
    ):
        op.drop_table(table)

    sa.Enum(name="actionstatusenum").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="priorityenum").drop(op.get_bind(), checkfirst=True)
