import hashlib
from pathlib import Path

import pytest

from scripts.restore import verify_manifest_artifacts


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
