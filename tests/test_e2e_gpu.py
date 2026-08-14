"""Optional GPU end-to-end test: the full pipeline against real backends.

Marked ``gpu`` and skipped by default (see ``tests/test_windows_audio.py``
for the identical skip-marker pattern used for hardware-dependent tests in
this project). Run manually on the GPU host, per
``docs/OPERATOR_RUNBOOK_SEED.md``/`MANUAL_ACTIONS.md`'s staged action for
this file:

    pytest -m gpu tests/test_e2e_gpu.py -v

Unlike ``tests/test_e2e_mocked_pipeline.py`` (which uses
``ScriptedAsrModel``/``ScriptedTranslationClient``), this constructs a real
``WhisperAsrModel`` (faster-whisper, requires a CUDA GPU and the
already-downloaded ``large-v3`` weights -- see ``GPU-ASR-004`` in
``USER_RESULTS.md``) and a real ``VllmTranslationClient`` (plain HTTP via
``httpx``, requires a running vLLM server -- see ``GPU-TRANSLATE-005``) and
drives them through the same ``UtteranceOrchestrator`` used everywhere else,
fed a locally-synthesized sine tone (no bundled or personal audio content,
consistent with ``GPU-ASR-004``'s precedent -- this test proves the
*wiring* executes against real hardware without exception, not
transcription accuracy, which ``GPU-ASR-005``/``GPU-TRANSLATE-007`` already
hardware-verified separately with real speech and native-language
judgment).

Configuration is read from the standard settings environment variables
(``WHISPER_MODEL``/``WHISPER_DEVICE``/``WHISPER_COMPUTE_TYPE``,
``VLLM_BASE_URL``/``VLLM_MODEL``) via ``shared.settings.Settings`` so this
test targets whatever the operator's ``.env`` on the GPU host already
points at -- no hardcoded host/path.
"""

from __future__ import annotations

import math
import struct
from importlib.util import find_spec

import pytest

from server.asr.types import AsrConfig
from server.orchestration.heuristics import HeuristicConfig
from server.orchestration.pipeline import UtteranceOrchestrator
from server.orchestration.types import CompletenessConfig
from server.translation.types import TranslationConfig
from server.vad.types import VadConfig
from shared.protocol.binary import decode_packet, encode_packet
from shared.protocol.enums import Language, StreamSource
from shared.protocol.messages import UtteranceFinal
from shared.settings import Settings

pytestmark = pytest.mark.gpu

_HAS_FASTER_WHISPER = find_spec("faster_whisper") is not None
requires_gpu_stack = pytest.mark.skipif(
    not _HAS_FASTER_WHISPER,
    reason="requires the 'gpu' extra (faster-whisper) installed on a CUDA host",
)

FRAME_MS = 20
SAMPLE_RATE = 16000
_FRAME_SAMPLES = SAMPLE_RATE * FRAME_MS // 1000


def _sine_frame(*, frame_index: int, frequency_hz: float = 220.0, amplitude: float = 0.2) -> bytes:
    """One frame of a continuous sine tone, encoded as mono 16 kHz PCM S16LE."""
    samples = []
    for i in range(_FRAME_SAMPLES):
        t = (frame_index * _FRAME_SAMPLES + i) / SAMPLE_RATE
        value = amplitude * math.sin(2 * math.pi * frequency_hz * t)
        samples.append(int(value * 32767))
    return struct.pack(f"<{_FRAME_SAMPLES}h", *samples)


def _silence_frame() -> bytes:
    return b"\x00\x00" * _FRAME_SAMPLES


@requires_gpu_stack
async def test_real_asr_and_translation_backends_through_the_orchestrator() -> None:
    from server.asr.whisper import WhisperAsrModel
    from server.translation.client import VllmTranslationClient

    settings = Settings()
    asr_config = AsrConfig.from_settings(settings)
    translation_config = TranslationConfig.from_settings(settings)

    asr_model = WhisperAsrModel(asr_config)
    translation_client = VllmTranslationClient(translation_config)

    published: list[object] = []

    async def publish(event: object) -> None:
        published.append(event)

    orchestrator = UtteranceOrchestrator(
        session_id="sess-gpu-e2e",
        vad_config=VadConfig.from_settings(settings),
        frame_ms=FRAME_MS,
        asr_config=asr_config,
        asr_model=asr_model,
        translation_config=translation_config,
        translation_client=translation_client,
        publish=publish,
        heuristic_config=HeuristicConfig(),
        completeness_config=CompletenessConfig(enabled=False),
        partial_interval_ms=FRAME_MS,
        asr_final_timeout_ms=30_000,  # real GPU decode is slower than the fake-backend default
    )
    orchestrator.add_stream(
        "mic-01",
        source=StreamSource.MICROPHONE,
        source_language=Language.JAPANESE,
        target_language=Language.VIETNAMESE,
    )

    try:
        # ~1.5s of tone (well past min_speech_ms) then enough silence to
        # cross hard_silence_ms and force finalization deterministically,
        # without depending on the heuristic recognizing any real words.
        now_ms = 0
        for i in range(75):
            packet = encode_packet(
                stream_number=1,
                sequence_number=i,
                client_timestamp_ms=now_ms,
                payload=_sine_frame(frame_index=i),
            )
            _, pcm = decode_packet(packet, max_payload_bytes=65536)
            await orchestrator.ingest_frame("mic-01", pcm, 0.9)
            now_ms += FRAME_MS
            await orchestrator.run_due_partial_decodes(now_ms=now_ms)

        for i in range(75, 75 + 60):  # 1.2s silence >= default hard_silence_ms (900ms)
            packet = encode_packet(
                stream_number=1,
                sequence_number=i,
                client_timestamp_ms=now_ms,
                payload=_silence_frame(),
            )
            _, pcm = decode_packet(packet, max_payload_bytes=65536)
            await orchestrator.ingest_frame("mic-01", pcm, 0.05)
            now_ms += FRAME_MS
            await orchestrator.run_due_partial_decodes(now_ms=now_ms)

        await orchestrator.wait_idle()
    finally:
        orchestrator.close()
        await translation_client.aclose()

    finals = [e for e in published if isinstance(e, UtteranceFinal)]
    assert len(finals) == 1, f"expected exactly one utterance.final, got {len(finals)}"
    final_event = finals[0]

    # Proves the real GPU decode actually ran (no exception, real latency
    # recorded) -- content accuracy on a synthetic tone is not asserted;
    # faster-whisper may return empty text, silence-hallucinated text, or
    # noise-shaped text for a pure sine tone, none of which is a wiring
    # failure. Real-speech accuracy was separately hardware-verified by
    # GPU-ASR-005/GPU-TRANSLATE-007 (see USER_RESULTS.md).
    assert final_event.latency is not None
    assert final_event.latency.asr_final_ms is not None
    assert final_event.latency.asr_final_ms >= 0
    print(f"transcription: {final_event.transcription!r}")
    print(f"translation_status: {final_event.translation_status!r}")
    print(f"translation: {final_event.translation!r}")
    if final_event.transcription.strip():
        # Non-empty ASR output means the translation leg was actually
        # attempted against the real vLLM server too.
        assert final_event.translation_status is not None
