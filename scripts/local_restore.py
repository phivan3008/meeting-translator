"""Restore a local snapshot created by ``local_backup.py``.

Usage:

    python scripts/local_restore.py --snapshot <name> [--root PATH] [--dest PATH] [--verify]

By default the snapshot is extracted into a sibling directory
``.local_backups/restore_<name>`` so that an existing working tree is never
overwritten implicitly. Pass ``--dest`` to choose a target directory. Use
``--verify`` to check extracted files against the manifest checksums.

This script only reads snapshot archives and writes to a restore directory; it
never deletes source files.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from backup_common import BACKUP_DIR_NAME  # noqa: E402


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _resolve_zip(backup_dir: Path, snapshot: str) -> Path:
    candidate = backup_dir / snapshot
    if candidate.suffix != ".zip":
        candidate = backup_dir / f"{snapshot}.zip"
    if not candidate.is_file():
        raise FileNotFoundError(f"Snapshot archive not found: {candidate}")
    return candidate


def restore_snapshot(root: Path, snapshot: str, dest: Path | None, verify: bool) -> Path:
    """Extract a snapshot into ``dest`` and optionally verify checksums."""
    root = root.resolve()
    backup_dir = root / BACKUP_DIR_NAME
    zip_path = _resolve_zip(backup_dir, snapshot)
    base_name = zip_path.with_suffix("").name

    target = dest.resolve() if dest else backup_dir / f"restore_{base_name}"
    target.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(zip_path, "r") as archive:
        archive.extractall(target)

    if verify:
        manifest_path = backup_dir / f"{base_name}.manifest.json"
        if not manifest_path.is_file():
            raise FileNotFoundError(f"Manifest not found for verification: {manifest_path}")
        manifest = json.loads(manifest_path.read_text("utf-8"))
        mismatches: list[str] = []
        for entry in manifest["files"]:
            extracted = target / entry["path"]
            if not extracted.is_file() or _sha256(extracted) != entry["sha256"]:
                mismatches.append(entry["path"])
        if mismatches:
            raise ValueError(f"Checksum mismatch for {len(mismatches)} file(s): {mismatches[:5]}")

    return target


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Restore a local project snapshot.")
    parser.add_argument("--snapshot", required=True, help="Snapshot name or zip file name.")
    parser.add_argument("--root", default=".", help="Project root containing .local_backups.")
    parser.add_argument("--dest", default=None, help="Destination directory for extraction.")
    parser.add_argument("--verify", action="store_true", help="Verify checksums after extraction.")
    args = parser.parse_args(argv)

    dest = Path(args.dest) if args.dest else None
    target = restore_snapshot(Path(args.root), args.snapshot, dest, args.verify)
    print(f"Restored snapshot into: {target}")
    if args.verify:
        print("Checksum verification: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
