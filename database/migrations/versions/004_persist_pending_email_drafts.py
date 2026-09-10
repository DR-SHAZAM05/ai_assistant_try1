"""Persist email drafts awaiting explicit human approval.

Revision ID: 004_persist_pending_email_drafts
Revises: 003_reconcile_legacy_schema
Create Date: 2026-08-29 20:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "004_persist_pending_email_drafts"
down_revision = "003_reconcile_legacy_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "pending_email_drafts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("draft_id", sa.String(length=64), nullable=False, unique=True),
        sa.Column("owner_id", sa.String(length=64), nullable=False),
        sa.Column("original_message_id", sa.String(length=256), nullable=False),
        sa.Column("account_type", sa.String(length=32), nullable=False),
        sa.Column("recipient", sa.String(length=512), nullable=False),
        sa.Column("subject", sa.String(length=512), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("metadata", sa.JSON(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="pending_approval"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("decided_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_pending_email_drafts_id", "pending_email_drafts", ["id"])
    op.create_index("ix_pending_email_drafts_draft_id", "pending_email_drafts", ["draft_id"], unique=True)
    op.create_index("ix_pending_email_drafts_owner_id", "pending_email_drafts", ["owner_id"])
    op.create_index("ix_pending_email_drafts_status", "pending_email_drafts", ["status"])


def downgrade() -> None:
    op.drop_table("pending_email_drafts")
