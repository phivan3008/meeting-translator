"""Full per-session finalization orchestrator: VAD -> partial ASR -> final ASR
-> translation -> final event (docs/ARCHITECTURE.md processing pipeline).

Composes components already built in Phases 04-07 (:class:`UtteranceSegmenter`,
:class:`PartialTranscriber`, :class:`PartialDecodeScheduler`,
:class:`FinalTranscriber`, :class:`FinalTranslator`,
:class:`CompletenessClassifier`, :class:`TranslationQueue`) plus this phase's
own deterministic heuristic checker. Frame ingestion and partial-decode
ticking are driven by the caller (matches ``PartialDecodeScheduler``'s
time-injected style); this class contains no real-time timer loop or
WebSocket I/O of its own. The caller driving it in production is
``server/transport/gateway.py`` (see ``OrchestrationDeps``/
``_build_orchestrator``), which feeds released audio frames through VAD
and calls ``ingest_frame``/``run_due_partial_decodes``/``flush_stream``,
publishing whatever this class emits back over the live WebSocket.

Soft silence (``SoftSilence``) triggers a *decision*, not automatic
finalization: the deterministic heuristic runs immediately, and only for a
genuinely ambiguous result does an optional, low-priority Qwen completeness
check run (skipped under translation-queue pressure or when disabled). Hard
silence and max-utterance duration are already handled synchronously inside
``UtteranceSegmenter`` itself; client flush, session end and device
reconfiguration are forced via :meth:`UtteranceOrchestrator.flush_stream`.

Race safety: a soft-silence decision runs in the background (it may involve
an HTTP round trip) and must never finalize an utterance twice, or finalize
one that has since resumed speaking or already finalized for another
reason. Each utterance carries a monotonically increasing "pending
generation" counter, bumped on every ``SoftSilence`` (new decision),
``ResumedSpeech`` (invalidate any decision in flight) and
``UtteranceFinalized`` (invalidate; already finalized). A late-resolving
decision only acts if its captured generation still matches and the
segmenter still reports the same utterance as open.
"""

from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import AsyncIterator, Coroutine
from contextlib import asynccontextmanager
from dataclasses import dataclass, field

from server.asr.errors import AsrError
from server.asr.interface import AsrModel
from server.asr.partial import PartialTranscriber
from server.asr.partial_scheduler import PartialDecodeScheduler
from server.asr.types import AsrConfig
from server.asr.worker import FinalTranscriber, build_asr_error_event
from server.observability.correlation import bind, new_request_id
from server.observability.metrics import Metrics
from server.orchestration.heuristics import HeuristicConfig, evaluate_heuristic
from server.orchestration.types import CompletenessConfig, PublishEvent
from server.reliability.circuit_breaker import CircuitBreaker
from server.translation.completeness import CompletenessClassifier
from server.translation.interface import TranslationClient
from server.translation.queue import TranslationPriority, TranslationQueue, should_skip_completeness
from server.translation.types import (
    MAX_CONTEXT_SENTENCES,
    TranslationConfig,
    TranslationOutcome,
    TranslationRequest,
)
from server.translation.worker import FinalTranslator, apply_translation, build_translation_updated
from server.vad.events import (
    ResumedSpeech,
    SoftSilence,
    SpeechStarted,
    UtteranceFinalized,
    VadEvent,
)
from server.vad.state_machine import UtteranceSegmenter
from server.vad.types import Utterance, VadConfig
from shared.protocol.enums import FinalReason, Language, StreamSource, TranslationStatus
from shared.protocol.messages import TranscriptionPartial


@dataclass
class _StreamState:
    source: StreamSource
    source_language: Language
    target_language: Language
    segmenter: UtteranceSegmenter
    context_sentences: deque[str] = field(
        default_factory=lambda: deque(maxlen=MAX_CONTEXT_SENTENCES)
    )
    # Bumped on SoftSilence (new pending decision), ResumedSpeech and
    # UtteranceFinalized (invalidate any decision in flight). See the
    # module docstring's "Race safety" section.
    pending_gen: dict[str, int] = field(default_factory=dict)


