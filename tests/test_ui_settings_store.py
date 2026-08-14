"""Tests for file-backed client settings persistence (no Qt)."""

from __future__ import annotations

from pathlib import Path

from client.ui.settings_store import (
    PersistedSettings,
    PersistedSourceSettings,
    SettingsStore,
    default_settings_path,
)


def test_load_missing_file_returns_defaults(tmp_path: Path) -> None:
    store = SettingsStore(tmp_path / "nope" / "settings.json")
    settings = store.load()
    assert settings == PersistedSettings()


def test_save_then_load_round_trips(tmp_path: Path) -> None:
    store = SettingsStore(tmp_path / "settings.json")
    original = PersistedSettings(
        preset="japanese_side",
        microphone=PersistedSourceSettings(
            enabled=False,
            device_index=2,
            device_name="Mic",
            source_language="ja",
            target_language="vi",
        ),
        loopback=PersistedSourceSettings(
            enabled=True,
            device_index=None,
            device_name="",
            source_language="vi",
            target_language="ja",
        ),
    )
    store.save(original)

    loaded = store.load()

    assert loaded == original


def test_save_creates_parent_directories(tmp_path: Path) -> None:
    nested = tmp_path / "a" / "b" / "c" / "settings.json"
    store = SettingsStore(nested)
    store.save(PersistedSettings())
    assert nested.exists()


def test_load_corrupt_json_falls_back_to_defaults(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    path.write_text("{not valid json", encoding="utf-8")
    store = SettingsStore(path)
    assert store.load() == PersistedSettings()


def test_load_non_object_json_falls_back_to_defaults(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    path.write_text("[1, 2, 3]", encoding="utf-8")
    store = SettingsStore(path)
    assert store.load() == PersistedSettings()


def test_load_partial_document_fills_in_defaults(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    path.write_text('{"preset": "japanese_side"}', encoding="utf-8")
    store = SettingsStore(path)
    settings = store.load()
    assert settings.preset == "japanese_side"
    assert settings.microphone == PersistedSourceSettings()
    assert settings.loopback == PersistedSourceSettings()


def test_saved_file_contains_no_secret_looking_keys(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    store = SettingsStore(path)
    store.save(PersistedSettings())
    text = path.read_text(encoding="utf-8").lower()
    for forbidden in ("token", "password", "secret", "authorization"):
        assert forbidden not in text


def test_default_settings_path_is_under_a_dedicated_directory() -> None:
    path = default_settings_path()
    assert path.name == "client_settings.json"
    assert path.parent.name == "MeetingTranslator"
