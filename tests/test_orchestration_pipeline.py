"""Integration tests for the full finalization orchestrator.

Covers the phase's required scenarios: pause-resume, semantic completion,
hard silence, completeness timeout, concurrent streams and race-safe
(exactly-once) finalization.
"""

from __future__ import annotations

import asyncio

from server.asr.fake import ScriptedAsrModel
from server.asr.types import AsrConfig, TranscriptionResult, TranscriptionSegment
from server.observability.correlation import current
from server.observability.metrics import create_metrics
from server.orchestration.heuristics import HeuristicConfig
from server.orchestration.pipeline import UtteranceOrchestrator
from server.orchestration.types import CompletenessConfig
from server.translation.fake import ScriptedTranslationClient
from server.translation.types import TranslationConfig
from server.vad.types import VadConfig
from shared.protocol.enums import FinalReason, Language, StreamSource
from shared.protocol.messages import TranslationUpdated, UtteranceFinal

FRAME_MS = 20
FRAME_BYTES = FRAME_MS * 32  # mono 16 kHz S16LE
SPEECH = bytes([1]) * FRAME_BYTES
SILENCE = bytes([0]) * FRAME_BYTES

VAD_CONFIG = VadConfig(
    threshold=0.5,
    speech_start_ms=40,  # 2 frames
    min_speech_ms=60,  # 3 frames
    soft_silence_ms=60,  # 3 frames
    hard_silence_ms=160,  # 8 frames
    speech_pad_before_ms=40,
    speech_pad_after_ms=40,
    max_utterance_ms=5000,
)

ASR_CONFIG = AsrConfig(model="large-v3", device="cpu", compute_type="int8")
TRANSLATION_CONFIG = TranslationConfig(
    base_url="http://vllm.local/v1", model="qwen3.6-27b-translate", timeout_ms=2000
)
# The default HeuristicConfig requires 300ms of confirmed speech before a
# punctuation/ending-signal match counts as definite-complete; these tests
# use much shorter utterances, so relax that threshold to 0 (the min-speech
# -duration gating itself is covered by test_orchestration_heuristics.py).
FAST_HEURISTIC = HeuristicConfig(min_stable_speech_ms=0, max_unstable_tail_chars=50)


def _result(text: str, language: Language, *, end_ms: int = 400) -> TranscriptionResult:
    segment = TranscriptionSegment(text=text, start_ms=0, end_ms=end_ms)
    return TranscriptionResult(
        text=text, language=language, duration_ms=end_ms, segments=(segment,)
    )


class _EventSink:
    """Collects every published event in order, async-callable."""

    def __init__(self) -> None:
        self.events: list[object] = []

    async def __call__(self, event: object) -> None:
        self.events.append(event)

    def finals(self) -> list[UtteranceFinal]:
        return [e for e in self.events if isinstance(e, UtteranceFinal)]

    def updates(self) -> list[TranslationUpdated]:
        return [e for e in self.events if isinstance(e, TranslationUpdated)]


def _orchestrator(
    asr_model: object,
    translation_client: object,
    publish: _EventSink,
    *,
    heuristic_config: HeuristicConfig | None = None,
    completeness_config: CompletenessConfig | None = None,
    vad_config: VadConfig = VAD_CONFIG,
    metrics: object | None = None,
) -> UtteranceOrchestrator:
    return UtteranceOrchestrator(
        session_id="sess-1",
        vad_config=vad_config,
        frame_ms=FRAME_MS,
        asr_config=ASR_CONFIG,
        asr_model=asr_model,  # type: ignore[arg-type]
        translation_config=TRANSLATION_CONFIG,
        translation_client=translation_client,  # type: ignore[arg-type]
        publish=publish,
        heuristic_config=heuristic_config or FAST_HEURISTIC,
        completeness_config=completeness_config or CompletenessConfig(enabled=False),
        partial_interval_ms=FRAME_MS,
        metrics=metrics,  # type: ignore[arg-type]
    )


