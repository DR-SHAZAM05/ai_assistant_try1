"""m4_practice_document_tracking

Revision ID: 002_m4_practice_document_tracking
Revises: 001_initial_m2_tables
Create Date: 2026-08-21 16:30:00.000000

"""
from alembic import op


revision = "002_m4_practice_docs"
down_revision = "001_initial_m2_tables"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS practice_documents (
            id SERIAL PRIMARY KEY,
            document_id VARCHAR(256) NOT NULL DEFAULT '',
            academic_year VARCHAR(32) NOT NULL,
            file_name VARCHAR(256) NOT NULL,
            file_path VARCHAR(512) NOT NULL,
            document_type VARCHAR(64) NOT NULL,
            qdrant_collection VARCHAR(128) NOT NULL,
            checksum VARCHAR(64) NOT NULL DEFAULT '',
            status VARCHAR(32) NOT NULL DEFAULT 'processed',
            chunks_count INTEGER NOT NULL DEFAULT 0,
            vectors_count INTEGER NOT NULL DEFAULT 0,
            metadata JSON,
            created_at TIMESTAMP,
            updated_at TIMESTAMP
        )
        """
    )
    op.execute("ALTER TABLE practice_documents ADD COLUMN IF NOT EXISTS document_id VARCHAR(256) NOT NULL DEFAULT ''")
    op.execute("ALTER TABLE practice_documents ADD COLUMN IF NOT EXISTS checksum VARCHAR(64) NOT NULL DEFAULT ''")
    op.execute("ALTER TABLE practice_documents ADD COLUMN IF NOT EXISTS status VARCHAR(32) NOT NULL DEFAULT 'processed'")
    op.execute("ALTER TABLE practice_documents ADD COLUMN IF NOT EXISTS chunks_count INTEGER NOT NULL DEFAULT 0")
    op.execute("ALTER TABLE practice_documents ADD COLUMN IF NOT EXISTS vectors_count INTEGER NOT NULL DEFAULT 0")
    op.execute("ALTER TABLE practice_documents ADD COLUMN IF NOT EXISTS metadata JSON")
    op.execute("ALTER TABLE practice_documents ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP")
    op.execute("CREATE INDEX IF NOT EXISTS ix_practice_documents_academic_year ON practice_documents (academic_year)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_practice_documents_document_id ON practice_documents (document_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_practice_documents_checksum ON practice_documents (checksum)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_practice_documents_status ON practice_documents (status)")
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_practice_document_year_path_collection
        ON practice_documents (academic_year, file_path, qdrant_collection)
        """
    )


def downgrade() -> None:
    op.drop_table("practice_documents")
