"""End-to-end proof that real processing call sites never log raw content.

Unlike ``test_logging_redaction.py`` (which tests the redaction filter/regex
in isolation), this drives the actual production code paths -- final ASR,
final translation and the full finalization orchestrator -- with distinctive
marker text standing in for audio/transcript/prompt/translation content, and
asserts the marker never appears in anything logged by any logger anywhere
in the process during the run. This is CLAUDE.md's "no raw audio,
transcript, prompt or translation is logged by default" requirement, proven
against real call sites rather than assumed from the filter alone.
"""

from __future__ import annotations

import logging

from server.asr.fake import ScriptedAsrModel
from server.asr.types import AsrConfig, TranscriptionResult
from server.asr.worker import FinalTranscriber
from server.orchestration.pipeline import UtteranceOrchestrator
from server.translation.fake import ScriptedTranslationClient
from server.translation.types import TranslationConfig, TranslationRequest
from server.translation.worker import FinalTranslator
from server.vad.types import Utterance, VadConfig
from shared.logging import RedactionFilter
from shared.protocol.enums import FinalReason, Language, StreamSource

# Distinctive, never-otherwise-emitted markers standing in for sensitive
# content. If any of these appear in captured log output, something logged
# raw content it should not have.
TRANSCRIPT_MARKER = "zzqqmarkertranscriptcontentxyzzqq"
TRANSLATION_MARKER = "zzqqmarkertranslationcontentxyzzqq"

ASR_CONFIG = AsrConfig(model="large-v3", device="cpu", compute_type="int8")
TRANSLATION_CONFIG = TranslationConfig(
    base_url="http://vllm.local/v1", model="qwen3.6-27b-translate", timeout_ms=2000
)
VAD_CONFIG = VadConfig(
    threshold=0.5,
    speech_start_ms=40,
    min_speech_ms=60,
    soft_silence_ms=60,
    hard_silence_ms=160,
    speech_pad_before_ms=40,
    speech_pad_after_ms=40,
    max_utterance_ms=5000,
)


class _CapturingHandler(logging.Handler):
    """Collects every rendered record emitted anywhere during the test."""

    def __init__(self) -> None:
        super().__init__()
        self.rendered: list[str] = []
        self.addFilter(RedactionFilter())  # matches production wiring (shared.logging)

    def emit(self, record: logging.LogRecord) -> None:
        self.rendered.append(self.format(record))


def _attach_capturing_handler() -> _CapturingHandler:
    handler = _CapturingHandler()
    logging.getLogger().addHandler(handler)
    logging.getLogger().setLevel(logging.DEBUG)
    return handler


def _detach(handler: logging.Handler) -> None:
    logging.getLogger().removeHandler(handler)


def _assert_no_marker_leaked(handler: _CapturingHandler) -> None:
    combined = "\n".join(handler.rendered)
    assert TRANSCRIPT_MARKER not in combined
    assert TRANSLATION_MARKER not in combined


async def test_final_transcriber_does_not_log_transcript_content() -> None:
    handler = _attach_capturing_handler()
    try:
        model = ScriptedAsrModel(
            [
                TranscriptionResult(
                    text=TRANSCRIPT_MARKER, language=Language.JAPANESE, duration_ms=100
                )
            ]
        )
        transcriber = FinalTranscriber(model, ASR_CONFIG, timeout_ms=2000)
        try:
            utterance = Utterance(
                utterance_id="utt-1",
                source=StreamSource.MICROPHONE,
                start_ms=0,
                end_ms=1000,
                speech_ms=800,
                final_reason=FinalReason.VAD_HARD_SILENCE,
                audio=bytes([1]) * 3200,
            )
            event = await transcriber.finalize(
                utterance,
                session_id="sess-1",
                stream_id="mic-01",
                source_language=Language.JAPANESE,
                target_language=Language.VIETNAMESE,
            )
        finally:
            transcriber.close()
        assert event.transcription == TRANSCRIPT_MARKER  # sanity: marker really flowed through
    finally:
        _detach(handler)
    _assert_no_marker_leaked(handler)


async def test_final_translator_does_not_log_prompt_or_translation_content() -> None:
    handler = _attach_capturing_handler()
    try:
        client = ScriptedTranslationClient([TRANSLATION_MARKER])
        translator = FinalTranslator(client, TRANSLATION_CONFIG)
        request = TranslationRequest(
            text=TRANSCRIPT_MARKER,
            source_language=Language.JAPANESE,
            target_language=Language.VIETNAMESE,
        )
        outcome = await translator.translate_once(request)
        assert outcome.text == TRANSLATION_MARKER  # sanity: marker really flowed through
    finally:
        _detach(handler)
    _assert_no_marker_leaked(handler)


async def test_full_pipeline_finalize_and_translate_does_not_leak_content() -> None:
    handler = _attach_capturing_handler()
    try:
        model = ScriptedAsrModel(
            [
                TranscriptionResult(
                    text=TRANSCRIPT_MARKER, language=Language.JAPANESE, duration_ms=800
                )
            ]
        )
        client = ScriptedTranslationClient([TRANSLATION_MARKER])
        published: list[object] = []

        async def publish(event: object) -> None:
            published.append(event)

        orch = UtteranceOrchestrator(
            session_id="sess-1",
            vad_config=VAD_CONFIG,
            frame_ms=20,
            asr_config=ASR_CONFIG,
            asr_model=model,  # type: ignore[arg-type]
            translation_config=TRANSLATION_CONFIG,
            translation_client=client,  # type: ignore[arg-type]
            publish=publish,
            partial_interval_ms=20,
        )
        orch.add_stream(
            "mic-01",
            source=StreamSource.MICROPHONE,
            source_language=Language.JAPANESE,
            target_language=Language.VIETNAMESE,
        )
        try:
            frame = bytes([1]) * (20 * 32)
            silence = bytes([0]) * (20 * 32)
            t = 0
            for pcm, prob in [(frame, 0.9)] * 4 + [(silence, 0.1)] * 8:
                await orch.ingest_frame("mic-01", pcm, prob)
                t += 20
                await orch.run_due_partial_decodes(now_ms=t)
            await orch.wait_idle()
        finally:
            orch.close()

        assert len(published) >= 1  # sanity: the flow really ran end to end
    finally:
        _detach(handler)
    _assert_no_marker_leaked(handler)


def test_capturing_handler_itself_would_catch_a_leak() -> None:
    # Negative control: prove the harness actually detects a leak if one
    # occurs, so the "no marker found" assertions above are meaningful and
    # not silently vacuous (e.g. because nothing was captured at all).
    handler = _attach_capturing_handler()
    try:
        logging.getLogger("test.leak.control").info("leaked: %s", TRANSCRIPT_MARKER)
    finally:
        _detach(handler)
    combined = "\n".join(handler.rendered)
    assert TRANSCRIPT_MARKER in combined