async def _feed(
    orchestrator: UtteranceOrchestrator,
    stream_id: str,
    probs: list[float],
    *,
    t0: int = 0,
) -> int:
    """Feed frames (and run due partial decodes) for one stream; return the new clock.

    ``run_due_partial_decodes`` performs a real executor round trip, which is
    a genuine suspension point that lets other scheduled background tasks
    run interleaved. That is fine (even desirable) for most scenarios, but
    tests that need to control exactly when a pending background decision
    is allowed to run should use :func:`_feed_no_partial` instead.
    """
    t = t0
    for prob in probs:
        pcm = SPEECH if prob >= VAD_CONFIG.threshold else SILENCE
        await orchestrator.ingest_frame(stream_id, pcm, prob)
        t += FRAME_MS
        await orchestrator.run_due_partial_decodes(now_ms=t)
    return t


async def _feed_no_partial(
    orchestrator: UtteranceOrchestrator,
    stream_id: str,
    probs: list[float],
    *,
    t0: int = 0,
) -> int:
    """Feed frames without ever running a partial decode.

    ``ingest_frame`` alone has no genuine suspension point (VAD/bookkeeping
    is all synchronous), so a run of calls to this helper is guaranteed not
    to yield control to the event loop -- letting a test drive the VAD
    machine through several transitions (e.g. soft silence *and* hard
    silence) without any chance for an already-scheduled background task to
    run in between.
    """
    t = t0
    for prob in probs:
        pcm = SPEECH if prob >= VAD_CONFIG.threshold else SILENCE
        await orchestrator.ingest_frame(stream_id, pcm, prob)
        t += FRAME_MS
    return t


def test_hard_silence_finalizes_without_completeness_check() -> None:
    async def run() -> None:
        model = ScriptedAsrModel([_result("no punctuation here", Language.JAPANESE)])
        client = ScriptedTranslationClient(["OK"])
        sink = _EventSink()
        orch = _orchestrator(model, client, sink)
        orch.add_stream(
            "mic-01",
            source=StreamSource.MICROPHONE,
            source_language=Language.JAPANESE,
            target_language=Language.VIETNAMESE,
        )
        try:
            # 4 speech frames (>= min_speech_ms=60ms) confirm the utterance,
            # then 8 silence frames (>= hard_silence_ms=160ms) hard-finalize
            # it inside the VAD machine itself -- no semantic-complete
            # decision should fire (no punctuation/ending signal present).
            await _feed(orch, "mic-01", [0.9, 0.9, 0.9, 0.9] + [0.1] * 8)
            await orch.wait_idle()
        finally:
            orch.close()

        finals = sink.finals()
        assert len(finals) == 1
        assert finals[0].final_reason is FinalReason.VAD_HARD_SILENCE
        assert finals[0].stream_id == "mic-01"

    asyncio.run(run())


def test_semantic_completion_finalizes_before_hard_silence() -> None:
    async def run() -> None:
        # A single segment ending in Japanese sentence-final punctuation:
        # the deterministic heuristic alone (no model call needed) judges
        # it complete once two consecutive decodes agree.
        model = ScriptedAsrModel([_result("テストです。", Language.JAPANESE)])
        client = ScriptedTranslationClient(["Đây là một bài kiểm tra."])
        sink = _EventSink()
        orch = _orchestrator(model, client, sink)
        orch.add_stream(
            "mic-01",
            source=StreamSource.MICROPHONE,
            source_language=Language.JAPANESE,
            target_language=Language.VIETNAMESE,
        )
        try:
            # 2 speech frames confirm + 2 more speech frames so >=2 partial
            # decodes see the same content (commits the stable text), then
            # only enough silence to cross soft_silence_ms (60ms = 3
            # frames) -- well short of hard_silence_ms (160ms).
            await _feed(orch, "mic-01", [0.9, 0.9, 0.9, 0.9] + [0.1] * 3)
            await orch.wait_idle()
        finally:
            orch.close()

        finals = sink.finals()
        assert len(finals) == 1
        assert finals[0].final_reason is FinalReason.SEMANTIC_COMPLETE
        assert finals[0].transcription == "テストです。"

    asyncio.run(run())


