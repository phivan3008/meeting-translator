"""Tests for environment-based settings validation."""

from __future__ import annotations

import pytest

from shared.settings import Settings


def _base_env() -> dict[str, str]:
    return {
        "APP_ENV": "development",
        "LOG_LEVEL": "INFO",
        "SERVER_PORT": "8080",
    }


def test_defaults_load_without_env(monkeypatch: pytest.MonkeyPatch) -> None:
    # Ignore any local .env by pointing pydantic at a nonexistent file.
    settings = Settings(_env_file=None)  # type: ignore[call-arg]
    assert settings.app_env == "development"
    assert settings.server_port == 8080
    assert settings.store_raw_audio is False
    assert settings.log_transcript_content is False
    assert settings.log_translation_content is False


def test_env_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("SERVER_PORT", "9090")
    monkeypatch.setenv("VAD_THRESHOLD", "0.7")
    settings = Settings(_env_file=None)  # type: ignore[call-arg]
    assert settings.is_production is True
    assert settings.server_port == 9090
    assert settings.vad_threshold == pytest.approx(0.7)


def test_invalid_port_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SERVER_PORT", "70000")
    with pytest.raises(ValueError):
        Settings(_env_file=None)  # type: ignore[call-arg]


def test_invalid_vad_threshold_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VAD_THRESHOLD", "1.5")
    with pytest.raises(ValueError):
        Settings(_env_file=None)  # type: ignore[call-arg]


def test_hard_silence_must_exceed_soft(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VAD_SOFT_SILENCE_MS", "800")
    monkeypatch.setenv("VAD_HARD_SILENCE_MS", "500")
    with pytest.raises(ValueError):
        Settings(_env_file=None)  # type: ignore[call-arg]


def test_invalid_log_level_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LOG_LEVEL", "VERBOSE")
    with pytest.raises(ValueError):
        Settings(_env_file=None)  # type: ignore[call-arg]
