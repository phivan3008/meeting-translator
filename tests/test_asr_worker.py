"""Tests for the final transcription service and finalization-to-event flow."""

from __future__ import annotations

import time

import pytest

from server.asr.errors import AsrCircuitOpenError, AsrOutOfMemoryError, AsrTimeoutError
from server.asr.fake import ScriptedAsrModel
from server.asr.types import AsrConfig, AsrRequest, TranscriptionResult
from server.asr.worker import FinalTranscriber, build_asr_error_event
from server.observability.metrics import create_metrics
from server.reliability.circuit_breaker import CircuitBreaker, CircuitState
from server.vad.types import Utterance
from shared.protocol.enums import (
    ErrorCode,
    FinalReason,
    Language,
    StreamSource,
    TranslationStatus,
)

CONFIG = AsrConfig(
    model="large-v3",
    device="cpu",
    compute_type="int8",
    final_beam_size=3,
    temperature=0.0,
    condition_on_previous_text=True,
)


def _utterance(text_marker: int = 1) -> Utterance:
    return Utterance(
        utterance_id="utt-00001",
        source=StreamSource.MICROPHONE,
        start_ms=0,
        end_ms=1000,
        speech_ms=800,
        final_reason=FinalReason.VAD_HARD_SILENCE,
        audio=bytes([text_marker]) * 3200,  # 100 ms
    )


def _result(text: str = "こんにちは") -> TranscriptionResult:
    return TranscriptionResult(text=text, language=Language.JAPANESE, duration_ms=100)


async def test_transcribe_utterance_uses_config_options() -> None:
    model = ScriptedAsrModel([_result()])
    transcriber = FinalTranscriber(model, CONFIG, timeout_ms=2000)
    try:
        result = await transcriber.transcribe_utterance(
            _utterance(), source_language=Language.JAPANESE, previous_text="prev"
        )
    finally:
        transcriber.close()

    assert result.text == "こんにちは"
    request: AsrRequest = model.requests[0]
    assert request.beam_size == CONFIG.final_beam_size
    assert request.temperature == CONFIG.temperature
    assert request.condition_on_previous_text is True
    assert request.previous_text == "prev"
    assert request.language is Language.JAPANESE


async def test_finalize_builds_event_without_translation() -> None:
    model = ScriptedAsrModel([_result("xin chào")])
    transcriber = FinalTranscriber(model, CONFIG, timeout_ms=2000)
    try:
        event = await transcriber.finalize(
            _utterance(),
            session_id="sess-1",
            stream_id="stream-1",
            source_language=Language.VIETNAMESE,
            target_language=Language.JAPANESE,
        )
    finally:
        transcriber.close()

    assert event.transcription == "xin chào"
    assert event.translation is None
    assert event.translation_status is TranslationStatus.PENDING
    assert event.final_reason is FinalReason.VAD_HARD_SILENCE
    assert event.source is StreamSource.MICROPHONE
    assert event.source_language is Language.VIETNAMESE
    assert event.target_language is Language.JAPANESE
    assert event.start_ms == 0
    assert event.end_ms == 1000
    assert event.revision == 0
    assert event.latency is not None
    assert event.latency.asr_final_ms is not None
    assert event.latency.asr_final_ms >= 0
    # The event must serialize cleanly to the JSON wire form.
    assert '"type":"utterance.final"' in event.model_dump_json()


async def test_timeout_maps_to_asr_timeout_error() -> None:
    class SlowModel:
        def transcribe(self, request: AsrRequest, /) -> TranscriptionResult:
            time.sleep(0.2)
            return _result()

    transcriber = FinalTranscriber(SlowModel(), CONFIG, timeout_ms=10)
    try:
        with pytest.raises(AsrTimeoutError):
            await transcriber.transcribe_utterance(_utterance(), source_language=Language.JAPANESE)
    finally:
        transcriber.close()


async def test_typed_asr_error_propagates_and_maps_to_event() -> None:
    model = ScriptedAsrModel([AsrOutOfMemoryError("CUDA out of memory")])
    transcriber = FinalTranscriber(model, CONFIG, timeout_ms=2000)
    try:
        with pytest.raises(AsrOutOfMemoryError) as excinfo:
            await transcriber.transcribe_utterance(_utterance(), source_language=Language.JAPANESE)
    finally:
        transcriber.close()

    event = build_asr_error_event(excinfo.value, session_id="sess-1", utterance_id="utt-00001")
    assert event.code is ErrorCode.ASR_FAILED
    assert event.retryable is True
    assert event.utterance_id == "utt-00001"


async def test_backend_exception_is_normalized() -> None:
    class BoomModel:
        def transcribe(self, request: AsrRequest, /) -> TranscriptionResult:
            raise RuntimeError("CUDA out of memory")

    transcriber = FinalTranscriber(BoomModel(), CONFIG, timeout_ms=2000)
    try:
        with pytest.raises(AsrOutOfMemoryError):
            await transcriber.transcribe_utterance(_utterance(), source_language=Language.JAPANESE)
    finally:
        transcriber.close()


def test_invalid_timeout_rejected() -> None:
    with pytest.raises(ValueError):
        FinalTranscriber(ScriptedAsrModel([_result()]), CONFIG, timeout_ms=0)


async def test_circuit_breaker_short_circuits_without_calling_model() -> None:
    model = ScriptedAsrModel([_result()])
    breaker = CircuitBreaker(failure_threshold=1, reset_timeout_ms=60_000)
    breaker.record_failure()  # trip before any request
    assert breaker.state is CircuitState.OPEN
    transcriber = FinalTranscriber(model, CONFIG, timeout_ms=2000, circuit_breaker=breaker)
    try:
        with pytest.raises(AsrCircuitOpenError) as excinfo:
            await transcriber.transcribe_utterance(_utterance(), source_language=Language.JAPANESE)
    finally:
        transcriber.close()

    assert excinfo.value.error_code is ErrorCode.OVERLOADED
    assert excinfo.value.retryable is True
    assert len(model.requests) == 0


async def test_circuit_breaker_records_success_and_failure() -> None:
    model = ScriptedAsrModel([AsrOutOfMemoryError("CUDA out of memory"), _result()])
    breaker = CircuitBreaker(failure_threshold=5, reset_timeout_ms=60_000)
    transcriber = FinalTranscriber(model, CONFIG, timeout_ms=2000, circuit_breaker=breaker)
    try:
        with pytest.raises(AsrOutOfMemoryError):
            await transcriber.transcribe_utterance(_utterance(), source_language=Language.JAPANESE)
        assert breaker.state is CircuitState.CLOSED  # below failure_threshold

        result = await transcriber.transcribe_utterance(
            _utterance(), source_language=Language.JAPANESE
        )
        assert result.text == "こんにちは"
        assert breaker.state is CircuitState.CLOSED
    finally:
        transcriber.close()


async def test_metrics_record_latency_and_circuit_state() -> None:
    model = ScriptedAsrModel([_result()])
    breaker = CircuitBreaker(failure_threshold=1, reset_timeout_ms=60_000)
    metrics = create_metrics()
    transcriber = FinalTranscriber(
        model, CONFIG, timeout_ms=2000, circuit_breaker=breaker, metrics=metrics
    )
    try:
        await transcriber.transcribe_utterance(_utterance(), source_language=Language.JAPANESE)
    finally:
        transcriber.close()

    sample_count = metrics.asr_latency_seconds.labels(stage="final")._sum.get()
    assert sample_count >= 0.0
    gauge_value = metrics.circuit_breaker_state.labels(backend="asr")._value.get()
    assert gauge_value == 0.0  # CLOSED
