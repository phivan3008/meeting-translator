"""Proves UtteranceOrchestrator is actually wired into the live WebSocket
gateway: real binary audio frames sent over ``client.websocket_connect``
produce real ``transcription.partial``/``utterance.final`` JSON events.

This is the first test to exercise audio-in -> caption-out over the real
transport rather than calling the orchestrator directly (contrast
``tests/test_e2e_mocked_pipeline.py``), closing the gap long documented in
``IMPLEMENTATION_STATUS.md``/``docs/FINAL_IMPLEMENTATION_REPORT.md`` as
"the one gap that matters most". Uses scripted ASR/translation/VAD
doubles -- no GPU, no model weights, no real network calls.
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi.testclient import TestClient

from server.app import create_app
from server.asr.fake import ScriptedAsrModel
from server.asr.types import TranscriptionResult
from server.translation.fake import ScriptedTranslationClient
from server.vad.fake import ScriptedVadModel
from shared.protocol.binary import encode_packet
from shared.protocol.enums import EventType, Language, StreamSource
from shared.protocol.messages import SessionStart, StreamConfig
from shared.settings import Settings

FRAME_MS = 20
FRAME_BYTES = FRAME_MS * 32  # mono 16 kHz PCM S16LE: 32 bytes/ms
SPEECH_SAMPLE = bytes([1]) * FRAME_BYTES
SILENCE_SAMPLE = bytes([0]) * FRAME_BYTES


def _settings() -> Settings:
    return Settings(
        _env_file=None,  # type: ignore[call-arg]
        audio_frame_ms=FRAME_MS,
        vad_threshold=0.5,
        vad_speech_start_ms=40,
        vad_min_speech_ms=60,
        vad_soft_silence_ms=60,
        vad_hard_silence_ms=160,
        vad_speech_pad_before_ms=40,
        vad_speech_pad_after_ms=40,
        vad_max_utterance_ms=5000,
        # Partial-decode timing is real wall-clock elapsed time in the
        # live gateway (unlike the synthetic, lockstep-driven now_ms the
        # pure-orchestrator e2e/load tests control directly), so this is
        # set near-zero to avoid flakiness from test-execution speed.
        whisper_partial_interval_ms=1,
        completeness_enabled=False,
    )


def _session_start() -> SessionStart:
    return SessionStart(
        session_id="sess-wired-1",
        client_id="client-1",
        timestamp=datetime.now(UTC),
        streams=[
            StreamConfig(
                stream_number=1,
                stream_id="mic-01",
                source=StreamSource.MICROPHONE,
                source_language=Language.JAPANESE,
                target_language=Language.VIETNAMESE,
            ),
        ],
    )


def _frame(seq: int, payload: bytes) -> bytes:
    return encode_packet(
        stream_number=1,
        sequence_number=seq,
        client_timestamp_ms=1000 + seq * FRAME_MS,
        payload=payload,
    )


def test_real_frames_over_the_live_websocket_produce_partial_and_final_events() -> None:
    asr_model = ScriptedAsrModel(
        [TranscriptionResult(text="テストです。", language=Language.JAPANESE, duration_ms=400)]
    )
    translation_client = ScriptedTranslationClient(["Đây là một bài kiểm tra."])
    # 4 speech frames (>= min_speech_ms=60ms and speech_start_ms=40ms),
    # then 9 silence frames -- comfortably past hard_silence_ms=160ms (8
    # frames) regardless of whether semantic-complete fires first via
    # soft-silence, so exactly one utterance.final results either way.
    speech_flags = [True, True, True, True] + [False] * 9
    probabilities = [0.9 if is_speech else 0.1 for is_speech in speech_flags]

    app = create_app(
        _settings(),
        asr_model=asr_model,
        translation_client=translation_client,
        vad_model_factory=lambda: ScriptedVadModel(probabilities),
    )
    events: list[dict[str, object]] = []
    with TestClient(app).websocket_connect("/ws/stream") as ws:
        ws.send_text(_session_start().model_dump_json())
        for seq, is_speech in enumerate(speech_flags):
            ws.send_bytes(_frame(seq, SPEECH_SAMPLE if is_speech else SILENCE_SAMPLE))

        for _ in range(50):
            message = ws.receive_json()
            events.append(message)
            if message["type"] == EventType.UTTERANCE_FINAL.value:
                break

    partials = [e for e in events if e["type"] == EventType.TRANSCRIPTION_PARTIAL.value]
    finals = [e for e in events if e["type"] == EventType.UTTERANCE_FINAL.value]

    assert len(finals) == 1
    assert finals[0]["transcription"] == "テストです。"
    assert finals[0]["translation"] == "Đây là một bài kiểm tra."
    assert len(partials) >= 1
