import hashlib
import json
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from scripts.restore import verify_manifest_artifacts
from scripts.retention import _is_valid_backup_set, _parse_dir_timestamp, run_retention


def test_verify_manifest_artifacts_accepts_matching_checksums(tmp_path: Path):
    artifact = tmp_path / "postgres.dump"
    artifact.write_bytes(b"backup-data")
    manifest = {
        "artifacts": {
            "postgres_dump": {
                "file": artifact.name,
                "sha256": hashlib.sha256(b"backup-data").hexdigest(),
            }
        }
    }

    verify_manifest_artifacts(manifest, tmp_path)


def test_verify_manifest_artifacts_rejects_tampering(tmp_path: Path):
    artifact = tmp_path / "postgres.dump"
    artifact.write_bytes(b"tampered")
    manifest = {
        "artifacts": {
            "postgres_dump": {
                "file": artifact.name,
                "sha256": hashlib.sha256(b"original").hexdigest(),
            }
        }
    }

    with pytest.raises(RuntimeError, match="integrity"):
        verify_manifest_artifacts(manifest, tmp_path)


def test_verify_manifest_artifacts_rejects_missing_file(tmp_path: Path):
    manifest = {
        "artifacts": {
            "postgres_dump": {
                "file": "missing.dump",
                "sha256": hashlib.sha256(b"data").hexdigest(),
            }
        }
    }

    with pytest.raises(RuntimeError, match="integrity"):
        verify_manifest_artifacts(manifest, tmp_path)


def test_parse_dir_timestamp_valid():
    result = _parse_dir_timestamp("20260910T161339Z")
    assert result is not None
    assert result.year == 2026
    assert result.month == 9
    assert result.day == 10


def test_parse_dir_timestamp_invalid():
    assert _parse_dir_timestamp("not-a-timestamp") is None
    assert _parse_dir_timestamp("20260910") is None  # Missing T
    assert _parse_dir_timestamp("20260910T161339") is None  # Missing Z


def test_is_valid_backup_set_valid(tmp_path: Path):
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"format_version": 2}), encoding="utf-8")
    assert _is_valid_backup_set(tmp_path) is True


def test_is_valid_backup_set_no_manifest(tmp_path: Path):
    assert _is_valid_backup_set(tmp_path) is False


def test_is_valid_backup_set_invalid_json(tmp_path: Path):
    manifest = tmp_path / "manifest.json"
    manifest.write_text("not valid json", encoding="utf-8")
    assert _is_valid_backup_set(tmp_path) is False


def test_is_valid_backup_set_no_format_version(tmp_path: Path):
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"other": "data"}), encoding="utf-8")
    assert _is_valid_backup_set(tmp_path) is False


def test_run_retention_dry_run(tmp_path: Path):
    """Test retention in dry-run mode does not delete anything."""
    # Create some backup directories
    old_backup = tmp_path / "20260901T000000Z"
    old_backup.mkdir()
    old_manifest = old_backup / "manifest.json"
    old_manifest.write_text(json.dumps({"format_version": 2}), encoding="utf-8")

    recent_backup = tmp_path / "20260914T000000Z"
    recent_backup.mkdir()
    recent_manifest = recent_backup / "manifest.json"
    recent_manifest.write_text(json.dumps({"format_version": 2}), encoding="utf-8")

    # Run retention with 5 days cutoff in dry-run mode
    deleted = run_retention(tmp_path, retention_days=5, dry_run=True)

    # Should report 1 deletion but not actually delete
    assert deleted == 1
    assert old_backup.exists()
    assert recent_backup.exists()


def test_run_retention_deletes_expired(tmp_path: Path):
    """Test retention actually deletes expired backups."""
    old_backup = tmp_path / "20260901T000000Z"
    old_backup.mkdir()
    old_manifest = old_backup / "manifest.json"
    old_manifest.write_text(json.dumps({"format_version": 2}), encoding="utf-8")

    recent_backup = tmp_path / "20260914T000000Z"
    recent_backup.mkdir()
    recent_manifest = recent_backup / "manifest.json"
    recent_manifest.write_text(json.dumps({"format_version": 2}), encoding="utf-8")

    # Run retention with 5 days cutoff (not dry-run)
    deleted = run_retention(tmp_path, retention_days=5, dry_run=False)

    # Should delete old backup
    assert deleted == 1
    assert not old_backup.exists()
    assert recent_backup.exists()


def test_run_retention_skips_validation_dir(tmp_path: Path):
    """Test that the validation/ subdirectory is never deleted."""
    validation_dir = tmp_path / "validation"
    validation_dir.mkdir()
    validation_manifest = validation_dir / "manifest.json"
    validation_manifest.write_text(json.dumps({"format_version": 2}), encoding="utf-8")

    deleted = run_retention(tmp_path, retention_days=0, dry_run=False)

    # Should not delete validation directory
    assert deleted == 0
    assert validation_dir.exists()


def test_run_retention_skips_invalid_backup_sets(tmp_path: Path):
    """Test that directories without valid manifests are skipped."""
    old_backup = tmp_path / "20260901T000000Z"
    old_backup.mkdir()
    # No manifest.json

    deleted = run_retention(tmp_path, retention_days=0, dry_run=False)

    # Should not delete invalid backup set
    assert deleted == 0
    assert old_backup.exists()


def test_run_retention_idempotent(tmp_path: Path):
    """Test that running retention multiple times is safe."""
    old_backup = tmp_path / "20260901T000000Z"
    old_backup.mkdir()
    old_manifest = old_backup / "manifest.json"
    old_manifest.write_text(json.dumps({"format_version": 2}), encoding="utf-8")

    # Run retention twice
    deleted1 = run_retention(tmp_path, retention_days=0, dry_run=False)
    deleted2 = run_retention(tmp_path, retention_days=0, dry_run=False)

    # First run deletes, second run does nothing
    assert deleted1 == 1
    assert deleted2 == 0
