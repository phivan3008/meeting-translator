"""End-to-end mocked test: audio packet -> VAD -> partial -> final ASR ->
translation -> final UI state.

Composes real production code from every layer of the documented pipeline
(``docs/ARCHITECTURE.md``'s "Processing pipeline") in one in-process test:

    binary audio packet (shared.protocol.binary)
    -> decoded PCM
    -> UtteranceOrchestrator (server.orchestration.pipeline): VAD state
       machine -> partial ASR -> final ASR -> translation
    -> published protocol events (transcription.partial / utterance.final /
       translation.updated)
    -> ClientViewModel.handle_event (client.ui.view_model): the same
       Qt-independent state layer client/ui/main_window.py renders from
    -> final caption/translation UI state

Only the ASR and translation *backends* are scripted fakes (``ScriptedAsrModel``/
``ScriptedTranslationClient``, the same fakes every prior phase's tests use) --
"mocked" per this phase's own required outcome. Everything else (packet
codec, VAD segmentation, stable-prefix partial logic, heuristic completeness,
translation retry, protocol event construction/validation, and the client
view-model's idempotency rules) is real, unmodified production code. This
does **not** exercise the live WebSocket gateway: ``UtteranceOrchestrator``
is still not wired into ``server/transport/gateway.py`` (a gap carried
forward since Phase 08 -- see ``IMPLEMENTATION_STATUS.md``'s "Known
limitations"), so this test constructs the orchestrator directly, the same
way every orchestration test since Phase 08 has.
"""

from __future__ import annotations

import asyncio

from client.ui.view_model import ClientViewModel
from server.asr.fake import ScriptedAsrModel
from server.asr.types import AsrConfig, TranscriptionResult, TranscriptionSegment
from server.orchestration.heuristics import HeuristicConfig
from server.orchestration.pipeline import UtteranceOrchestrator
from server.orchestration.types import CompletenessConfig
from server.translation.fake import ScriptedTranslationClient
from server.translation.types import TranslationConfig
from server.vad.types import VadConfig
from shared.protocol.binary import decode_packet, encode_packet
from shared.protocol.enums import FinalReason, Language, StreamSource
from shared.protocol.messages import TranscriptionPartial, TranslationUpdated, UtteranceFinal

FRAME_MS = 20
FRAME_BYTES = FRAME_MS * 32  # mono 16 kHz S16LE
SPEECH_SAMPLE = bytes([1]) * FRAME_BYTES
SILENCE_SAMPLE = bytes([0]) * FRAME_BYTES

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
ASR_CONFIG = AsrConfig(model="large-v3", device="cpu", compute_type="int8")
TRANSLATION_CONFIG = TranslationConfig(
    base_url="http://vllm.local/v1", model="qwen3.6-27b-translate", timeout_ms=2000
)
# Relaxed so a short test utterance can reach a definite-complete heuristic
# verdict without needing 300ms of confirmed speech (see
# tests/test_orchestration_pipeline.py's identical rationale).
FAST_HEURISTIC = HeuristicConfig(min_stable_speech_ms=0, max_unstable_tail_chars=50)


def _encode_audio_packet(*, stream_number: int, sequence_number: int, is_speech: bool) -> bytes:
    """Build a real wire-format binary audio packet (header + PCM payload)."""
    payload = SPEECH_SAMPLE if is_speech else SILENCE_SAMPLE
    return encode_packet(
        stream_number=stream_number,
        sequence_number=sequence_number,
        client_timestamp_ms=1000 + sequence_number * FRAME_MS,
        payload=payload,
    )