class UtteranceOrchestrator:
    """Drives one session's streams through the full finalization pipeline."""

    def __init__(
        self,
        *,
        session_id: str,
        vad_config: VadConfig,
        frame_ms: int,
        asr_config: AsrConfig,
        asr_model: AsrModel,
        translation_config: TranslationConfig,
        translation_client: TranslationClient,
        publish: PublishEvent,
        heuristic_config: HeuristicConfig | None = None,
        completeness_config: CompletenessConfig | None = None,
        partial_interval_ms: int = 500,
        partial_overlap_ms: int = 1500,
        asr_final_timeout_ms: int = 8000,
        translation_queue_capacity_per_priority: int = 16,
        metrics: Metrics | None = None,
        asr_circuit_breaker: CircuitBreaker | None = None,
        translation_circuit_breaker: CircuitBreaker | None = None,
    ) -> None:
        self._session_id = session_id
        self._vad_config = vad_config
        self._frame_ms = frame_ms
        self._heuristic_config = heuristic_config or HeuristicConfig()
        self._completeness_config = completeness_config or CompletenessConfig()
        self._publish = publish
        self._metrics = metrics

        self._partial = PartialTranscriber(asr_model, asr_config, overlap_ms=partial_overlap_ms)
        self._scheduler = PartialDecodeScheduler(interval_ms=partial_interval_ms)
        self._final_transcriber = FinalTranscriber(
            asr_model,
            asr_config,
            timeout_ms=asr_final_timeout_ms,
            circuit_breaker=asr_circuit_breaker,
            metrics=metrics,
        )
        self._final_translator = FinalTranslator(
            translation_client,
            translation_config,
            circuit_breaker=translation_circuit_breaker,
            metrics=metrics,
        )
        self._completeness_classifier = CompletenessClassifier(
            translation_client,
            timeout_ms=self._completeness_config.timeout_ms,
            max_tokens=self._completeness_config.max_tokens,
        )
        self._translation_queue: TranslationQueue[object] = TranslationQueue(
            capacity_per_priority=translation_queue_capacity_per_priority
        )

        self._streams: dict[str, _StreamState] = {}
        self._background_tasks: set[asyncio.Task[None]] = set()

    # --- Stream registration ---------------------------------------------
    def add_stream(
        self,
        stream_id: str,
        *,
        source: StreamSource,
        source_language: Language,
        target_language: Language,
    ) -> None:
        """Register a new stream (e.g. microphone or loopback) for this session."""
        segmenter = UtteranceSegmenter(
            source=source, config=self._vad_config, frame_ms=self._frame_ms, id_prefix=stream_id
        )
        self._streams[stream_id] = _StreamState(
            source=source,
            source_language=source_language,
            target_language=target_language,
            segmenter=segmenter,
        )

    def remove_stream(self, stream_id: str) -> None:
        self._streams.pop(stream_id, None)

    # --- Frame ingestion ---------------------------------------------------
    async def ingest_frame(self, stream_id: str, pcm: bytes, probability: float) -> None:
        """Feed one fixed-duration audio frame plus its VAD probability."""
        state = self._require_stream(stream_id)
        events = state.segmenter.process_frame(pcm, probability)
        for event in events:
            await self._on_vad_event(stream_id, event)
        utterance_id = state.segmenter.current_utterance_id
        if utterance_id is not None and self._partial.is_active(utterance_id):
            self._partial.append_audio(utterance_id, pcm)

    async def flush_stream(self, stream_id: str, reason: FinalReason) -> None:
        """Force finalization: client flush, session end or device reconfiguration."""
        state = self._require_stream(stream_id)
        events = state.segmenter.flush(reason)
        for event in events:
            await self._on_vad_event(stream_id, event)

    async def run_due_partial_decodes(self, *, now_ms: int) -> list[TranscriptionPartial]:
        """Run and publish any partial decodes due at ``now_ms`` (caller-driven tick)."""
        published: list[TranscriptionPartial] = []
        for utterance_id in self._scheduler.due(now_ms=now_ms):
            result = await self._partial.decode(utterance_id)
            if result is not None:
                await self._publish(result)
                published.append(result)
        return published

    async def wait_idle(self) -> None:
        """Await all in-flight background work (finalize/retry/completeness tasks)."""
        while self._background_tasks:
            await asyncio.gather(*list(self._background_tasks), return_exceptions=True)

    def close(self) -> None:
        """Shut down owned executors."""
        self._partial.close()
        self._final_transcriber.close()

    # --- VAD event handling --------------------------------------------------
    async def _on_vad_event(self, stream_id: str, event: VadEvent) -> None:
        state = self._streams[stream_id]
        if isinstance(event, SpeechStarted):
            self._partial.start_utterance(
                event.utterance_id,
                session_id=self._session_id,
                stream_id=stream_id,
                source_language=state.source_language,
                start_ms=event.start_ms,
            )
            self._scheduler.start(event.utterance_id, now_ms=state.segmenter.now_ms)
            state.pending_gen[event.utterance_id] = 0
        elif isinstance(event, SoftSilence):
            gen = state.pending_gen.get(event.utterance_id, 0) + 1
            state.pending_gen[event.utterance_id] = gen
            self._spawn(self._evaluate_completeness(stream_id, event.utterance_id, gen))
        elif isinstance(event, ResumedSpeech):
            state.pending_gen[event.utterance_id] = state.pending_gen.get(event.utterance_id, 0) + 1
        elif isinstance(event, UtteranceFinalized):
            utterance = event.utterance
            state.pending_gen[utterance.utterance_id] = (
                state.pending_gen.get(utterance.utterance_id, 0) + 1
            )
            self._scheduler.stop(utterance.utterance_id)
            self._partial.stop_utterance(utterance.utterance_id)
            self._spawn(self._finalize_utterance(stream_id, utterance))

    def _spawn(self, coro: Coroutine[object, object, None]) -> None:
        task = asyncio.ensure_future(coro)
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)

    # --- Completeness decision (soft silence) --------------------------------
    async def _evaluate_completeness(self, stream_id: str, utterance_id: str, gen: int) -> None:
        state = self._streams[stream_id]
        stable_text, unstable_text = self._partial.current_text(utterance_id)
        verdict = evaluate_heuristic(
            language=state.source_language,
            stable_text=stable_text,
            unstable_text=unstable_text,
            speech_ms=state.segmenter.speech_ms,
            config=self._heuristic_config,
        )
        complete = verdict.complete

        if verdict.ambiguous and self._completeness_config.enabled and stable_text.strip():
            depth = self._translation_queue.qsize()
            skip = should_skip_completeness(
                current_depth=depth, skip_threshold=self._completeness_config.skip_queue_depth
            )
            if not skip:
                async with self._pressure_slot(TranslationPriority.COMPLETENESS) as admitted:
                    if admitted:
                        outcome = await self._completeness_classifier.classify(
                            language=state.source_language, sentence=stable_text.strip()
                        )
                        if outcome.complete is not None and (
                            outcome.confidence is None
                            or outcome.confidence >= self._completeness_config.min_confidence
                        ):
                            complete = outcome.complete
                        # else: unknown or low-confidence -> keep the
                        # deterministic fallback already in `complete`.

        if not complete:
            return
        # Re-check race-safety right before acting: state may have changed
        # (resumed speech, or already finalized by hard silence/flush) while
        # this decision was pending or awaiting the model call above.
        if state.pending_gen.get(utterance_id) != gen:
            return
        if state.segmenter.current_utterance_id != utterance_id:
            return

        events = state.segmenter.flush(FinalReason.SEMANTIC_COMPLETE)
        for event in events:
            await self._on_vad_event(stream_id, event)

    @asynccontextmanager
    async def _pressure_slot(self, priority: TranslationPriority) -> AsyncIterator[bool]:
        """Track one unit of in-flight translation-priority work.

        Yields whether the slot was actually tracked (``False`` only if the
        priority lane is already at capacity, which itself doubles as a
        pressure signal). The queue is used purely as a live depth counter
        here -- see the module docstring's discussion of queue pressure.
        """
        tracked = self._translation_queue.put(object(), priority=priority)
        self._record_queue_depth(priority)
        try:
            yield tracked
        finally:
            if tracked:
                self._translation_queue.get()
                self._record_queue_depth(priority)

    def _record_queue_depth(self, priority: TranslationPriority) -> None:
        if self._metrics is not None:
            self._metrics.translation_queue_depth.labels(priority=priority.name.lower()).set(
                self._translation_queue.qsize(priority)
            )

    # --- Finalization: final ASR + translation --------------------------------
    async def _finalize_utterance(self, stream_id: str, utterance: Utterance) -> None:
        with bind(
            session_id=self._session_id,
            stream_id=stream_id,
            utterance_id=utterance.utterance_id,
            request_id=new_request_id(),
        ):
            await self._do_finalize_utterance(stream_id, utterance)

    async def _do_finalize_utterance(self, stream_id: str, utterance: Utterance) -> None:
        state = self._streams[stream_id]
        revision = self._partial.current_revision(utterance.utterance_id) + 1
        try:
            final_event = await self._final_transcriber.finalize(
                utterance,
                session_id=self._session_id,
                stream_id=stream_id,
                source_language=state.source_language,
                target_language=state.target_language,
                revision=revision,
            )
        except AsrError as exc:
            await self._publish(
                build_asr_error_event(
                    exc, session_id=self._session_id, utterance_id=utterance.utterance_id
                )
            )
            return

        transcription = final_event.transcription
        request: TranslationRequest | None = None
        if transcription.strip():
            request = TranslationRequest(
                text=transcription,
                source_language=state.source_language,
                target_language=state.target_language,
                context_sentences=tuple(state.context_sentences),
            )
            async with self._pressure_slot(TranslationPriority.FINAL):
                outcome = await self._final_translator.translate_once(request)
        else:
            outcome = TranslationOutcome(
                text=None, status=TranslationStatus.FAILED, issue="empty_transcription"
            )

        final_event = apply_translation(final_event, outcome)
        await self._publish(final_event)
        if transcription.strip():
            state.context_sentences.append(transcription)

        if outcome.status is TranslationStatus.FAILED and request is not None:
            self._spawn(
                self._retry_translation(stream_id, final_event.utterance_id, request, outcome.issue)
            )

    async def _retry_translation(
        self,
        stream_id: str,
        utterance_id: str,
        request: TranslationRequest,
        previous_issue: str | None,
    ) -> None:
        with bind(
            session_id=self._session_id,
            stream_id=stream_id,
            utterance_id=utterance_id,
            request_id=new_request_id(),
        ):
            async with self._pressure_slot(TranslationPriority.RETRY):
                outcome = await self._final_translator.retry(request, previous_issue=previous_issue)
            if outcome.status is TranslationStatus.COMPLETED:
                updated = build_translation_updated(
                    session_id=self._session_id,
                    stream_id=stream_id,
                    utterance_id=utterance_id,
                    outcome=outcome,
                )
                await self._publish(updated)

    def _require_stream(self, stream_id: str) -> _StreamState:
        state = self._streams.get(stream_id)
        if state is None:
            raise KeyError(f"unknown stream_id: {stream_id!r}")
        return state
