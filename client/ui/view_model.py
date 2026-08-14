"""Qt-independent client UI state (view model).

Deliberately free of any PySide6 import so it is fully unit-testable on the
CPU suite, per this phase's own required outcome ("view-model tests
independent of Qt rendering"). ``client/ui/main_window.py`` is the only
module that imports PySide6 and renders this state into real widgets; it
mutates a :class:`ClientViewModel` instance and re-reads it to update the
screen, but contains no state logic of its own.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum

from client.audio.types import DeviceInfo
from client.transport.sender import ConnectionState
from client.ui.settings_store import PersistedSettings, PersistedSourceSettings
from shared.protocol.enums import FinalReason, Language, StreamSource, TranslationStatus
from shared.protocol.messages import (
    ErrorEvent,
    TranscriptionPartial,
    TranslationUpdated,
    UtteranceFinal,
)

InboundEvent = TranscriptionPartial | UtteranceFinal | TranslationUpdated | ErrorEvent


class LanguagePreset(Enum):
    """Named source/target language mapping presets (docs/PRODUCT_REQUIREMENTS.md).

    ``VIETNAMESE_SIDE``: microphone is Vietnamese->Japanese, loopback is
    Japanese->Vietnamese. ``JAPANESE_SIDE`` is the mirror image. ``CUSTOM``
    means the user changed the mapping explicitly in settings.
    """

    VIETNAMESE_SIDE = "vietnamese_side"
    JAPANESE_SIDE = "japanese_side"
    CUSTOM = "custom"


_PRESET_MAPPING: dict[LanguagePreset, dict[StreamSource, tuple[Language, Language]]] = {
    LanguagePreset.VIETNAMESE_SIDE: {
        StreamSource.MICROPHONE: (Language.VIETNAMESE, Language.JAPANESE),
        StreamSource.LOOPBACK: (Language.JAPANESE, Language.VIETNAMESE),
    },
    LanguagePreset.JAPANESE_SIDE: {
        StreamSource.MICROPHONE: (Language.JAPANESE, Language.VIETNAMESE),
        StreamSource.LOOPBACK: (Language.VIETNAMESE, Language.JAPANESE),
    },
}


def resolve_preset_mapping(
    preset: LanguagePreset,
) -> dict[StreamSource, tuple[Language, Language]]:
    """Return the ``{source: (source_language, target_language)}`` mapping.

    Raises for ``CUSTOM``, since a custom mapping is set explicitly by the
    user rather than derived from a fixed table.
    """
    mapping = _PRESET_MAPPING.get(preset)
    if mapping is None:
        raise ValueError(f"{preset} has no fixed mapping; set languages explicitly")
    return mapping


@dataclass
class SourceConfig:
    """Per-source (microphone/loopback) device selection and language mapping."""

    source: StreamSource
    enabled: bool = True
    device_index: int | None = None
    device_name: str = ""
    source_language: Language = Language.VIETNAMESE
    target_language: Language = Language.JAPANESE


@dataclass
class CaptionEntry:
    """One utterance's current display state in the caption timeline.

    Mirrors ``docs/PROTOCOL.md``'s event fields plus display-only derived
    state (``retryable``/``error_message``). ``display_text`` is what a
    simple view should render for the transcription line; translation is
    rendered separately below it.
    """

    utterance_id: str
    stream_id: str
    source_language: Language
    source: StreamSource | None = None
    target_language: Language | None = None
    revision: int = 0
    stable_text: str = ""
    unstable_text: str = ""
    is_final: bool = False
    final_reason: FinalReason | None = None
    transcription: str = ""
    translation: str | None = None
    translation_status: TranslationStatus | None = None
    error_message: str | None = None
    retryable: bool = False
    timestamp: str = ""

    @property
    def display_text(self) -> str:
        """The transcription line: final text once final, else stable+unstable."""
        if self.is_final:
            return self.transcription
        return self.stable_text + self.unstable_text


class CaptionTimeline:
    """Ordered utterance entries keyed by utterance ID.

    Idempotent by ``(utterance_id, revision)``: a partial with a revision at
    or below the currently-applied one is ignored (docs/PROTOCOL.md:
    "client ignores revisions less than or equal to the currently applied
    revision"). A final event is always authoritative and replaces any
    partial in place regardless of revision; a late partial arriving after
    a final for the same utterance is ignored so it cannot resurrect a
    stale hint.
    """

    def __init__(self) -> None:
        self._order: list[str] = []
        self._entries: dict[str, CaptionEntry] = {}

    def __len__(self) -> int:
        return len(self._order)

    def entries(self) -> list[CaptionEntry]:
        """Entries in utterance-start (insertion) order."""
        return [self._entries[uid] for uid in self._order]

    def get(self, utterance_id: str) -> CaptionEntry | None:
        return self._entries.get(utterance_id)

    def apply_partial(self, event: TranscriptionPartial) -> CaptionEntry | None:
        existing = self._entries.get(event.utterance_id)
        if existing is not None and existing.is_final:
            return None
        if existing is not None and event.revision <= existing.revision:
            return None
        entry = existing
        if entry is None:
            entry = CaptionEntry(
                utterance_id=event.utterance_id,
                stream_id=event.stream_id,
                source_language=event.source_language,
            )
            self._order.append(event.utterance_id)
            self._entries[event.utterance_id] = entry
        entry.revision = event.revision
        entry.stable_text = event.stable_text
        entry.unstable_text = event.unstable_text
        entry.source_language = event.source_language
        entry.timestamp = event.timestamp.isoformat()
        return entry

    def apply_final(self, event: UtteranceFinal) -> CaptionEntry:
        entry = self._entries.get(event.utterance_id)
        if entry is None:
            entry = CaptionEntry(
                utterance_id=event.utterance_id,
                stream_id=event.stream_id,
                source_language=event.source_language,
            )
            self._order.append(event.utterance_id)
            self._entries[event.utterance_id] = entry
        entry.revision = event.revision
        entry.is_final = True
        entry.final_reason = event.final_reason
        entry.transcription = event.transcription
        entry.translation = event.translation
        entry.translation_status = event.translation_status
        entry.source = event.source
        entry.source_language = event.source_language
        entry.target_language = event.target_language
        entry.stable_text = event.transcription
        entry.unstable_text = ""
        entry.timestamp = event.timestamp.isoformat()
        entry.error_message = None
        entry.retryable = event.translation_status is TranslationStatus.FAILED
        return entry

    def apply_translation_update(self, event: TranslationUpdated) -> CaptionEntry | None:
        entry = self._entries.get(event.utterance_id)
        if entry is None:
            return None
        entry.translation = event.translation
        entry.translation_status = event.translation_status
        entry.retryable = event.translation_status is TranslationStatus.FAILED
        entry.timestamp = event.timestamp.isoformat()
        return entry

    def apply_error(self, event: ErrorEvent) -> CaptionEntry | None:
        if event.utterance_id is None:
            return None
        entry = self._entries.get(event.utterance_id)
        if entry is None:
            return None
        entry.error_message = event.message
        entry.retryable = event.retryable
        return entry


class ClientViewModel:
    """Top-level, Qt-independent client state.

    Owns connection state, per-source device/language configuration and the
    caption timeline. This class does no locking or threading of its own:
    it is meant to be mutated only from one thread at a time (the Qt main
    thread, after a signal-based handoff -- see
    ``client/ui/main_window.py``'s cross-thread bridge).
    """

    def __init__(self) -> None:
        self.connection_state: ConnectionState = ConnectionState.DISCONNECTED
        self.input_devices: list[DeviceInfo] = []
        self.loopback_devices: list[DeviceInfo] = []
        self.sources: dict[StreamSource, SourceConfig] = {
            StreamSource.MICROPHONE: SourceConfig(source=StreamSource.MICROPHONE),
            StreamSource.LOOPBACK: SourceConfig(source=StreamSource.LOOPBACK),
        }
        self.preset: LanguagePreset = LanguagePreset.VIETNAMESE_SIDE
        self.timeline = CaptionTimeline()
        self._stream_id_by_source: dict[StreamSource, str] = {}
        self.apply_preset(self.preset)

    # --- Connection ------------------------------------------------------
    def set_connection_state(self, state: ConnectionState) -> None:
        self.connection_state = state

    # --- Devices -----------------------------------------------------------
    def set_devices(
        self, *, input_devices: Sequence[DeviceInfo], loopback_devices: Sequence[DeviceInfo]
    ) -> None:
        self.input_devices = list(input_devices)
        self.loopback_devices = list(loopback_devices)

    def select_device(self, source: StreamSource, device: DeviceInfo | None) -> None:
        config = self.sources[source]
        if device is None:
            config.device_index = None
            config.device_name = ""
        else:
            config.device_index = device.index
            config.device_name = device.name

    def set_source_enabled(self, source: StreamSource, enabled: bool) -> None:
        self.sources[source].enabled = enabled

    # --- Language mapping ----------------------------------------------------
    def apply_preset(self, preset: LanguagePreset) -> None:
        self.preset = preset
        if preset is LanguagePreset.CUSTOM:
            return
        for source, (source_language, target_language) in resolve_preset_mapping(preset).items():
            self.sources[source].source_language = source_language
            self.sources[source].target_language = target_language

    def set_custom_languages(
        self, source: StreamSource, *, source_language: Language, target_language: Language
    ) -> None:
        self.preset = LanguagePreset.CUSTOM
        config = self.sources[source]
        config.source_language = source_language
        config.target_language = target_language

    # --- Settings persistence -------------------------------------------------
    def apply_persisted_settings(self, settings: PersistedSettings) -> None:
        """Restore device selection, enabled flags and language mapping."""
        try:
            preset = LanguagePreset(settings.preset)
        except ValueError:
            preset = LanguagePreset.CUSTOM
        if preset is LanguagePreset.CUSTOM:
            self.preset = preset
        else:
            self.apply_preset(preset)

        for source, persisted in (
            (StreamSource.MICROPHONE, settings.microphone),
            (StreamSource.LOOPBACK, settings.loopback),
        ):
            config = self.sources[source]
            config.enabled = persisted.enabled
            config.device_index = persisted.device_index
            config.device_name = persisted.device_name
            if preset is LanguagePreset.CUSTOM:
                try:
                    config.source_language = Language(persisted.source_language)
                    config.target_language = Language(persisted.target_language)
                except ValueError:
                    pass  # keep the dataclass defaults for an unrecognized value

    def to_persisted_settings(self) -> PersistedSettings:
        """Snapshot the current, persistable subset of state."""

        def _persist(source: StreamSource) -> PersistedSourceSettings:
            config = self.sources[source]
            return PersistedSourceSettings(
                enabled=config.enabled,
                device_index=config.device_index,
                device_name=config.device_name,
                source_language=config.source_language.value,
                target_language=config.target_language.value,
            )

        return PersistedSettings(
            preset=self.preset.value,
            microphone=_persist(StreamSource.MICROPHONE),
            loopback=_persist(StreamSource.LOOPBACK),
        )

    # --- Stream registration (for display attribution only) ------------------
    def register_stream(self, source: StreamSource, stream_id: str) -> None:
        """Remember which ``stream_id`` corresponds to which source.

        Used to backfill a caption entry's ``source`` before its first
        final event arrives (partial events do not carry ``source``).
        """
        self._stream_id_by_source[source] = stream_id

    def source_for_stream(self, stream_id: str) -> StreamSource | None:
        for source, sid in self._stream_id_by_source.items():
            if sid == stream_id:
                return source
        return None

    # --- Inbound protocol events -----------------------------------------------
    def handle_event(self, event: InboundEvent) -> CaptionEntry | None:
        """Apply one incoming protocol event to the caption timeline."""
        entry: CaptionEntry | None
        if isinstance(event, TranscriptionPartial):
            entry = self.timeline.apply_partial(event)
        elif isinstance(event, UtteranceFinal):
            entry = self.timeline.apply_final(event)
        elif isinstance(event, TranslationUpdated):
            entry = self.timeline.apply_translation_update(event)
        else:
            entry = self.timeline.apply_error(event)
        if entry is not None and entry.source is None:
            entry.source = self.source_for_stream(entry.stream_id)
        return entry
