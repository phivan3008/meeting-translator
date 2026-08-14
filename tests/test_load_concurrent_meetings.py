"""Load-test scenario: concurrent meetings, a translation-backend spike, and
synchronized utterance finalization.

Phase 08's own race-safety tests (``tests/test_orchestration_pipeline.py``)
prove exactly-once finalization *within* one session under a race between a
pending completeness decision and a competing hard-silence finalize. This
adds the dimension Phase 08 never exercised: **multiple independent
sessions** (real deployments run one ``UtteranceOrchestrator`` per session,
all in the same server process) driven **concurrently**, sharing one
translation backend and one process-wide ``Metrics`` instance -- exactly
the "concurrent meetings" scenario this phase's own required outcome names.

Deterministic and fast (no real sleep-based timing, no flakiness): frames
for every session are fed via ``asyncio.gather`` so their finalizations
land in the same event-loop tick window ("synchronized utterance
finalization"), and the shared fake translation client deliberately forces
a validation failure (a "queue spike" of retry work) for a subset of
sessions so the retry path is also exercised under concurrent load.
"""

from __future__ import annotations

import asyncio

from server.asr.fake import ScriptedAsrModel
from server.asr.types import AsrConfig, TranscriptionResult
from server.observability.metrics import Metrics, create_metrics
from server.orchestration.heuristics import HeuristicConfig
from server.orchestration.pipeline import UtteranceOrchestrator
from server.orchestration.types import CompletenessConfig
from server.translation.types import TranslationConfig
from server.vad.types import VadConfig
from shared.protocol.enums import FinalReason, Language, StreamSource, TranslationStatus
from shared.protocol.messages import TranslationUpdated, UtteranceFinal

FRAME_MS = 20
FRAME_BYTES = FRAME_MS * 32
SPEECH = bytes([1]) * FRAME_BYTES
SILENCE = bytes([0]) * FRAME_BYTES

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

# One tag per simulated meeting -- deliberately alphabetic-only (no digits,
# no hyphenated identifier-shaped tokens) so server/translation/validator.py's
# number/identifier-preservation check never fires and the fake translation
# output below doesn't need to echo the tag back verbatim.
SESSION_TAGS = ["alpha", "bravo", "charlie", "delta", "echo", "foxtrot"]
# Every other session's first translation attempt is forced to fail
# validation (a shared-backend "queue spike" of retry work).
FORCED_RETRY_TAGS = frozenset(SESSION_TAGS[::2])


class _SharedLoadTestTranslationClient:
    """One fake backend shared by every concurrent session's ``FinalTranslator``.

    Tracks real concurrent overlap (``max_active``) the same way
    ``tests/test_translation_worker.py::test_bounded_concurrency_is_respected``
    does for a single session, extended here across *multiple* sessions'
    independent ``FinalTranslator`` instances (each has its own semaphore;
    this fake is what lets the test observe whether the event loop actually
    interleaved their calls rather than accidentally serializing everything).
    """

    def __init__(self, *, force_retry_tags: frozenset[str]) -> None:
        self._pending_forced_failures = set(force_retry_tags)
        self.active = 0
        self.max_active = 0
        self.call_count = 0

    async def complete_chat(self, *, system_prompt: str, user_content: str, max_tokens: int) -> str:
        self.call_count += 1
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        try:
            await asyncio.sleep(0.005)  # simulate real backend request latency
            for tag in list(self._pending_forced_failures):
                if tag in user_content:
                    self._pending_forced_failures.discard(tag)
                    # A forbidden explanation prefix -> validator rejects
                    # this attempt, forcing FinalTranslator's retry path.
                    return f"Translation: forced spike failure for {tag}"
            return "ban dich hop le"  # plausible-looking, low-CJK-ratio Vietnamese-ish text
        finally:
            self.active -= 1


def _orchestrator(
    *, tag: str, translation_client: _SharedLoadTestTranslationClient, metrics: Metrics
) -> tuple[UtteranceOrchestrator, list[object]]:
    model = ScriptedAsrModel(
        [
            TranscriptionResult(
                text=f"utterance from session {tag}",
                language=Language.JAPANESE,
                duration_ms=400,
            )
        ]
    )
    published: list[object] = []

    async def publish(event: object) -> None:
        published.append(event)

    orchestrator = UtteranceOrchestrator(
        session_id=f"sess-{tag}",
        vad_config=VAD_CONFIG,
        frame_ms=FRAME_MS,
        asr_config=ASR_CONFIG,
        asr_model=model,
        translation_config=TRANSLATION_CONFIG,
        translation_client=translation_client,
        publish=publish,
        heuristic_config=HeuristicConfig(min_stable_speech_ms=0, max_unstable_tail_chars=50),
        completeness_config=CompletenessConfig(enabled=False),
        partial_interval_ms=FRAME_MS,
        metrics=metrics,
    )
    orchestrator.add_stream(
        "mic-01",
        source=StreamSource.MICROPHONE,
        source_language=Language.JAPANESE,
        target_language=Language.VIETNAMESE,
    )
    return orchestrator, published


