"""Backup retention policy: remove backup sets older than the configured number of days.

Usage:
    python -m scripts.retention [--backup-dir <dir>] [--days <N>] [--dry-run]

A backup set directory is considered expired when its name encodes a UTC timestamp
(format: YYYYMMDDTHHMMSSz) that is older than <days> days.  Directories that do not
match the timestamp pattern are never touched.

Only directories that contain a valid manifest.json are considered backup sets.
The special sub-directory "validation/" inside the backup root is always skipped.
"""

import argparse
import json
import re
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.app.core.config import settings

# Matches timestamp directories produced by backup.py: 20260910T161339Z
_TIMESTAMP_RE = re.compile(r"^\d{8}T\d{6}Z$")


def _parse_dir_timestamp(name: str) -> datetime | None:
    """Return the UTC datetime encoded in *name*, or None if not a timestamp dir."""
    if not _TIMESTAMP_RE.match(name):
        return None
    try:
        return datetime.strptime(name, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _is_valid_backup_set(path: Path) -> bool:
    """Return True only if the directory contains a parseable manifest.json."""
    manifest = path / "manifest.json"
    if not manifest.is_file():
        return False
    try:
        data = json.loads(manifest.read_text(encoding="utf-8"))
        return data.get("format_version") is not None
    except (json.JSONDecodeError, OSError):
        return False


def run_retention(backup_root: Path, retention_days: int, dry_run: bool = False) -> int:
    """Delete expired backup sets from *backup_root*.

    Args:
        backup_root: Root directory that contains timestamped backup set sub-directories.
        retention_days: Backup sets older than this many days are deleted.
        dry_run: If True, print what would be deleted without actually deleting.

    Returns:
        Number of backup sets deleted (or that would be deleted in dry-run mode).
    """
    if not backup_root.is_dir():
        return 0

    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
    deleted = 0

    for entry in sorted(backup_root.iterdir()):
        # Never touch the special validation sub-directory
        if entry.name == "validation":
            continue
        if not entry.is_dir():
            continue

        ts = _parse_dir_timestamp(entry.name)
        if ts is None:
            # Not a timestamped backup set -- skip safely
            continue

        if ts >= cutoff:
            continue  # Still within retention window

        if not _is_valid_backup_set(entry):
            # Safety: do not delete directories that don't look like backup sets
            print(f"  SKIP (no valid manifest): {entry}")
            continue

        age_days = (datetime.now(timezone.utc) - ts).days
        if dry_run:
            print(f"  [DRY RUN] Would delete: {entry}  (age: {age_days}d)")
        else:
            print(f"  Deleting expired backup: {entry}  (age: {age_days}d)")
            shutil.rmtree(entry)
        deleted += 1

    return deleted


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Remove backup sets older than BACKUP_RETENTION_DAYS."
    )
    parser.add_argument(
        "--backup-dir",
        default=settings.BACKUP_DIR,
        help=f"Root directory containing timestamped backup sets (default: {settings.BACKUP_DIR!r}).",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=settings.BACKUP_RETENTION_DAYS,
        help=f"Retention window in days (default: {settings.BACKUP_RETENTION_DAYS}).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be deleted without actually deleting anything.",
    )
    args = parser.parse_args()

    backup_root = Path(args.backup_dir)
    print(f"Retention: scanning {backup_root} (cutoff: {args.days}d) ...")
    deleted = run_retention(backup_root, args.days, dry_run=args.dry_run)
    if deleted == 0:
        print("No expired backup sets found.")
    elif args.dry_run:
        print(f"{deleted} backup set(s) would be deleted (dry-run mode).")
    else:
        print(f"Removed {deleted} expired backup set(s).")


if __name__ == "__main__":
    main()
