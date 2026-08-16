"""Per-stream VAD utterance state machine.

Consumes fixed-duration audio frames plus a speech probability and segments them
into utterances. States: IDLE, SPEECH_STARTING, SPEAKING, POSSIBLE_END,
FINALIZING (transient). It manages the utterance audio buffer (with pre-roll and
trailing padding), utterance ids, timestamps and the finalization reason, and
emits speech-start, soft-silence, resumed-speech and finalization events.

The machine is pure synchronous CPU logic and holds no model or I/O; the caller
computes probabilities (off the event loop) and feeds frames here. Time is
derived from frame durations so behavior is fully deterministic.
"""

from __future__ import annotations

from server.vad.events import (
    ResumedSpeech,
    SoftSilence,
    SpeechStarted,
    UtteranceAbandoned,
    UtteranceFinalized,
    VadEvent,
)
from server.vad.ring_buffer import PreRollBuffer
from server.vad.types import (
    BYTES_PER_MS,
    Utterance,
    VadConfig,
    VadState,
)
from shared.protocol.enums import FinalReason, StreamSource


class UtteranceSegmenter:
    """Segment one stream's frames into utterances via VAD probabilities."""

    def __init__(
        self,
        *,
        source: StreamSource,
        config: VadConfig,
        frame_ms: int,
        id_prefix: str = "utt",
    ) -> None:
        if frame_ms < 1:
            raise ValueError("frame_ms must be >= 1")
        self._source = source
        self._config = config
        self._frame_ms = frame_ms
        self._id_prefix = id_prefix

        self._state = VadState.IDLE
        self._now_ms = 0
        self._preroll = PreRollBuffer(capacity_ms=config.speech_pad_before_ms, frame_ms=frame_ms)

        # Provisional (SPEECH_STARTING) state.
        self._prov_audio = bytearray()
        self._prov_start_ms = 0
        self._preroll_snapshot = b""
        self._speech_run_ms = 0

        # Open-utterance state.
        self._utterance_id: str | None = None
        self._utt_start_ms = 0
        self._utt_audio = bytearray()
        self._speech_ms = 0
        self._silence_run_ms = 0
        self._soft_emitted = False
        self._counter = 0

    # --- Introspection -------------------------------------------------------
    @property
    def state(self) -> VadState:
        return self._state

    @property
    def now_ms(self) -> int:
        return self._now_ms

    @property
    def current_utterance_id(self) -> str | None:
        return self._utterance_id

    @property
    def speech_ms(self) -> int:
        """Total confirmed speech duration (ms) of the currently open utterance."""
        return self._speech_ms

    # --- Frame ingest --------------------------------------------------------
    def process_frame(self, pcm: bytes, probability: float) -> list[VadEvent]:
        """Process one frame; return any events produced (usually zero or one)."""
        events: list[VadEvent] = []
        frame_start = self._now_ms
        self._now_ms += self._frame_ms
        is_speech = probability >= self._config.threshold

        if self._state is VadState.IDLE:
            self._on_idle(pcm, is_speech, frame_start, events)
        elif self._state is VadState.SPEECH_STARTING:
            self._on_starting(pcm, is_speech, events)
        elif self._state is VadState.SPEAKING:
            self._on_speaking(pcm, is_speech, events)
        elif self._state is VadState.POSSIBLE_END:
            self._on_possible_end(pcm, is_speech, events)
        return events

    def flush(self, reason: FinalReason) -> list[VadEvent]:
        """Force finalization (client flush, session end, device reconfigure)."""
        events: list[VadEvent] = []
        if self._state in (VadState.SPEAKING, VadState.POSSIBLE_END):
            self._finalize(reason, events, forced=True)
        elif self._state is VadState.SPEECH_STARTING:
            self._reset_idle()
        return events

    # --- State handlers ------------------------------------------------------
    def _on_idle(
        self, pcm: bytes, is_speech: bool, frame_start: int, events: list[VadEvent]
    ) -> None:
        if is_speech:
            self._preroll_snapshot = self._preroll.snapshot()
            self._prov_audio = bytearray(pcm)
            self._prov_start_ms = frame_start
            self._speech_run_ms = self._frame_ms
            self._state = VadState.SPEECH_STARTING
            self._maybe_confirm(events)
        else:
            self._preroll.push(pcm)

    def _on_starting(self, pcm: bytes, is_speech: bool, events: list[VadEvent]) -> None:
        if is_speech:
            self._prov_audio.extend(pcm)
            self._speech_run_ms += self._frame_ms
            self._maybe_confirm(events)
        else:
            # False start: discard the provisional run.
            self._preroll.push(pcm)
            self._state = VadState.IDLE
            self._prov_audio = bytearray()
            self._speech_run_ms = 0

    def _on_speaking(self, pcm: bytes, is_speech: bool, events: list[VadEvent]) -> None:
        self._utt_audio.extend(pcm)
        if is_speech:
            self._speech_ms += self._frame_ms
            self._silence_run_ms = 0
            self._check_max(events)
        else:
            self._state = VadState.POSSIBLE_END
            self._silence_run_ms = self._frame_ms
            self._soft_emitted = False
            self._check_silence(events)
            if self._utterance_id is not None:
                self._check_max(events)

    def _on_possible_end(self, pcm: bytes, is_speech: bool, events: list[VadEvent]) -> None:
        self._utt_audio.extend(pcm)
        if is_speech:
            assert self._utterance_id is not None
            events.append(ResumedSpeech(utterance_id=self._utterance_id, at_ms=self._now_ms))
            self._state = VadState.SPEAKING
            self._silence_run_ms = 0
            self._soft_emitted = False
            self._speech_ms += self._frame_ms
            self._check_max(events)
        else:
            self._silence_run_ms += self._frame_ms
            self._check_silence(events)
            if self._utterance_id is not None:
                self._check_max(events)

    # --- Helpers -------------------------------------------------------------
    def _maybe_confirm(self, events: list[VadEvent]) -> None:
        if self._speech_run_ms < self._config.speech_start_ms:
            return
        self._counter += 1
        self._utterance_id = f"{self._id_prefix}-{self._counter:05d}"
        preroll_ms = len(self._preroll_snapshot) // BYTES_PER_MS
        self._utt_start_ms = self._prov_start_ms - preroll_ms
        self._utt_audio = bytearray(self._preroll_snapshot)
        self._utt_audio.extend(self._prov_audio)
        self._speech_ms = self._speech_run_ms
        self._silence_run_ms = 0
        self._soft_emitted = False
        self._preroll.clear()
        self._prov_audio = bytearray()
        self._state = VadState.SPEAKING
        events.append(SpeechStarted(utterance_id=self._utterance_id, start_ms=self._utt_start_ms))
        self._check_max(events)

    def _check_silence(self, events: list[VadEvent]) -> None:
        if self._utterance_id is None:
            return
        if not self._soft_emitted and self._silence_run_ms >= self._config.soft_silence_ms:
            self._soft_emitted = True
            events.append(SoftSilence(utterance_id=self._utterance_id, at_ms=self._now_ms))
        if self._silence_run_ms >= self._config.hard_silence_ms:
            self._finalize(FinalReason.VAD_HARD_SILENCE, events)

    def _check_max(self, events: list[VadEvent]) -> None:
        if self._utterance_id is None:
            return
        if (self._now_ms - self._utt_start_ms) >= self._config.max_utterance_ms:
            self._finalize(FinalReason.MAX_UTTERANCE, events)

    def _finalize(
        self, reason: FinalReason, events: list[VadEvent], *, forced: bool = False
    ) -> None:
        if self._utterance_id is None:
            self._reset_idle()
            return

        # Trim trailing silence beyond the configured post-roll padding.
        pad_keep = min(self._silence_run_ms, self._config.speech_pad_after_ms)
        trim_ms = self._silence_run_ms - pad_keep
        if trim_ms > 0:
            trim_bytes = trim_ms * BYTES_PER_MS
            if trim_bytes < len(self._utt_audio):
                del self._utt_audio[len(self._utt_audio) - trim_bytes :]
            else:
                self._utt_audio = bytearray()
        end_ms = self._now_ms - trim_ms

        too_short = self._speech_ms < self._config.min_speech_ms
        if self._speech_ms == 0 or (too_short and not forced):
            events.append(
                UtteranceAbandoned(utterance_id=self._utterance_id, speech_ms=self._speech_ms)
            )
            self._reset_idle()
            return

        utterance = Utterance(
            utterance_id=self._utterance_id,
            source=self._source,
            start_ms=self._utt_start_ms,
            end_ms=end_ms,
            speech_ms=self._speech_ms,
            final_reason=reason,
            audio=bytes(self._utt_audio),
        )
        events.append(UtteranceFinalized(utterance=utterance))
        self._reset_idle()

    def _reset_idle(self) -> None:
        self._state = VadState.IDLE
        self._utterance_id = None
        self._utt_audio = bytearray()
        self._prov_audio = bytearray()
        self._preroll_snapshot = b""
        self._speech_run_ms = 0
        self._speech_ms = 0
        self._silence_run_ms = 0
        self._soft_emitted = False
        self._preroll.clear()