def test_pause_resume_discards_stale_decision_no_early_finalize() -> None:
    async def run() -> None:
        class DelayedCompleteClient:
            """Answers "complete" but only after a real, non-trivial delay.

            Gives the test a wide, reliable window in which to feed a
            resume frame before the decision actually resolves -- unlike a
            purely heuristic (no I/O) decision, which can complete
            synchronously fast enough that there is no meaningful window to
            race against.
            """

            async def complete_chat(
                self, *, system_prompt: str, user_content: str, max_tokens: int
            ) -> str:
                await asyncio.sleep(0.1)
                return '{"complete": true, "confidence": 0.9}'

        # No punctuation/ending signal -> heuristic is ambiguous -> the
        # (slow) completeness model is consulted.
        model = ScriptedAsrModel([_result("no signal here", Language.JAPANESE)])
        sink = _EventSink()
        orch = _orchestrator(
            model,
            DelayedCompleteClient(),
            sink,
            completeness_config=CompletenessConfig(
                enabled=True, timeout_ms=1000, skip_queue_depth=99
            ),
        )
        orch.add_stream(
            "mic-01",
            source=StreamSource.MICROPHONE,
            source_language=Language.JAPANESE,
            target_language=Language.VIETNAMESE,
        )
        try:
            # Reach soft silence: schedules a completeness decision that
            # will not resolve for ~100ms (the model round trip).
            t = await _feed(orch, "mic-01", [0.9, 0.9, 0.9, 0.9] + [0.1] * 3)
            # Resume speaking well within that window: invalidates the
            # pending decision before it can act.
            t = await _feed(orch, "mic-01", [0.9, 0.9], t0=t)
            # Now let the stale decision (and anything else) actually run.
            await orch.wait_idle()
            assert sink.finals() == []  # must NOT have finalized early

            # Continue to a real hard silence to finalize normally.
            await _feed(orch, "mic-01", [0.1] * 8, t0=t)
            await orch.wait_idle()
        finally:
            orch.close()

        finals = sink.finals()
        assert len(finals) == 1
        assert finals[0].final_reason is FinalReason.VAD_HARD_SILENCE

    asyncio.run(run())


def test_no_double_finalize_when_hard_silence_races_pending_decision() -> None:
    async def run() -> None:
        model = ScriptedAsrModel([_result("テストです。", Language.JAPANESE)])
        client = ScriptedTranslationClient(["Đây là một bài kiểm tra."])
        sink = _EventSink()
        orch = _orchestrator(model, client, sink)
        orch.add_stream(
            "mic-01",
            source=StreamSource.MICROPHONE,
            source_language=Language.JAPANESE,
            target_language=Language.VIETNAMESE,
        )
        try:
            # Commit stable text (with definite-complete punctuation) while
            # still speaking, via the normal partial-decode-ticking feed.
            t = await _feed(orch, "mic-01", [0.9, 0.9, 0.9, 0.9])
            # Then run straight through soft silence (schedules a decision
            # that would finalize as semantic_complete) AND onward past
            # hard silence using the no-suspension-point helper, so the VAD
            # machine's own synchronous hard-silence finalize is guaranteed
            # to fire (and invalidate the pending decision) before that
            # decision ever gets a chance to run.
            await _feed_no_partial(orch, "mic-01", [0.1] * 8, t0=t)
            await orch.wait_idle()
        finally:
            orch.close()

        finals = sink.finals()
        assert len(finals) == 1  # exactly once, never twice
        assert finals[0].final_reason is FinalReason.VAD_HARD_SILENCE

    asyncio.run(run())


