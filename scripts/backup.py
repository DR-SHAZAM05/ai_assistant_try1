"""Create a PostgreSQL dump and a Qdrant collection snapshot for disaster recovery.

Usage:
    python -m scripts.backup [--output-dir <dir>] [--retention]

The backup set is written to <output-dir>/<timestamp>/ and contains:
  - postgres.dump    (pg_dump --format=custom)
  - qdrant.snapshot  (Qdrant snapshot API)
  - manifest.json    (metadata + SHA-256 checksums)

Pass --retention to automatically purge old backup sets after the new one is created.
"""

import argparse
import hashlib
import json
import os
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import httpx

from src.app.core.config import settings


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def backup_postgres(destination: Path) -> Path:
    """Dump the configured PostgreSQL database to *destination* in custom format.

    Prefers a locally-installed pg_dump; falls back to docker exec so the
    script works both inside and outside the Docker environment.

    The database password is passed via the PGPASSWORD environment variable and
    never written to disk or printed to stdout.
    """
    executable = shutil.which("pg_dump")
    environment = os.environ.copy()
    environment["PGPASSWORD"] = settings.POSTGRES_PASSWORD
    if executable:
        subprocess.run(
            [
                executable,
                "--host", settings.POSTGRES_HOST,
                "--port", str(settings.POSTGRES_PORT),
                "--username", settings.POSTGRES_USER,
                "--format", "custom",
                "--file", str(destination),
                settings.POSTGRES_DB,
            ],
            check=True,
            env=environment,
        )
        return destination

    docker = shutil.which("docker")
    container = settings.POSTGRES_DOCKER_CONTAINER
    if not docker or not container:
        raise RuntimeError(
            "pg_dump was not found. Install PostgreSQL client tools or set "
            "POSTGRES_DOCKER_CONTAINER in .env for Docker Compose."
        )
    with destination.open("wb") as output:
        subprocess.run(
            [
                docker,
                "exec",
                "-i",
                "-e",
                "PGPASSWORD",
                container,
                "pg_dump",
                "--host",
                "127.0.0.1",
                "--port",
                "5432",
                "--username",
                settings.POSTGRES_USER,
                "--format",
                "custom",
                settings.POSTGRES_DB,
            ],
            check=True,
            env=environment,
            stdout=output,
        )
    return destination


def backup_qdrant(destination: Path) -> Path:
    """Snapshot the configured Qdrant collection to *destination*.

    The API key is read from settings and sent only in the request header --
    never written to disk or logged.
    """
    base_url = settings.effective_qdrant_url.rstrip("/")
    headers = {"api-key": settings.QDRANT_API_KEY} if settings.QDRANT_API_KEY else {}
    with httpx.Client(timeout=settings.EXTERNAL_REQUEST_TIMEOUT_SECONDS, headers=headers) as client:
        response = client.post(f"{base_url}/collections/{settings.QDRANT_COLLECTION}/snapshots")
        response.raise_for_status()
        snapshot_name = response.json()["result"]["name"]
        snapshot = client.get(
            f"{base_url}/collections/{settings.QDRANT_COLLECTION}/snapshots/{snapshot_name}"
        )
        snapshot.raise_for_status()
    destination.write_bytes(snapshot.content)
    return destination


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Back up PostgreSQL and the configured Qdrant collection."
    )
    parser.add_argument(
        "--output-dir",
        default=settings.BACKUP_DIR,
        help=f"Root directory for backup sets (default: {settings.BACKUP_DIR!r}).",
    )
    parser.add_argument(
        "--retention",
        action="store_true",
        help="After creating the new backup, purge sets older than BACKUP_RETENTION_DAYS.",
    )
    args = parser.parse_args()

    output_dir = Path(args.output_dir) / _timestamp()
    output_dir.mkdir(parents=True, exist_ok=False)
    print(f"Creating backup in {output_dir} ...")

    postgres_file = backup_postgres(output_dir / "postgres.dump")
    print(f"  PostgreSQL dump: {postgres_file.stat().st_size:,} bytes")

    qdrant_file = backup_qdrant(output_dir / "qdrant.snapshot")
    print(f"  Qdrant snapshot: {qdrant_file.stat().st_size:,} bytes")

    manifest = {
        "format_version": 2,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "postgres_database": settings.POSTGRES_DB,
        "qdrant_collection": settings.QDRANT_COLLECTION,
        "artifacts": {
            "postgres_dump": {
                "file": postgres_file.name,
                "bytes": postgres_file.stat().st_size,
                "sha256": _sha256(postgres_file),
            },
            "qdrant_snapshot": {
                "file": qdrant_file.name,
                "bytes": qdrant_file.stat().st_size,
                "sha256": _sha256(qdrant_file),
            },
        },
    }
    (output_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"Backup created: {output_dir}")

    if args.retention:
        from scripts.retention import run_retention
        deleted = run_retention(Path(args.output_dir), settings.BACKUP_RETENTION_DAYS)
        if deleted:
            print(f"Retention: removed {deleted} expired backup set(s).")


if __name__ == "__main__":
    main()
