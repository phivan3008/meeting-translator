"""Local snapshot backup and restore utilities.

These scripts implement the Git-free local snapshot workflow described in
``LOCAL_WORKFLOW.md``. A snapshot is a timestamped zip archive stored under
``.local_backups`` at the project root, accompanied by a JSON manifest with a
per-file SHA-256 checksum.

Backups deliberately exclude virtual environments, model weights, caches,
logs, audio recordings, secrets and the ``.local_backups`` directory itself.
"""

from __future__ import annotations

import fnmatch
from collections.abc import Iterable, Iterator
from pathlib import Path

# Directory (relative to project root) where snapshots are stored.
BACKUP_DIR_NAME = ".local_backups"

# Directory names that are always excluded anywhere in the tree.
EXCLUDED_DIR_NAMES: frozenset[str] = frozenset(
    {
        BACKUP_DIR_NAME,
        ".git",
        ".venv",
        "venv",
        "env",
        "__pycache__",
        ".mypy_cache",
        ".ruff_cache",
        ".pytest_cache",
        "node_modules",
        ".idea",
        ".vscode",
        "build",
        "dist",
        "logs",
        "recordings",
        "models",
        ".local_models",
    }
)

# Glob patterns (matched against the file name) that are always excluded.
EXCLUDED_FILE_PATTERNS: tuple[str, ...] = (
    "*.pyc",
    "*.pyo",
    "*.log",
    "*.tmp",
    "*.wav",
    "*.flac",
    "*.mp3",
    "*.ogg",
    "*.pcm",
    "*.raw",
    "*.bin",
    "*.pt",
    "*.pth",
    "*.onnx",
    "*.safetensors",
    "*.gguf",
    "*.ckpt",
    ".env",
    ".env.*",
    "*.pem",
    "*.key",
    "*.p12",
    "*.pfx",
    "secrets.*",
    "*.secret",
)


def _is_excluded_file(name: str) -> bool:
    # ``.env.example`` is documentation and must be kept, even though ``.env.*``
    # is excluded to protect real environment files.
    if name == ".env.example":
        return False
    return any(fnmatch.fnmatch(name, pattern) for pattern in EXCLUDED_FILE_PATTERNS)


def iter_backup_files(
    root: Path,
    excluded_dirs: Iterable[str] = EXCLUDED_DIR_NAMES,
) -> Iterator[Path]:
    """Yield files under ``root`` that should be included in a snapshot.

    Excluded directories are pruned entirely. Excluded file patterns and
    secret-like files are skipped. Paths are yielded relative to ``root``.
    """
    excluded = frozenset(excluded_dirs)
    root = root.resolve()

    def _walk(directory: Path) -> Iterator[Path]:
        for entry in sorted(directory.iterdir(), key=lambda p: p.name):
            if entry.is_dir():
                if entry.name in excluded:
                    continue
                yield from _walk(entry)
            elif entry.is_file():
                if _is_excluded_file(entry.name):
                    continue
                yield entry.relative_to(root)

    yield from _walk(root)
