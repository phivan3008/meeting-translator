"""Tests for the Qt-independent client UI view model."""

from __future__ import annotations

from datetime import UTC, datetime

from client.audio.types import DeviceInfo
from client.transport.sender import ConnectionState
from client.ui.settings_store import PersistedSettings, PersistedSourceSettings
from client.ui.view_model import (
    CaptionTimeline,
    ClientViewModel,
    LanguagePreset,
    resolve_preset_mapping,
)
from shared.protocol.enums import FinalReason, Language, StreamSource, TranslationStatus
from shared.protocol.messages import (
    ErrorEvent,
    TranscriptionPartial,
    TranslationUpdated,
    UtteranceFinal,
)


def _partial(
    utterance_id: str = "utt-1", revision: int = 1, **overrides: object
) -> TranscriptionPartial:
    fields = {
        "session_id": "sess-1",
        "stream_id": "mic-01",
        "utterance_id": utterance_id,
        "revision": revision,
        "source_language": Language.JAPANESE,
        "stable_text": "来週の",
        "unstable_text": "リリース",
        "display_text": "来週のリリース",
        "start_ms": 0,
        "end_ms": 400,
        "timestamp": datetime.now(UTC),
    }
    fields.update(overrides)
    return TranscriptionPartial(**fields)  # type: ignore[arg-type]


def _final(utterance_id: str = "utt-1", revision: int = 2, **overrides: object) -> UtteranceFinal:
    fields = {
        "session_id": "sess-1",
        "stream_id": "mic-01",
        "utterance_id": utterance_id,
        "revision": revision,
        "source": StreamSource.MICROPHONE,
        "source_language": Language.JAPANESE,
        "target_language": Language.VIETNAMESE,
        "transcription": "来週のリリースです。",
        "translation": "Bản phát hành vào tuần tới.",
        "translation_status": TranslationStatus.COMPLETED,
        "start_ms": 0,
        "end_ms": 800,
        "final_reason": FinalReason.VAD_HARD_SILENCE,
        "timestamp": datetime.now(UTC),
    }
    fields.update(overrides)
    return UtteranceFinal(**fields)  # type: ignore[arg-type]


# --- LanguagePreset / resolve_preset_mapping ----------------------------------


def test_resolve_preset_mapping_vietnamese_side() -> None:
    mapping = resolve_preset_mapping(LanguagePreset.VIETNAMESE_SIDE)
    assert mapping[StreamSource.MICROPHONE] == (Language.VIETNAMESE, Language.JAPANESE)
    assert mapping[StreamSource.LOOPBACK] == (Language.JAPANESE, Language.VIETNAMESE)


def test_resolve_preset_mapping_japanese_side() -> None:
    mapping = resolve_preset_mapping(LanguagePreset.JAPANESE_SIDE)
    assert mapping[StreamSource.MICROPHONE] == (Language.JAPANESE, Language.VIETNAMESE)
    assert mapping[StreamSource.LOOPBACK] == (Language.VIETNAMESE, Language.JAPANESE)


def test_resolve_preset_mapping_custom_raises() -> None:
    import pytest

    with pytest.raises(ValueError):
        resolve_preset_mapping(LanguagePreset.CUSTOM)


# --- CaptionTimeline: partial idempotency/ordering ----------------------------


def test_apply_partial_creates_new_entry() -> None:
    timeline = CaptionTimeline()
    entry = timeline.apply_partial(_partial())
    assert entry is not None
    assert entry.utterance_id == "utt-1"
    assert entry.stable_text == "来週の"
    assert entry.unstable_text == "リリース"
    assert entry.is_final is False
    assert len(timeline) == 1


def test_apply_partial_stale_revision_ignored() -> None:
    timeline = CaptionTimeline()
    timeline.apply_partial(_partial(revision=3, stable_text="A"))
    result = timeline.apply_partial(_partial(revision=2, stable_text="B"))
    assert result is None
    assert timeline.get("utt-1").stable_text == "A"  # type: ignore[union-attr]


def test_apply_partial_equal_revision_ignored() -> None:
    timeline = CaptionTimeline()
    timeline.apply_partial(_partial(revision=2, stable_text="A"))
    result = timeline.apply_partial(_partial(revision=2, stable_text="B"))
    assert result is None
    assert timeline.get("utt-1").stable_text == "A"  # type: ignore[union-attr]


def test_apply_partial_higher_revision_replaces_in_place() -> None:
    timeline = CaptionTimeline()
    timeline.apply_partial(_partial(revision=1, stable_text="A"))
    result = timeline.apply_partial(_partial(revision=2, stable_text="A chào"))
    assert result is not None
    assert result.stable_text == "A chào"
    assert len(timeline) == 1  # updated in place, not appended


