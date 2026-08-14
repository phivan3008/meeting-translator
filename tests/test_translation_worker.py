"""Tests for the final translation service (worker.py)."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest

from server.observability.metrics import create_metrics
from server.reliability.circuit_breaker import CircuitBreaker, CircuitState
from server.translation.errors import TranslationTimeoutError
from server.translation.fake import ScriptedTranslationClient
from server.translation.types import GlossaryEntry, TranslationConfig, TranslationRequest
from server.translation.worker import FinalTranslator, apply_translation, build_translation_updated
from shared.protocol.enums import FinalReason, Language, StreamSource, TranslationStatus
from shared.protocol.messages import UtteranceFinal

CONFIG = TranslationConfig(
    base_url="http://vllm.local/v1",
    model="qwen3.6-27b-translate",
    max_input_tokens=768,
    max_output_tokens=256,
    timeout_ms=2000,
    max_concurrency=8,
)


def _request(text: str = "来週のリリースについて確認したいです。") -> TranslationRequest:
    return TranslationRequest(
        text=text, source_language=Language.JAPANESE, target_language=Language.VIETNAMESE
    )


async def test_translate_once_success() -> None:
    client = ScriptedTranslationClient(["Tôi muốn xác nhận về đợt phát hành vào tuần tới."])
    translator = FinalTranslator(client, CONFIG)

    outcome = await translator.translate_once(_request())

    assert outcome.status is TranslationStatus.COMPLETED
    assert outcome.text == "Tôi muốn xác nhận về đợt phát hành vào tuần tới."
    assert outcome.issue is None
    assert client.call_count == 1


async def test_translate_once_validation_failure_does_not_auto_retry() -> None:
    client = ScriptedTranslationClient(["Translation: xin chào"])
    translator = FinalTranslator(client, CONFIG)

    outcome = await translator.translate_once(_request())

    assert outcome.status is TranslationStatus.FAILED
    assert outcome.text is None
    assert outcome.issue == "forbidden_prefix"
    assert client.call_count == 1  # translate_once never retries by itself


async def test_translate_once_backend_error_maps_to_failed() -> None:
    client = ScriptedTranslationClient([TranslationTimeoutError("vLLM timed out")])
    translator = FinalTranslator(client, CONFIG)

    outcome = await translator.translate_once(_request())

    assert outcome.status is TranslationStatus.FAILED
    assert outcome.issue == "timeout"


async def test_translate_once_enforces_wait_for_timeout() -> None:
    class SlowClient:
        async def complete_chat(
            self, *, system_prompt: str, user_content: str, max_tokens: int
        ) -> str:
            await asyncio.sleep(0.5)
            return "too late"

    fast_timeout_config = TranslationConfig(
        base_url=CONFIG.base_url,
        model=CONFIG.model,
        timeout_ms=10,
        max_concurrency=CONFIG.max_concurrency,
    )
    translator = FinalTranslator(SlowClient(), fast_timeout_config)

    outcome = await translator.translate_once(_request())

    assert outcome.status is TranslationStatus.FAILED
    assert outcome.issue == "timeout"


async def test_retry_uses_corrective_prompt_after_validation_failure() -> None:
    client = ScriptedTranslationClient(
        ["Translation: xin chào", "Tôi muốn xác nhận về đợt phát hành vào tuần tới."]
    )
    translator = FinalTranslator(client, CONFIG)

    first = await translator.translate_once(_request())
    assert first.status is TranslationStatus.FAILED

    second = await translator.retry(_request(), previous_issue=first.issue)

    assert second.status is TranslationStatus.COMPLETED
    assert client.call_count == 2
    assert "previous answer violated" in client.calls[1].system_prompt
    assert "previous answer violated" not in client.calls[0].system_prompt


async def test_retry_uses_original_prompt_after_timeout() -> None:
    client = ScriptedTranslationClient(
        [TranslationTimeoutError("timed out"), "Tôi muốn xác nhận về đợt phát hành vào tuần tới."]
    )
    translator = FinalTranslator(client, CONFIG)

    first = await translator.translate_once(_request())
    assert first.issue == "timeout"

    second = await translator.retry(_request(), previous_issue=first.issue)

    assert second.status is TranslationStatus.COMPLETED
    assert "previous answer violated" not in client.calls[1].system_prompt


async def test_bounded_concurrency_is_respected() -> None:
    active = 0
    max_active = 0
    lock = asyncio.Lock()

    class TrackingClient:
        async def complete_chat(
            self, *, system_prompt: str, user_content: str, max_tokens: int
        ) -> str:
            nonlocal active, max_active
            async with lock:
                active += 1
                max_active = max(max_active, active)
            await asyncio.sleep(0.05)
            async with lock:
                active -= 1
            return "Xin chào"

    limited_config = TranslationConfig(
        base_url=CONFIG.base_url, model=CONFIG.model, timeout_ms=2000, max_concurrency=2
    )
    translator = FinalTranslator(TrackingClient(), limited_config)

    await asyncio.gather(*(translator.translate_once(_request()) for _ in range(5)))

    assert max_active <= 2


async def test_glossary_and_context_reach_the_client() -> None:
    client = ScriptedTranslationClient(["Tôi muốn xác nhận."])
    translator = FinalTranslator(client, CONFIG)
    request = TranslationRequest(
        text="確認したいです。",
        source_language=Language.JAPANESE,
        target_language=Language.VIETNAMESE,
        glossary=(GlossaryEntry(term="確認", translation="xác nhận"),),
        context_sentences=("Trước đó.",),
    )

    await translator.translate_once(request)

    call = client.calls[0]
    assert "確認 -> xác nhận" in call.system_prompt
    assert "Trước đó." in call.user_content
    assert "確認したいです。" in call.user_content


def _final_event() -> UtteranceFinal:
    return UtteranceFinal(
        session_id="sess-1",
        stream_id="mic-01",
        utterance_id="utt-1",
        revision=1,
        source=StreamSource.MICROPHONE,
        source_language=Language.JAPANESE,
        target_language=Language.VIETNAMESE,
        transcription="来週のリリースについて確認したいです。",
        translation=None,
        translation_status=TranslationStatus.PENDING,
        start_ms=0,
        end_ms=1000,
        final_reason=FinalReason.VAD_HARD_SILENCE,
        timestamp=datetime.now(UTC),
    )


def test_apply_translation_returns_new_event_without_mutating_original() -> None:
    from server.translation.types import TranslationOutcome

    original = _final_event()
    outcome = TranslationOutcome(
        text="Tôi muốn xác nhận.", status=TranslationStatus.COMPLETED, issue=None
    )

    updated = apply_translation(original, outcome)

    assert original.translation is None
    assert original.translation_status is TranslationStatus.PENDING
    assert updated.translation == "Tôi muốn xác nhận."
    assert updated.translation_status is TranslationStatus.COMPLETED
    assert updated.utterance_id == original.utterance_id


def test_build_translation_updated_requires_completed_outcome() -> None:
    from server.translation.types import TranslationOutcome

    failed = TranslationOutcome(text=None, status=TranslationStatus.FAILED, issue="timeout")
    with pytest.raises(ValueError):
        build_translation_updated(
            session_id="s", stream_id="mic-01", utterance_id="utt-1", outcome=failed
        )


async def test_circuit_breaker_short_circuits_without_calling_client() -> None:
    client = ScriptedTranslationClient(["should never be used"])
    breaker = CircuitBreaker(failure_threshold=1, reset_timeout_ms=60_000)
    breaker.record_failure()  # trip it before any request
    assert breaker.state is CircuitState.OPEN
    translator = FinalTranslator(client, CONFIG, circuit_breaker=breaker)

    outcome = await translator.translate_once(_request())

    assert outcome.status is TranslationStatus.FAILED
    assert outcome.issue == "circuit_open"
    assert client.call_count == 0


async def test_circuit_breaker_records_success_and_failure() -> None:
    client = ScriptedTranslationClient(
        [TranslationTimeoutError("timed out"), "Tôi muốn xác nhận về đợt phát hành vào tuần tới."]
    )
    breaker = CircuitBreaker(failure_threshold=5, reset_timeout_ms=60_000)
    translator = FinalTranslator(client, CONFIG, circuit_breaker=breaker)

    first = await translator.translate_once(_request())
    assert first.issue == "timeout"
    assert breaker.state is CircuitState.CLOSED  # below failure_threshold

    second = await translator.translate_once(_request())
    assert second.status is TranslationStatus.COMPLETED
    assert breaker.state is CircuitState.CLOSED


async def test_metrics_are_recorded_for_completed_and_failed_outcomes() -> None:
    client = ScriptedTranslationClient(
        ["Translation: xin chào", "Tôi muốn xác nhận về đợt phát hành vào tuần tới."]
    )
    metrics = create_metrics()
    translator = FinalTranslator(client, CONFIG, metrics=metrics)

    await translator.translate_once(_request())
    await translator.retry(_request(), previous_issue="forbidden_prefix")

    failed_count = metrics.translation_requests_total.labels(
        priority="final", status="failed"
    )._value.get()
    completed_count = metrics.translation_requests_total.labels(
        priority="retry", status="completed"
    )._value.get()
    assert failed_count == 1
    assert completed_count == 1


async def test_metrics_record_circuit_open_without_latency_observation() -> None:
    client = ScriptedTranslationClient(["unused"])
    breaker = CircuitBreaker(failure_threshold=1, reset_timeout_ms=60_000)
    breaker.record_failure()
    metrics = create_metrics()
    translator = FinalTranslator(client, CONFIG, circuit_breaker=breaker, metrics=metrics)

    outcome = await translator.translate_once(_request())

    assert outcome.issue == "circuit_open"
    circuit_open_count = metrics.translation_requests_total.labels(
        priority="final", status="failed"
    )._value.get()
    assert circuit_open_count == 1
    gauge_value = metrics.circuit_breaker_state.labels(backend="translation")._value.get()
    assert gauge_value == 2.0  # OPEN


def test_build_translation_updated_builds_expected_event() -> None:
    from server.translation.types import TranslationOutcome

    outcome = TranslationOutcome(text="Đã dịch xong.", status=TranslationStatus.COMPLETED)
    event = build_translation_updated(
        session_id="sess-1", stream_id="mic-01", utterance_id="utt-1", outcome=outcome
    )
    assert event.translation == "Đã dịch xong."
    assert event.translation_status is TranslationStatus.COMPLETED
    assert event.utterance_id == "utt-1"
    assert '"type":"translation.updated"' in event.model_dump_json()