def test_completeness_timeout_falls_back_to_deterministic_incomplete() -> None:
    async def run() -> None:
        class SlowClient:
            async def complete_chat(
                self, *, system_prompt: str, user_content: str, max_tokens: int
            ) -> str:
                await asyncio.sleep(0.2)
                return '{"complete": true, "confidence": 0.99}'

        # No punctuation/ending signal: the heuristic is ambiguous, so the
        # (slow, timing-out) completeness model would be consulted.
        model = ScriptedAsrModel([_result("no signal here", Language.JAPANESE)])
        sink = _EventSink()
        orch = _orchestrator(
            model,
            SlowClient(),
            sink,
            completeness_config=CompletenessConfig(enabled=True, timeout_ms=20, skip_queue_depth=4),
        )
        orch.add_stream(
            "mic-01",
            source=StreamSource.MICROPHONE,
            source_language=Language.JAPANESE,
            target_language=Language.VIETNAMESE,
        )
        try:
            # Soft silence only (not hard silence): if the timeout fallback
            # were ignored (i.e. treated as complete), this would wrongly
            # finalize as semantic_complete.
            await _feed(orch, "mic-01", [0.9, 0.9, 0.9, 0.9] + [0.1] * 3)
            await orch.wait_idle()
        finally:
            orch.close()

        # The (timed-out) model call must not have caused an early finalize.
        assert sink.finals() == []

    asyncio.run(run())


def test_concurrent_streams_finalize_independently() -> None:
    async def run() -> None:
        model = ScriptedAsrModel([_result("テストです。", Language.JAPANESE)])
        client = ScriptedTranslationClient(["Đây là một bài kiểm tra."])
        sink = _EventSink()
        orch = _orchestrator(model, client, sink)
        orch.add_stream(
            "mic-01",
            source=StreamSource.MICROPHONE,
            source_language=Language.JAPANESE,
            target_language=Language.VIETNAMESE,
        )
        orch.add_stream(
            "loop-01",
            source=StreamSource.LOOPBACK,
            source_language=Language.JAPANESE,
            target_language=Language.VIETNAMESE,
        )
        try:
            # Interleave: both streams have an utterance open at once.
            t_a = await _feed(orch, "mic-01", [0.9, 0.9])
            t_b = await _feed(orch, "loop-01", [0.9, 0.9])
            t_a = await _feed(orch, "mic-01", [0.9, 0.9] + [0.1] * 3, t0=t_a)
            t_b = await _feed(orch, "loop-01", [0.9, 0.9] + [0.1] * 3, t0=t_b)
            await orch.wait_idle()
        finally:
            orch.close()

        finals = sink.finals()
        assert len(finals) == 2
        by_stream = {f.stream_id: f for f in finals}
        assert set(by_stream) == {"mic-01", "loop-01"}
        assert by_stream["mic-01"].final_reason is FinalReason.SEMANTIC_COMPLETE
        assert by_stream["loop-01"].final_reason is FinalReason.SEMANTIC_COMPLETE
        # Independent utterance ids (prefixed by their own stream id).
        assert by_stream["mic-01"].utterance_id != by_stream["loop-01"].utterance_id
        assert by_stream["mic-01"].utterance_id.startswith("mic-01-")
        assert by_stream["loop-01"].utterance_id.startswith("loop-01-")

    asyncio.run(run())


def test_client_flush_forces_finalization() -> None:
    async def run() -> None:
        model = ScriptedAsrModel([_result("still speaking", Language.JAPANESE)])
        client = ScriptedTranslationClient(["OK"])
        sink = _EventSink()
        orch = _orchestrator(model, client, sink)
        orch.add_stream(
            "mic-01",
            source=StreamSource.MICROPHONE,
            source_language=Language.JAPANESE,
            target_language=Language.VIETNAMESE,
        )
        try:
            # Still actively speaking (no silence at all) when flushed.
            await _feed(orch, "mic-01", [0.9, 0.9, 0.9, 0.9])
            await orch.flush_stream("mic-01", FinalReason.CLIENT_FLUSH)
            await orch.wait_idle()
        finally:
            orch.close()

        finals = sink.finals()
        assert len(finals) == 1
        assert finals[0].final_reason is FinalReason.CLIENT_FLUSH

    asyncio.run(run())


