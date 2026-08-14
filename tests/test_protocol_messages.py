"""Tests for protocol JSON message schemas and doc-aligned examples."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from shared.protocol.enums import (
    Encoding,
    ErrorCode,
    EventType,
    FinalReason,
    Language,
    StreamSource,
    TranslationStatus,
)
from shared.protocol.messages import (
    AudioAck,
    ErrorEvent,
    LatencyInfo,
    SessionStart,
    StreamConfig,
    TranscriptionPartial,
    TranslationUpdated,
    UtteranceFinal,
)

TS = datetime(2026, 8, 10, 3, 45, 0, tzinfo=UTC)


def test_session_start_from_documented_example() -> None:
    payload = {
        "protocol_version": 1,
        "type": "session.start",
        "session_id": "meeting-20260810-001",
        "client_id": "client-vn-01",
        "timestamp": "2026-08-10T03:45:00.000Z",
        "streams": [
            {
                "stream_number": 1,
                "stream_id": "mic-01",
                "source": "microphone",
                "source_language": "vi",
                "target_language": "ja",
                "sample_rate": 16000,
                "channels": 1,
                "encoding": "pcm_s16le",
            },
            {
                "stream_number": 2,
                "stream_id": "loopback-01",
                "source": "loopback",
                "source_language": "ja",
                "target_language": "vi",
                "sample_rate": 16000,
                "channels": 1,
                "encoding": "pcm_s16le",
            },
        ],
    }
    msg = SessionStart.model_validate(payload)
    assert msg.type is EventType.SESSION_START
    assert len(msg.streams) == 2
    assert msg.streams[0].source is StreamSource.MICROPHONE
    assert msg.streams[1].source_language is Language.JAPANESE
    assert msg.streams[0].encoding is Encoding.PCM_S16LE


def test_timestamp_serializes_with_z_and_millis() -> None:
    ack = AudioAck(
        session_id="s",
        stream_id="loopback-01",
        last_contiguous_sequence=18420,
        timestamp=TS,
    )
    dumped = ack.model_dump(mode="json")
    assert dumped["timestamp"] == "2026-08-10T03:45:00.000Z"
    assert dumped["type"] == "audio.ack"


def test_partial_round_trip() -> None:
    partial = TranscriptionPartial(
        session_id="s",
        stream_id="loopback-01",
        utterance_id="utt-00081",
        revision=5,
        source_language=Language.JAPANESE,
        stable_text="stable",
        unstable_text="tail",
        display_text="stabletail",
        start_ms=128420,
        end_ms=130880,
        timestamp=TS,
    )
    restored = TranscriptionPartial.model_validate_json(partial.model_dump_json())
    assert restored == partial


def test_utterance_final_with_latency() -> None:
    final = UtteranceFinal(
        session_id="s",
        stream_id="loopback-01",
        utterance_id="utt-00081",
        revision=6,
        source=StreamSource.LOOPBACK,
        source_language=Language.JAPANESE,
        target_language=Language.VIETNAMESE,
        transcription="transcription text",
        translation="ban dich",
        translation_status=TranslationStatus.COMPLETED,
        start_ms=128420,
        end_ms=132700,
        final_reason=FinalReason.VAD_HARD_SILENCE,
        latency=LatencyInfo(
            asr_final_ms=610,
            translation_queue_ms=25,
            translation_ms=420,
            end_to_end_ms=1375,
        ),
        timestamp=TS,
    )
    dumped = final.model_dump(mode="json")
    assert dumped["final_reason"] == "vad_hard_silence"
    assert dumped["translation_status"] == "completed"
    assert dumped["latency"]["end_to_end_ms"] == 1375


def test_utterance_final_allows_missing_translation() -> None:
    final = UtteranceFinal(
        session_id="s",
        stream_id="mic-01",
        utterance_id="utt-1",
        revision=0,
        source=StreamSource.MICROPHONE,
        source_language=Language.VIETNAMESE,
        target_language=Language.JAPANESE,
        transcription="only transcription",
        translation=None,
        translation_status=TranslationStatus.FAILED,
        start_ms=0,
        end_ms=10,
        final_reason=FinalReason.MAX_UTTERANCE,
        timestamp=TS,
    )
    assert final.translation is None
    assert final.translation_status is TranslationStatus.FAILED


def test_translation_updated_and_error_events() -> None:
    updated = TranslationUpdated(
        session_id="s",
        stream_id="loopback-01",
        utterance_id="utt-00081",
        translation="ban dich moi",
        translation_status=TranslationStatus.COMPLETED,
        timestamp=TS,
    )
    assert updated.type is EventType.TRANSLATION_UPDATED

    err = ErrorEvent(
        session_id="s",
        code=ErrorCode.TRANSLATION_TIMEOUT,
        message="Translation did not complete within the configured timeout.",
        retryable=True,
        utterance_id="utt-00081",
        timestamp=TS,
    )
    dumped = err.model_dump(mode="json")
    assert dumped["code"] == "TRANSLATION_TIMEOUT"
    assert dumped["retryable"] is True


def test_stream_config_rejects_non_mono_and_wrong_rate() -> None:
    with pytest.raises(ValidationError):
        StreamConfig(
            stream_number=1,
            stream_id="mic-01",
            source=StreamSource.MICROPHONE,
            source_language=Language.VIETNAMESE,
            target_language=Language.JAPANESE,
            channels=2,
        )
    with pytest.raises(ValidationError):
        StreamConfig(
            stream_number=1,
            stream_id="mic-01",
            source=StreamSource.MICROPHONE,
            source_language=Language.VIETNAMESE,
            target_language=Language.JAPANESE,
            sample_rate=44100,
        )


def test_session_start_rejects_duplicate_stream_numbers() -> None:
    with pytest.raises(ValidationError):
        SessionStart(
            session_id="s",
            client_id="c",
            timestamp=TS,
            streams=[
                StreamConfig(
                    stream_number=1,
                    stream_id="a",
                    source=StreamSource.MICROPHONE,
                    source_language=Language.VIETNAMESE,
                    target_language=Language.JAPANESE,
                ),
                StreamConfig(
                    stream_number=1,
                    stream_id="b",
                    source=StreamSource.LOOPBACK,
                    source_language=Language.JAPANESE,
                    target_language=Language.VIETNAMESE,
                ),
            ],
        )


def test_partial_rejects_end_before_start() -> None:
    with pytest.raises(ValidationError):
        TranscriptionPartial(
            session_id="s",
            stream_id="x",
            utterance_id="u",
            revision=1,
            source_language=Language.JAPANESE,
            stable_text="a",
            unstable_text="b",
            display_text="ab",
            start_ms=100,
            end_ms=50,
            timestamp=TS,
        )


def test_extra_fields_forbidden() -> None:
    with pytest.raises(ValidationError):
        AudioAck.model_validate(
            {
                "session_id": "s",
                "stream_id": "x",
                "last_contiguous_sequence": 1,
                "timestamp": "2026-08-10T03:45:00.000Z",
                "unexpected": "field",
            }
        )
