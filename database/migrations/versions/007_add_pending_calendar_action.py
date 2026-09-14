# Alembic migration for PendingCalendarAction
"""Add pending_calendar_actions table.
Revision ID: 007_add_pending_calendar_action
Revises: 006_user_scoped_persistence
Create Date: 2026-09-14 12:30:00.000000
"""

from alembic import op
import sqlalchemy as sa
import datetime
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "007_add_pending_calendar_action"
down_revision = "006_user_scoped_persistence"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "pending_calendar_actions",
        sa.Column("id", sa.Integer, primary_key=True, index=True),
        sa.Column("action_id", sa.String(64), unique=True, nullable=False),
        sa.Column("owner_id", sa.String(64), nullable=False),
        sa.Column("action_type", sa.String(32), nullable=False),
        sa.Column("payload", postgresql.JSONB, nullable=False),
        sa.Column("preview_text", sa.Text, nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default=sa.text("'pending_approval'")),
        sa.Column("created_at", sa.DateTime, default=datetime.datetime.utcnow, nullable=False),
        sa.Column("expires_at", sa.DateTime, nullable=False),
        sa.Column("decided_at", sa.DateTime, nullable=True),
    )
    # Only create indexes if they don't exist
    op.execute("CREATE INDEX IF NOT EXISTS ix_pending_calendar_actions_action_id ON pending_calendar_actions (action_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_pending_calendar_actions_owner_id ON pending_calendar_actions (owner_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_pending_calendar_actions_status ON pending_calendar_actions (status)")


def downgrade() -> None:
    op.drop_table("pending_calendar_actions")
