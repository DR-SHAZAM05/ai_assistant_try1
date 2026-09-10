"""Restore a backup set produced by scripts.backup; requires explicit confirmation."""

import argparse
import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Optional

import httpx

from src.app.core.config import settings


def restore_postgres(dump_file: Path, database: Optional[str] = None) -> None:
    executable = shutil.which("pg_restore")
    target_database = database or settings.POSTGRES_DB
    environment = os.environ.copy()
    environment["PGPASSWORD"] = settings.POSTGRES_PASSWORD
    if executable:
        subprocess.run(
            [
                executable,
                "--host", settings.POSTGRES_HOST,
                "--port", str(settings.POSTGRES_PORT),
                "--username", settings.POSTGRES_USER,
                "--dbname", target_database,
                "--clean",
                "--if-exists",
                "--no-owner",
                str(dump_file),
            ],
            check=True,
            env=environment,
        )
        return

    docker = shutil.which("docker")
    container = settings.POSTGRES_DOCKER_CONTAINER
    if not docker or not container:
        raise RuntimeError(
            "pg_restore was not found. Install PostgreSQL client tools or set POSTGRES_DOCKER_CONTAINER for Docker Compose."
        )
    with dump_file.open("rb") as source:
        subprocess.run(
            [
                docker,
                "exec",
                "-i",
                "-e",
                "PGPASSWORD",
                container,
                "pg_restore",
                "--host",
                "127.0.0.1",
                "--port",
                "5432",
                "--username",
                settings.POSTGRES_USER,
                "--dbname",
                target_database,
                "--clean",
                "--if-exists",
                "--no-owner",
            ],
            check=True,
            env=environment,
            stdin=source,
        )


def restore_qdrant(snapshot_file: Path, collection: str) -> None:
    base_url = settings.effective_qdrant_url.rstrip("/")
    headers = {"api-key": settings.QDRANT_API_KEY} if settings.QDRANT_API_KEY else {}
    with snapshot_file.open("rb") as source, httpx.Client(
        timeout=120.0, headers=headers
    ) as client:
        response = client.post(
            f"{base_url}/collections/{collection}/snapshots/upload",
            params={"priority": "snapshot"},
            files={"snapshot": (snapshot_file.name, source, "application/octet-stream")},
        )
        response.raise_for_status()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def verify_manifest_artifacts(manifest: dict, backup_dir: Path) -> None:
    artifacts = manifest.get("artifacts")
    if not artifacts:
        return
    for artifact in artifacts.values():
        artifact_path = backup_dir / artifact["file"]
        if not artifact_path.is_file() or _sha256(artifact_path) != artifact["sha256"]:
            raise RuntimeError(f"Backup integrity check failed for {artifact['file']}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Restore a PostgreSQL/Qdrant backup set.")
    parser.add_argument("backup_dir", help="Directory containing manifest.json, postgres.dump, and qdrant.snapshot.")
    parser.add_argument("--yes", action="store_true", help="Confirm destructive replacement of current data.")
    parser.add_argument("--postgres-db", help="Existing PostgreSQL database to restore into instead of the configured database.")
    parser.add_argument("--qdrant-collection", help="Qdrant collection to restore into instead of the backup collection.")
    args = parser.parse_args()
    if not args.yes:
        parser.error("Restore replaces existing data. Re-run with --yes after verifying the backup directory.")

    backup_dir = Path(args.backup_dir)
    manifest_file = backup_dir / "manifest.json"
    postgres_file = backup_dir / "postgres.dump"
    qdrant_file = backup_dir / "qdrant.snapshot"
    if not manifest_file.is_file() or not postgres_file.is_file() or not qdrant_file.is_file():
        raise RuntimeError("Backup directory is incomplete; manifest.json, postgres.dump, and qdrant.snapshot are required.")
    manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    verify_manifest_artifacts(manifest, backup_dir)
    collection = args.qdrant_collection or manifest.get("qdrant_collection", settings.QDRANT_COLLECTION)
    restore_postgres(postgres_file, args.postgres_db)
    restore_qdrant(qdrant_file, collection)
    print(f"Backup restored from {backup_dir}")


if __name__ == "__main__":
    main()