def test_translation_retry_publishes_translation_updated() -> None:
    async def run() -> None:
        model = ScriptedAsrModel([_result("no punctuation here", Language.JAPANESE)])
        # First attempt fails validation (forbidden label); retry succeeds.
        client = ScriptedTranslationClient(["Translation: xin chào", "Xin chào."])
        sink = _EventSink()
        orch = _orchestrator(model, client, sink)
        orch.add_stream(
            "mic-01",
            source=StreamSource.MICROPHONE,
            source_language=Language.JAPANESE,
            target_language=Language.VIETNAMESE,
        )
        try:
            await _feed(orch, "mic-01", [0.9, 0.9, 0.9, 0.9] + [0.1] * 8)
            await orch.wait_idle()
        finally:
            orch.close()

        finals = sink.finals()
        updates = sink.updates()
        assert len(finals) == 1
        assert finals[0].translation_status.value == "failed"
        assert len(updates) == 1
        assert updates[0].translation == "Xin chào."
        assert updates[0].translation_status.value == "completed"

    asyncio.run(run())


def test_metrics_wiring_records_translation_outcome_and_queue_returns_to_zero() -> None:
    async def run() -> None:
        model = ScriptedAsrModel([_result("no punctuation here", Language.JAPANESE)])
        client = ScriptedTranslationClient(["OK"])
        sink = _EventSink()
        metrics = create_metrics()
        orch = _orchestrator(model, client, sink, metrics=metrics)
        orch.add_stream(
            "mic-01",
            source=StreamSource.MICROPHONE,
            source_language=Language.JAPANESE,
            target_language=Language.VIETNAMESE,
        )
        try:
            await _feed(orch, "mic-01", [0.9, 0.9, 0.9, 0.9] + [0.1] * 8)
            await orch.wait_idle()
        finally:
            orch.close()

        finals = sink.finals()
        assert len(finals) == 1
        recorded_count = metrics.translation_requests_total.labels(
            priority="final", status=finals[0].translation_status.value
        )._value.get()
        assert recorded_count == 1
        # Queue depth must be back to 0 once the pressure slot is released.
        assert metrics.translation_queue_depth.labels(priority="final")._value.get() == 0

    asyncio.run(run())


def test_correlation_ids_are_bound_during_publish() -> None:
    async def run() -> None:
        model = ScriptedAsrModel([_result("no punctuation here", Language.JAPANESE)])
        client = ScriptedTranslationClient(["OK"])
        seen: list[dict[str, str]] = []

        async def publish(event: object) -> None:
            seen.append(current())

        orch = _orchestrator(model, client, publish)  # type: ignore[arg-type]
        orch.add_stream(
            "mic-01",
            source=StreamSource.MICROPHONE,
            source_language=Language.JAPANESE,
            target_language=Language.VIETNAMESE,
        )
        try:
            await _feed(orch, "mic-01", [0.9, 0.9, 0.9, 0.9] + [0.1] * 8)
            await orch.wait_idle()
        finally:
            orch.close()

        bound_entries = [s for s in seen if s]
        assert len(bound_entries) == 1  # only the final event's publish was bound
        bound = bound_entries[0]
        assert bound["session_id"] == "sess-1"
        assert bound["stream_id"] == "mic-01"
        assert bound["utterance_id"].startswith("mic-01-")
        assert "request_id" in bound
        # No correlation IDs leak outside the bound block.
        assert current() == {}

    asyncio.run(run())