def test_audio_packet_through_vad_asr_translation_to_final_ui_state() -> None:
    async def run() -> tuple[ClientViewModel, list[object]]:
        # A single Japanese utterance with sentence-final punctuation, so the
        # deterministic heuristic (no completeness-model round trip needed)
        # judges it complete once two consecutive partial decodes agree.
        model = ScriptedAsrModel(
            [
                TranscriptionResult(
                    text="テストです。",
                    language=Language.JAPANESE,
                    duration_ms=400,
                    segments=(TranscriptionSegment(text="テストです。", start_ms=0, end_ms=400),),
                )
            ]
        )
        client = ScriptedTranslationClient(["Đây là một bài kiểm tra."])

        published: list[object] = []

        async def publish(event: object) -> None:
            published.append(event)

        orchestrator = UtteranceOrchestrator(
            session_id="sess-e2e-1",
            vad_config=VAD_CONFIG,
            frame_ms=FRAME_MS,
            asr_config=ASR_CONFIG,
            asr_model=model,
            translation_config=TRANSLATION_CONFIG,
            translation_client=client,
            publish=publish,
            heuristic_config=FAST_HEURISTIC,
            completeness_config=CompletenessConfig(enabled=False),
            partial_interval_ms=FRAME_MS,
        )
        orchestrator.add_stream(
            "mic-01",
            source=StreamSource.MICROPHONE,
            source_language=Language.JAPANESE,
            target_language=Language.VIETNAMESE,
        )

        # 4 speech frames confirm the utterance and let >=2 partial decodes
        # see the same content (committing stable text), then just enough
        # silence to cross soft_silence_ms and trigger the semantic-complete
        # decision -- well short of hard_silence_ms.
        speech_flags = [True, True, True, True] + [False] * 3
        now_ms = 0
        try:
            for seq, is_speech in enumerate(speech_flags):
                # The "audio packet" step: encode a real binary frame, send
                # it "over the wire", then decode it back -- the orchestrator
                # only ever sees the decoded PCM payload, exactly as the
                # (not-yet-wired) gateway would hand it off after its own
                # jitter-buffer release.
                packet = _encode_audio_packet(
                    stream_number=1, sequence_number=seq, is_speech=is_speech
                )
                header, pcm = decode_packet(packet, max_payload_bytes=65536)
                assert header.stream_number == 1
                assert len(pcm) == FRAME_BYTES

                await orchestrator.ingest_frame("mic-01", pcm, 0.9 if is_speech else 0.1)
                now_ms += FRAME_MS
                await orchestrator.run_due_partial_decodes(now_ms=now_ms)
            await orchestrator.wait_idle()
        finally:
            orchestrator.close()

        # Feed every published protocol event into the same Qt-independent
        # view-model client/ui/main_window.py renders from.
        view_model = ClientViewModel()
        view_model.register_stream(StreamSource.MICROPHONE, "mic-01")
        for event in published:
            assert isinstance(event, TranscriptionPartial | UtteranceFinal | TranslationUpdated)
            view_model.handle_event(event)

        return view_model, published

    view_model, published = asyncio.run(run())

    # At least one partial hint was rendered before the final replaced it
    # (proves the partial-ASR/stable-prefix stage actually ran, not just
    # the final one).
    assert any(isinstance(event, TranscriptionPartial) for event in published)

    entries = view_model.timeline.entries()
    assert len(entries) == 1
    entry = entries[0]
    assert entry.is_final is True
    assert entry.final_reason is FinalReason.SEMANTIC_COMPLETE
    assert entry.transcription == "テストです。"
    assert entry.translation == "Đây là một bài kiểm tra."
    assert entry.unstable_text == ""  # a final entry has no dangling partial hint
    assert entry.source is StreamSource.MICROPHONE  # backfilled via register_stream
    assert entry.error_message is None
    assert entry.retryable is False


def test_translation_failure_still_publishes_final_transcription_to_ui() -> None:
    """docs/ACCEPTANCE_CRITERIA.md: "Translation failure still publishes
    final transcription." -- proven through the same encode/decode/orchestrate
    /view-model chain, not just at the worker level (already covered by
    tests/test_orchestration_pipeline.py::test_translation_retry_publishes_translation_updated).
    """

    async def run() -> ClientViewModel:
        model = ScriptedAsrModel(
            [
                TranscriptionResult(
                    text="no punctuation here", language=Language.JAPANESE, duration_ms=400
                )
            ]
        )
        # First attempt fails validation (forbidden explanation prefix); the
        # background retry then succeeds.
        client = ScriptedTranslationClient(["Translation: xin chào", "Xin chào."])
        published: list[object] = []

        async def publish(event: object) -> None:
            published.append(event)

        orchestrator = UtteranceOrchestrator(
            session_id="sess-e2e-2",
            vad_config=VAD_CONFIG,
            frame_ms=FRAME_MS,
            asr_config=ASR_CONFIG,
            asr_model=model,
            translation_config=TRANSLATION_CONFIG,
            translation_client=client,
            publish=publish,
            heuristic_config=FAST_HEURISTIC,
            completeness_config=CompletenessConfig(enabled=False),
            partial_interval_ms=FRAME_MS,
        )
        orchestrator.add_stream(
            "mic-01",
            source=StreamSource.MICROPHONE,
            source_language=Language.JAPANESE,
            target_language=Language.VIETNAMESE,
        )

        now_ms = 0
        try:
            for seq, is_speech in enumerate([True, True, True, True] + [False] * 8):
                packet = _encode_audio_packet(
                    stream_number=1, sequence_number=seq, is_speech=is_speech
                )
                _, pcm = decode_packet(packet, max_payload_bytes=65536)
                await orchestrator.ingest_frame("mic-01", pcm, 0.9 if is_speech else 0.1)
                now_ms += FRAME_MS
                await orchestrator.run_due_partial_decodes(now_ms=now_ms)
            await orchestrator.wait_idle()
        finally:
            orchestrator.close()

        view_model = ClientViewModel()
        view_model.register_stream(StreamSource.MICROPHONE, "mic-01")
        for event in published:
            view_model.handle_event(event)  # type: ignore[arg-type]
        return view_model

    view_model = asyncio.run(run())

    entries = view_model.timeline.entries()
    assert len(entries) == 1
    entry = entries[0]
    # The final transcription was published immediately even though the
    # first translation attempt failed -- never suppressed.
    assert entry.is_final is True
    assert entry.transcription == "no punctuation here"
    # The background retry succeeded and updated the UI's translation state
    # via a translation.updated event, without a second caption entry.
    assert entry.translation == "Xin chào."
    assert entry.retryable is False