def test_apply_partial_after_final_is_ignored() -> None:
    timeline = CaptionTimeline()
    timeline.apply_final(_final(revision=5))
    result = timeline.apply_partial(_partial(revision=99))
    assert result is None
    entry = timeline.get("utt-1")
    assert entry is not None and entry.is_final is True


# --- CaptionTimeline: final replaces partial ----------------------------------


def test_apply_final_replaces_partial_and_is_bold_marker_set() -> None:
    timeline = CaptionTimeline()
    timeline.apply_partial(_partial(revision=1))
    entry = timeline.apply_final(_final(revision=2))
    assert entry.is_final is True
    assert entry.transcription == "来週のリリースです。"
    assert entry.translation == "Bản phát hành vào tuần tới."
    assert entry.unstable_text == ""
    assert entry.final_reason is FinalReason.VAD_HARD_SILENCE
    assert len(timeline) == 1


def test_apply_final_marks_retryable_when_translation_failed() -> None:
    timeline = CaptionTimeline()
    entry = timeline.apply_final(
        _final(translation=None, translation_status=TranslationStatus.FAILED)
    )
    assert entry.retryable is True
    assert entry.translation is None


# --- CaptionTimeline: translation.updated / error -----------------------------


def test_apply_translation_update_for_unknown_utterance_ignored() -> None:
    timeline = CaptionTimeline()
    update = TranslationUpdated(
        session_id="sess-1",
        stream_id="mic-01",
        utterance_id="nope",
        translation="x",
        translation_status=TranslationStatus.COMPLETED,
        timestamp=datetime.now(UTC),
    )
    assert timeline.apply_translation_update(update) is None


def test_apply_translation_update_replaces_translation_and_clears_retry() -> None:
    timeline = CaptionTimeline()
    timeline.apply_final(_final(translation=None, translation_status=TranslationStatus.FAILED))
    update = TranslationUpdated(
        session_id="sess-1",
        stream_id="mic-01",
        utterance_id="utt-1",
        translation="Đã dịch xong.",
        translation_status=TranslationStatus.COMPLETED,
        timestamp=datetime.now(UTC),
    )
    entry = timeline.apply_translation_update(update)
    assert entry is not None
    assert entry.translation == "Đã dịch xong."
    assert entry.retryable is False


def test_apply_error_sets_message_and_retryable() -> None:
    timeline = CaptionTimeline()
    timeline.apply_final(_final())
    error = ErrorEvent(
        session_id="sess-1",
        code="TRANSLATION_TIMEOUT",  # type: ignore[arg-type]
        message="Translation did not complete in time.",
        retryable=True,
        utterance_id="utt-1",
        timestamp=datetime.now(UTC),
    )
    entry = timeline.apply_error(error)
    assert entry is not None
    assert entry.error_message == "Translation did not complete in time."
    assert entry.retryable is True


def test_apply_error_without_utterance_id_ignored() -> None:
    timeline = CaptionTimeline()
    error = ErrorEvent(
        session_id="sess-1",
        code="INTERNAL_ERROR",  # type: ignore[arg-type]
        message="oops",
        retryable=False,
        utterance_id=None,
        timestamp=datetime.now(UTC),
    )
    assert timeline.apply_error(error) is None


# --- CaptionEntry.display_text -------------------------------------------------


def test_display_text_uses_stable_plus_unstable_before_final() -> None:
    timeline = CaptionTimeline()
    entry = timeline.apply_partial(_partial())
    assert entry is not None
    assert entry.display_text == "来週のリリース"


def test_display_text_uses_transcription_once_final() -> None:
    timeline = CaptionTimeline()
    entry = timeline.apply_final(_final())
    assert entry.display_text == "来週のリリースです。"


# --- ClientViewModel -----------------------------------------------------------


def test_view_model_defaults_to_vietnamese_side_preset() -> None:
    vm = ClientViewModel()
    mic = vm.sources[StreamSource.MICROPHONE]
    loopback = vm.sources[StreamSource.LOOPBACK]
    assert mic.source_language is Language.VIETNAMESE
    assert mic.target_language is Language.JAPANESE
    assert loopback.source_language is Language.JAPANESE
    assert loopback.target_language is Language.VIETNAMESE


def test_view_model_apply_preset_japanese_side() -> None:
    vm = ClientViewModel()
    vm.apply_preset(LanguagePreset.JAPANESE_SIDE)
    assert vm.sources[StreamSource.MICROPHONE].source_language is Language.JAPANESE
    assert vm.sources[StreamSource.LOOPBACK].target_language is Language.JAPANESE


def test_view_model_set_custom_languages_switches_preset_to_custom() -> None:
    vm = ClientViewModel()
    vm.set_custom_languages(
        StreamSource.MICROPHONE,
        source_language=Language.JAPANESE,
        target_language=Language.VIETNAMESE,
    )
    assert vm.preset is LanguagePreset.CUSTOM
    assert vm.sources[StreamSource.MICROPHONE].source_language is Language.JAPANESE
    # Loopback is untouched by a per-source custom change.
    assert (
        vm.sources[StreamSource.LOOPBACK].source_language is Language.JAPANESE
    )  # from default preset


