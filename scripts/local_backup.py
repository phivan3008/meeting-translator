"""Create a timestamped local snapshot of the project.

Usage:

    python scripts/local_backup.py [--label PHASE] [--root PATH]

Produces two artifacts under ``.local_backups``:

- ``<timestamp>_<label>.zip``: the archived source tree.
- ``<timestamp>_<label>.manifest.json``: metadata plus per-file SHA-256.

The snapshot excludes virtual environments, model weights, caches, logs, audio
recordings, secrets and ``.local_backups`` itself (see ``backup_common``).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import zipfile
from datetime import UTC, datetime
from pathlib import Path

# Allow running as a script (python scripts/local_backup.py) without install.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from backup_common import BACKUP_DIR_NAME, iter_backup_files  # noqa: E402


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def create_snapshot(root: Path, label: str) -> Path:
    """Create a snapshot zip and manifest; return the zip path."""
    root = root.resolve()
    backup_dir = root / BACKUP_DIR_NAME
    backup_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    safe_label = "".join(c if c.isalnum() or c in "-_" else "_" for c in label)
    base_name = f"{timestamp}_{safe_label}"
    zip_path = backup_dir / f"{base_name}.zip"
    manifest_path = backup_dir / f"{base_name}.manifest.json"

    files = list(iter_backup_files(root))
    manifest_files: list[dict[str, object]] = []

    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for rel in files:
            absolute = root / rel
            archive.write(absolute, arcname=str(rel).replace("\\", "/"))
            manifest_files.append(
                {
                    "path": str(rel).replace("\\", "/"),
                    "size": absolute.stat().st_size,
                    "sha256": _sha256(absolute),
                }
            )

    manifest = {
        "label": label,
        "timestamp": timestamp,
        "root": str(root),
        "file_count": len(manifest_files),
        "zip_name": zip_path.name,
        "files": manifest_files,
    }
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), "utf-8")
    return zip_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Create a local project snapshot.")
    parser.add_argument("--label", default="snapshot", help="Snapshot label, e.g. phase name.")
    parser.add_argument("--root", default=".", help="Project root to snapshot.")
    args = parser.parse_args(argv)

    zip_path = create_snapshot(Path(args.root), args.label)
    print(f"Created snapshot: {zip_path}")
    print(f"Manifest: {zip_path.with_suffix('').as_posix()}.manifest.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
