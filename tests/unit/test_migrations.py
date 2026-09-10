import os
import subprocess
import sys
from pathlib import Path


def test_alembic_offline_upgrade_creates_schema_sql():
    root = Path(__file__).resolve().parents[2]
    environment = os.environ.copy()
    environment["DATABASE_URL"] = "postgresql+asyncpg://postgres:password@localhost:5432/academic_assistant_db"
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head", "--sql"],
        cwd=root,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    sql = result.stdout.lower()
    assert "create table users" in sql
    assert "practice_documents" in sql
    assert "create table audit_logs" in sql
    assert "003_reconcile_legacy_schema" in sql
    assert "pending_email_drafts" in sql
    assert "004_persist_pending_email_drafts" in sql
    assert "002_m4_practice_docs" in sql