def test_view_model_select_device_and_clear() -> None:
    vm = ClientViewModel()
    device = DeviceInfo(
        index=3, name="Mic A", max_input_channels=1, default_sample_rate=48000, is_loopback=False
    )
    vm.select_device(StreamSource.MICROPHONE, device)
    assert vm.sources[StreamSource.MICROPHONE].device_index == 3
    assert vm.sources[StreamSource.MICROPHONE].device_name == "Mic A"

    vm.select_device(StreamSource.MICROPHONE, None)
    assert vm.sources[StreamSource.MICROPHONE].device_index is None
    assert vm.sources[StreamSource.MICROPHONE].device_name == ""


def test_view_model_set_source_enabled() -> None:
    vm = ClientViewModel()
    vm.set_source_enabled(StreamSource.LOOPBACK, False)
    assert vm.sources[StreamSource.LOOPBACK].enabled is False


def test_view_model_set_devices() -> None:
    vm = ClientViewModel()
    inputs = [
        DeviceInfo(
            index=0, name="Mic", max_input_channels=1, default_sample_rate=16000, is_loopback=False
        )
    ]
    loopbacks = [
        DeviceInfo(
            index=1,
            name="Speaker (loopback)",
            max_input_channels=2,
            default_sample_rate=48000,
            is_loopback=True,
        )
    ]
    vm.set_devices(input_devices=inputs, loopback_devices=loopbacks)
    assert vm.input_devices == inputs
    assert vm.loopback_devices == loopbacks


def test_view_model_connection_state() -> None:
    vm = ClientViewModel()
    assert vm.connection_state is ConnectionState.DISCONNECTED
    vm.set_connection_state(ConnectionState.CONNECTED)
    assert vm.connection_state is ConnectionState.CONNECTED


def test_view_model_handle_event_backfills_source_from_registered_stream() -> None:
    vm = ClientViewModel()
    vm.register_stream(StreamSource.MICROPHONE, "mic-01")
    entry = vm.handle_event(_partial())
    assert entry is not None
    assert entry.source is StreamSource.MICROPHONE


def test_view_model_handle_event_dispatches_by_type() -> None:
    vm = ClientViewModel()
    partial_entry = vm.handle_event(_partial(revision=1))
    assert partial_entry is not None and partial_entry.is_final is False

    final_entry = vm.handle_event(_final(revision=2))
    assert final_entry is not None and final_entry.is_final is True


# --- Settings round-trip ---------------------------------------------------


def test_view_model_persisted_settings_round_trip() -> None:
    vm = ClientViewModel()
    vm.select_device(
        StreamSource.MICROPHONE,
        DeviceInfo(
            index=5,
            name="USB Mic",
            max_input_channels=1,
            default_sample_rate=16000,
            is_loopback=False,
        ),
    )
    vm.set_source_enabled(StreamSource.LOOPBACK, False)
    vm.apply_preset(LanguagePreset.JAPANESE_SIDE)

    persisted = vm.to_persisted_settings()

    restored = ClientViewModel()
    restored.apply_persisted_settings(persisted)

    assert restored.sources[StreamSource.MICROPHONE].device_index == 5
    assert restored.sources[StreamSource.MICROPHONE].device_name == "USB Mic"
    assert restored.sources[StreamSource.LOOPBACK].enabled is False
    assert restored.preset is LanguagePreset.JAPANESE_SIDE
    assert restored.sources[StreamSource.MICROPHONE].source_language is Language.JAPANESE


def test_view_model_apply_persisted_settings_custom_preset_restores_languages() -> None:
    persisted = PersistedSettings(
        preset="custom",
        microphone=PersistedSourceSettings(
            enabled=True,
            device_index=1,
            device_name="A",
            source_language="ja",
            target_language="vi",
        ),
        loopback=PersistedSourceSettings(
            enabled=True,
            device_index=2,
            device_name="B",
            source_language="vi",
            target_language="ja",
        ),
    )
    vm = ClientViewModel()
    vm.apply_persisted_settings(persisted)
    assert vm.preset is LanguagePreset.CUSTOM
    assert vm.sources[StreamSource.MICROPHONE].source_language is Language.JAPANESE
    assert vm.sources[StreamSource.LOOPBACK].target_language is Language.JAPANESE


def test_view_model_apply_persisted_settings_unknown_preset_falls_back_to_custom() -> None:
    persisted = PersistedSettings(preset="not-a-real-preset")
    vm = ClientViewModel()
    vm.apply_persisted_settings(persisted)
    assert vm.preset is LanguagePreset.CUSTOM
