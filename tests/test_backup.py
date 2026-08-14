"""Tests for local snapshot backup selection, exclusion and round-trip."""

from __future__ import annotations

from pathlib import Path

from scripts.backup_common import iter_backup_files
from scripts.local_backup import create_snapshot
from scripts.local_restore import restore_snapshot


def _make_tree(root: Path) -> None:
    (root / "shared").mkdir(parents=True)
    (root / "shared" / "settings.py").write_text("x = 1\n", "utf-8")
    (root / "README.md").write_text("readme\n", "utf-8")
    (root / ".env.example").write_text("APP_ENV=development\n", "utf-8")

    # Files and directories that must be excluded.
    (root / ".env").write_text("SECRET=should-not-be-backed-up\n", "utf-8")
    (root / "server.key").write_text("PRIVATE", "utf-8")
    (root / "recording.wav").write_bytes(b"\x00\x01")
    (root / "model.safetensors").write_bytes(b"\x00")
    (root / ".venv").mkdir()
    (root / ".venv" / "pyvenv.cfg").write_text("home = x\n", "utf-8")
    (root / "logs").mkdir()
    (root / "logs" / "app.log").write_text("log line\n", "utf-8")
    (root / "__pycache__").mkdir()
    (root / "__pycache__" / "x.pyc").write_bytes(b"\x00")
    (root / "models").mkdir()
    (root / "models" / "weights.bin").write_bytes(b"\x00")


def test_iter_backup_files_selection(tmp_path: Path) -> None:
    _make_tree(tmp_path)
    selected = {p.as_posix() for p in iter_backup_files(tmp_path)}

    assert "shared/settings.py" in selected
    assert "README.md" in selected
    assert ".env.example" in selected

    assert ".env" not in selected
    assert "server.key" not in selected
    assert "recording.wav" not in selected
    assert "model.safetensors" not in selected
    assert ".venv/pyvenv.cfg" not in selected
    assert "logs/app.log" not in selected
    assert "__pycache__/x.pyc" not in selected
    assert "models/weights.bin" not in selected


def test_backup_excludes_itself(tmp_path: Path) -> None:
    _make_tree(tmp_path)
    create_snapshot(tmp_path, "test")
    # A second snapshot must not include the first snapshot's artifacts.
    selected = {p.as_posix() for p in iter_backup_files(tmp_path)}
    assert not any(p.startswith(".local_backups/") for p in selected)


def test_snapshot_creates_manifest_and_checksums(tmp_path: Path) -> None:
    _make_tree(tmp_path)
    zip_path = create_snapshot(tmp_path, "phase-00")
    assert zip_path.is_file()
    manifest_path = zip_path.with_suffix("").with_suffix(".manifest.json")
    # base name is <ts>_<label>; manifest is <ts>_<label>.manifest.json
    manifest_path = zip_path.parent / f"{zip_path.stem}.manifest.json"
    assert manifest_path.is_file()

    import json

    manifest = json.loads(manifest_path.read_text("utf-8"))
    assert manifest["file_count"] >= 3
    for entry in manifest["files"]:
        assert len(entry["sha256"]) == 64
        assert entry["size"] >= 0


def test_backup_restore_roundtrip_verifies(tmp_path: Path) -> None:
    _make_tree(tmp_path)
    zip_path = create_snapshot(tmp_path, "roundtrip")
    snapshot_name = zip_path.stem
    target = restore_snapshot(tmp_path, snapshot_name, dest=None, verify=True)
    assert (target / "shared" / "settings.py").is_file()
    assert (target / ".env.example").is_file()
    assert not (target / ".env").exists()