async def _run_one_meeting(orchestrator: UtteranceOrchestrator) -> None:
    now_ms = 0
    # 4 speech frames confirm the utterance; hard silence forces
    # finalization deterministically without depending on the heuristic.
    for is_speech in [True, True, True, True] + [False] * 8:
        pcm = SPEECH if is_speech else SILENCE
        await orchestrator.ingest_frame("mic-01", pcm, 0.9 if is_speech else 0.1)
        now_ms += FRAME_MS
        await orchestrator.run_due_partial_decodes(now_ms=now_ms)
    await orchestrator.wait_idle()


def test_concurrent_meetings_finalize_independently_under_a_shared_backend_spike() -> None:
    async def run() -> tuple[
        dict[str, tuple[UtteranceOrchestrator, list[object]]],
        _SharedLoadTestTranslationClient,
        Metrics,
    ]:
        translation_client = _SharedLoadTestTranslationClient(force_retry_tags=FORCED_RETRY_TAGS)
        metrics = create_metrics()

        sessions: dict[str, tuple[UtteranceOrchestrator, list[object]]] = {
            tag: _orchestrator(tag=tag, translation_client=translation_client, metrics=metrics)
            for tag in SESSION_TAGS
        }

        try:
            # All meetings run concurrently -- their finalizations land in
            # the same event-loop tick window ("synchronized finalization").
            await asyncio.gather(*(_run_one_meeting(orch) for orch, _ in sessions.values()))
        finally:
            for orch, _ in sessions.values():
                orch.close()

        return sessions, translation_client, metrics

    sessions, translation_client, metrics = asyncio.run(run())

    # Real concurrent overlap actually happened -- the event loop did not
    # accidentally serialize every session's translation call.
    assert translation_client.max_active >= 2

    for tag, (_, published) in sessions.items():
        finals = [e for e in published if isinstance(e, UtteranceFinal)]
        # Exactly one utterance.final per session: no duplicate finalization
        # and no lost finalization under concurrent multi-session load.
        assert len(finals) == 1, f"session {tag}: expected 1 final, got {len(finals)}"
        final_event = finals[0]

        # No cross-session contamination: this session's final carries only
        # its own session/stream/utterance identifiers.
        assert final_event.session_id == f"sess-{tag}"
        assert final_event.stream_id == "mic-01"
        assert final_event.utterance_id.startswith("mic-01-")
        assert final_event.transcription == f"utterance from session {tag}"
        assert final_event.final_reason is FinalReason.VAD_HARD_SILENCE

        updates = [e for e in published if isinstance(e, TranslationUpdated)]
        if tag in FORCED_RETRY_TAGS:
            # The forced spike failure shows up as an initially-failed
            # translation, then a background retry succeeds and is
            # published as a separate translation.updated for this
            # session's utterance only.
            assert final_event.translation_status is TranslationStatus.FAILED
            assert len(updates) == 1
            assert updates[0].session_id == f"sess-{tag}"
            assert updates[0].utterance_id == final_event.utterance_id
            assert updates[0].translation_status is TranslationStatus.COMPLETED
        else:
            assert final_event.translation_status is TranslationStatus.COMPLETED
            assert final_event.translation == "ban dich hop le"
            assert updates == []

    # Counters accumulate correctly across every concurrent session sharing
    # one process-wide Metrics instance (unlike a Gauge, a Counter is safe
    # to share this way -- see the "Known limitations" note this load test
    # motivated in IMPLEMENTATION_STATUS.md about translation_queue_depth,
    # a Gauge, *not* being meaningful when shared across concurrent
    # sessions the way this Counter is).
    total_completed = metrics.translation_requests_total.labels(
        priority="final", status="completed"
    )._value.get()
    total_failed = metrics.translation_requests_total.labels(
        priority="final", status="failed"
    )._value.get()
    total_retry_completed = metrics.translation_requests_total.labels(
        priority="retry", status="completed"
    )._value.get()
    assert total_completed == len(SESSION_TAGS) - len(FORCED_RETRY_TAGS)
    assert total_failed == len(FORCED_RETRY_TAGS)
    assert total_retry_completed == len(FORCED_RETRY_TAGS)
