"""File-backed client settings persistence (no Qt, no secrets).

Stores only non-sensitive UI preferences: device selection (index/name),
per-source enabled flags, and the language preset/mapping. Never stores
auth tokens, session ids or any other secret -- the same "no secrets in
persisted state" principle CLAUDE.md applies to status documents applies
here too. Deliberately a plain JSON file (not ``QSettings``/the Windows
registry) so persistence logic is fully unit-testable without Qt.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path


@dataclass
class PersistedSourceSettings:
    """Persisted per-source (microphone/loopback) preferences."""

    enabled: bool = True
    device_index: int | None = None
    device_name: str = ""
    source_language: str = "vi"
    target_language: str = "ja"


@dataclass
class PersistedSettings:
    """The full persisted settings document."""

    preset: str = "vietnamese_side"
    microphone: PersistedSourceSettings = field(default_factory=PersistedSourceSettings)
    loopback: PersistedSourceSettings = field(default_factory=PersistedSourceSettings)


class SettingsStore:
    """Reads/writes :class:`PersistedSettings` as JSON at a fixed path.

    Corrupt or unreadable files fall back to defaults rather than raising,
    since settings are a convenience, not a source of truth the app must
    have to function.
    """

    def __init__(self, path: Path) -> None:
        self._path = path

    @property
    def path(self) -> Path:
        return self._path

    def load(self) -> PersistedSettings:
        if not self._path.exists():
            return PersistedSettings()
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return PersistedSettings()
        return _from_dict(raw)

    def save(self, settings: PersistedSettings) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(asdict(settings), indent=2), encoding="utf-8")


def _source_from_dict(data: object) -> PersistedSourceSettings:
    if not isinstance(data, dict):
        return PersistedSourceSettings()
    defaults = PersistedSourceSettings()
    return PersistedSourceSettings(
        enabled=bool(data.get("enabled", defaults.enabled)),
        device_index=data.get("device_index"),
        device_name=str(data.get("device_name", defaults.device_name)),
        source_language=str(data.get("source_language", defaults.source_language)),
        target_language=str(data.get("target_language", defaults.target_language)),
    )


def _from_dict(raw: object) -> PersistedSettings:
    if not isinstance(raw, dict):
        return PersistedSettings()
    defaults = PersistedSettings()
    return PersistedSettings(
        preset=str(raw.get("preset", defaults.preset)),
        microphone=_source_from_dict(raw.get("microphone")),
        loopback=_source_from_dict(raw.get("loopback")),
    )


def default_settings_path() -> Path:
    """Default per-user settings file location.

    Windows: ``%APPDATA%\\MeetingTranslator\\client_settings.json``. Falls
    back to the user's home directory on other platforms (e.g. for local
    development/testing off Windows).
    """
    base = os.environ.get("APPDATA") or str(Path.home())
    return Path(base) / "MeetingTranslator" / "client_settings.json"
