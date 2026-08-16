"""Streaming partial ASR: per-utterance decode orchestration and publication.

Composes the pure :class:`~server.asr.sliding_window.SlidingAudioWindow` and
:class:`~server.asr.stable_prefix.StablePrefixTracker` components with an
:class:`~server.asr.interface.AsrModel` to produce ``transcription.partial``
events for in-progress utterances. Scheduling *when* to decode is a separate,
pure concern (:mod:`server.asr.partial_scheduler`); this module only performs
one decode when asked and reports whether a new event should be published.

Decoding runs off the event loop in a dedicated executor, exactly like
:class:`server.asr.worker.FinalTranscriber`. Per the ASR scheduler priority
policy in ``docs/ARCHITECTURE.md`` (final ASR before partial ASR), this class
never touches final reconciliation: final results always remain authoritative
and this module does not alter their behavior.
"""

from __future__ import annotations

import asyncio
import logging
from concurrent.futures import Executor, ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import UTC, datetime

from server.asr.errors import AsrError, classify_backend_error
from server.asr.interface import AsrModel
from server.asr.sliding_window import SlidingAudioWindow
from server.asr.stable_prefix import StablePrefixTracker
from server.asr.types import BYTES_PER_MS, AsrConfig, AsrRequest
from shared.protocol.enums import Language
from shared.protocol.messages import TranscriptionPartial

_LOG = logging.getLogger("server.asr.partial")


def _now() -> datetime:
    return datetime.now(UTC)


@dataclass
class _UtteranceState:
    session_id: str
    stream_id: str
    source_language: Language
    start_ms: int
    window: SlidingAudioWindow
    tracker: StablePrefixTracker = field(default_factory=StablePrefixTracker)
    total_ms: int = 0
    revision: int = 0
    last_published: tuple[str, str] | None = None
    generation: int = 0


class PartialTranscriber:
    """Produces ``transcription.partial`` events for in-progress utterances."""

    def __init__(
        self,
        model: AsrModel,
        config: AsrConfig,
        *,
        overlap_ms: int,
        executor: Executor | None = None,
    ) -> None:
        self._model = model
        self._config = config
        self._overlap_ms = overlap_ms
        self._owns_executor = executor is None
        self._executor: Executor = executor or ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="asr-partial"
        )
        self._utterances: dict[str, _UtteranceState] = {}

    def start_utterance(
        self,
        utterance_id: str,
        *,
        session_id: str,
        stream_id: str,
        source_language: Language,
        start_ms: int = 0,
    ) -> None:
        """Register a new in-progress utterance for partial decoding."""
        self._utterances[utterance_id] = _UtteranceState(
            session_id=session_id,
            stream_id=stream_id,
            source_language=source_language,
            start_ms=start_ms,
            window=SlidingAudioWindow(overlap_ms=self._overlap_ms),
        )

    def append_audio(self, utterance_id: str, chunk: bytes) -> None:
        """Feed newly received audio for an active utterance, if any."""
        state = self._utterances.get(utterance_id)
        if state is None:
            return
        state.window.append(chunk)
        state.total_ms += len(chunk) // BYTES_PER_MS

    def stop_utterance(self, utterance_id: str) -> None:
        """Remove an utterance's partial state (finalized or abandoned)."""
        self._utterances.pop(utterance_id, None)

    def is_active(self, utterance_id: str) -> bool:
        return utterance_id in self._utterances

    def current_text(self, utterance_id: str) -> tuple[str, str]:
        """Latest published ``(stable_text, unstable_text)``, or ``("", "")`` if none yet.

        Exposed so a completeness-decision caller can read the current
        partial transcription without waiting for/forcing a new decode.
        """
        state = self._utterances.get(utterance_id)
        if state is None or state.last_published is None:
            return ("", "")
        return state.last_published

    def current_revision(self, utterance_id: str) -> int:
        """Latest published partial revision, or 0 if none yet published.

        Exposed so a future final-reconciliation caller can assign the final
        event a strictly higher revision than the last partial.
        """
        state = self._utterances.get(utterance_id)
        return state.revision if state is not None else 0

    async def decode(self, utterance_id: str) -> TranscriptionPartial | None:
        """Run one partial decode for ``utterance_id``.

        Returns ``None`` when the utterance is unknown/stopped, has no audio
        yet, or the merged stable/unstable text is unchanged since the last
        published event (duplicate suppression) -- callers must not publish
        in that case. A decode result that arrives after the utterance was
        stopped or superseded by a newer decode is discarded rather than
        applied (stale-result protection).
        """
        state = self._utterances.get(utterance_id)
        if state is None:
            _LOG.debug("partial decode skipped for %s: no state (stopped?)", utterance_id)
            return None
        audio = state.window.window()
        if not audio:
            _LOG.debug(
                "partial decode skipped for %s: empty window (total_ms=%d)",
                utterance_id,
                state.total_ms,
            )
            return None

        state.generation += 1
        my_generation = state.generation
        request = AsrRequest(
            audio=audio,
            language=state.source_language,
            beam_size=self._config.partial_beam_size,
            temperature=self._config.temperature,
            condition_on_previous_text=self._config.condition_on_previous_text,
            previous_text=state.tracker.committed_text or None,
        )
        loop = asyncio.get_running_loop()
        try:
            result = await loop.run_in_executor(self._executor, self._model.transcribe, request)
        except AsrError:
            raise
        except Exception as exc:
            raise classify_backend_error(exc) from exc

        state = self._utterances.get(utterance_id)
        if state is None or state.generation != my_generation:
            # Utterance finalized/stopped, or a newer decode superseded this
            # one, while this decode was running off the event loop.
            _LOG.debug(
                "partial decode for %s discarded post-model: state_present=%s "
                "generation_mismatch=%s",
                utterance_id,
                state is not None,
                state is not None and state.generation != my_generation,
            )
            return None

        merged = state.tracker.update(result.segments)
        boundary_ms = state.tracker.stable_boundary_ms(result.segments)
        window_advanced = state.window.advance(boundary_ms)
        if window_advanced:
            state.tracker.reset_window()
        _LOG.debug(
            "partial decode for %s: boundary_ms=%d window_advanced=%s "
            "buffered_ms_after=%d total_ms=%d",
            utterance_id,
            boundary_ms,
            window_advanced,
            state.window.buffered_ms,
            state.total_ms,
        )

        published = (merged.stable_text, merged.unstable_text)
        if published == state.last_published:
            _LOG.debug("partial decode for %s: duplicate text, not publishing", utterance_id)
            return None
        state.last_published = published
        state.revision += 1

        return TranscriptionPartial(
            session_id=state.session_id,
            stream_id=state.stream_id,
            utterance_id=utterance_id,
            revision=state.revision,
            source_language=state.source_language,
            stable_text=merged.stable_text,
            unstable_text=merged.unstable_text,
            display_text=merged.display_text,
            start_ms=state.start_ms,
            end_ms=state.start_ms + state.total_ms,
            timestamp=_now(),
        )

    def close(self) -> None:
        """Shut down the owned executor, if any."""
        if self._owns_executor:
            self._executor.shutdown(wait=False)
