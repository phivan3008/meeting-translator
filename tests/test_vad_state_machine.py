"""State-transition and boundary tests for the utterance state machine."""

from __future__ import annotations

from server.vad.events import (
    ResumedSpeech,
    SoftSilence,
    SpeechStarted,
    UtteranceFinalized,
)
from server.vad.state_machine import UtteranceSegmenter
from server.vad.types import VadConfig, VadState
from shared.protocol.enums import FinalReason, StreamSource

FRAME_MS = 20
FRAME_BYTES = FRAME_MS * 32  # mono 16 kHz S16LE

# Small, frame-aligned thresholds for deterministic tests.
CONFIG = VadConfig(
    threshold=0.5,
    speech_start_ms=40,  # 2 frames
    min_speech_ms=60,  # 3 frames
    soft_silence_ms=60,  # 3 frames
    hard_silence_ms=120,  # 6 frames
    speech_pad_before_ms=40,  # 2 frames
    speech_pad_after_ms=40,  # 2 frames
    max_utterance_ms=400,  # 20 frames
)

SPEECH = bytes([1]) * FRAME_BYTES
SILENCE = bytes([0]) * FRAME_BYTES


def _segmenter(config: VadConfig = CONFIG) -> UtteranceSegmenter:
    return UtteranceSegmenter(source=StreamSource.MICROPHONE, config=config, frame_ms=FRAME_MS)


def _run(seg: UtteranceSegmenter, probs: list[float]) -> list:  # type: ignore[type-arg]
    events: list = []  # type: ignore[type-arg]
    for prob in probs:
        pcm = SPEECH if prob >= CONFIG.threshold else SILENCE
        events.extend(seg.process_frame(pcm, prob))
    return events


def test_full_utterance_hard_silence() -> None:
    seg = _segmenter()
    # 2 idle, 4 speech (confirm on 2nd), 6 silence (soft then hard).
    probs = [0.1, 0.1] + [0.9, 0.9, 0.9, 0.9] + [0.1] * 6
    events = _run(seg, probs)

    kinds = [type(e) for e in events]
    assert kinds == [SpeechStarted, SoftSilence, UtteranceFinalized]

    started = events[0]
    assert isinstance(started, SpeechStarted)
    assert started.utterance_id == "utt-00001"
    assert started.start_ms == 0  # pre-roll (40ms) pulls start back to 0

    final = events[2]
    assert isinstance(final, UtteranceFinalized)
    utt = final.utterance
    assert utt.final_reason is FinalReason.VAD_HARD_SILENCE
    assert utt.start_ms == 0
    assert utt.speech_ms == 80  # 4 speech frames
    # Trailing silence trimmed to pad_after (40ms): end at 120 + 40 = 160.
    assert utt.end_ms == 160
    assert len(utt.audio) == 160 * 32  # 160 ms of audio
    assert seg.state is VadState.IDLE


def test_speech_ms_tracks_confirmed_speech_and_resets_after_finalize() -> None:
    seg = _segmenter()
    assert seg.speech_ms == 0

    # 2 idle, 4 speech (confirm on 2nd frame -> speech_ms starts at 40ms).
    _run(seg, [0.1, 0.1, 0.9, 0.9])
    assert seg.speech_ms == 40

    _run(seg, [0.9, 0.9])
    assert seg.speech_ms == 80

    # Silence long enough to hard-finalize; speech_ms resets for the next utterance.
    _run(seg, [0.1] * 6)
    assert seg.speech_ms == 0


def test_resumed_speech_prevents_finalization() -> None:
    seg = _segmenter()
    # confirm speech, brief silence (below hard), then speech resumes.
    probs = [0.9, 0.9, 0.1, 0.1, 0.9, 0.9]
    events = _run(seg, probs)
    kinds = [type(e) for e in events]
    assert SpeechStarted in kinds
    assert ResumedSpeech in kinds
    assert UtteranceFinalized not in kinds
    assert seg.state is VadState.SPEAKING


def test_soft_silence_emitted_once() -> None:
    seg = _segmenter()
    probs = [0.9, 0.9] + [0.1] * 3  # confirm then 3 silence frames -> soft at 60ms
    events = _run(seg, probs)
    soft = [e for e in events if isinstance(e, SoftSilence)]
    assert len(soft) == 1
    assert soft[0].at_ms == 100  # now advances: 40 (speech) + 60 (silence)


def test_short_utterance_discarded_on_hard_silence() -> None:
    seg = _segmenter()
    # Exactly enough speech to confirm (40ms) < min_speech (60ms), then silence.
    probs = [0.9, 0.9] + [0.1] * 6
    events = _run(seg, probs)
    assert not any(isinstance(e, UtteranceFinalized) for e in events)
    assert seg.state is VadState.IDLE


def test_max_utterance_forces_finalization() -> None:
    seg = _segmenter()
    # Continuous speech beyond max_utterance_ms (400ms). Pre-roll is zero here
    # because there is no idle lead-in.
    probs = [0.9] * 25
    events = _run(seg, probs)
    finals = [e for e in events if isinstance(e, UtteranceFinalized)]
    assert len(finals) == 1
    assert finals[0].utterance.final_reason is FinalReason.MAX_UTTERANCE
    assert finals[0].utterance.start_ms == 0


def test_false_start_returns_to_idle() -> None:
    seg = _segmenter()
    # Single speech frame (20ms) below speech_start (40ms) then silence.
    events = _run(seg, [0.9, 0.1, 0.1])
    assert events == []
    assert seg.state is VadState.IDLE


def test_flush_forces_finalization_even_when_short() -> None:
    seg = _segmenter()
    # Confirm speech (40ms, below min_speech) then force a session-end flush.
    _run(seg, [0.9, 0.9])
    events = seg.flush(FinalReason.SESSION_END)
    assert len(events) == 1
    final = events[0]
    assert isinstance(final, UtteranceFinalized)
    assert final.utterance.final_reason is FinalReason.SESSION_END
    assert seg.state is VadState.IDLE


def test_flush_during_speech_starting_discards() -> None:
    seg = _segmenter()
    seg.process_frame(SPEECH, 0.9)  # SPEECH_STARTING, not yet confirmed
    assert seg.state is VadState.SPEECH_STARTING
    events = seg.flush(FinalReason.CLIENT_FLUSH)
    assert events == []
    assert seg.state is VadState.IDLE


def test_no_preroll_when_padding_zero() -> None:
    config = VadConfig(
        threshold=0.5,
        speech_start_ms=40,
        min_speech_ms=40,
        soft_silence_ms=60,
        hard_silence_ms=120,
        speech_pad_before_ms=0,
        speech_pad_after_ms=0,
        max_utterance_ms=400,
    )
    seg = UtteranceSegmenter(source=StreamSource.LOOPBACK, config=config, frame_ms=FRAME_MS)
    # 2 idle then speech; with zero pre-roll the utterance starts at the first
    # speech frame (idle advanced the clock to 40ms).
    events: list = []  # type: ignore[type-arg]
    for prob in [0.1, 0.1, 0.9, 0.9]:
        pcm = SPEECH if prob >= config.threshold else SILENCE
        events.extend(seg.process_frame(pcm, prob))
    started = next(e for e in events if isinstance(e, SpeechStarted))
    assert started.start_ms == 40


def test_two_sequential_utterances_increment_ids() -> None:
    seg = _segmenter()
    _run(seg, [0.9, 0.9, 0.9] + [0.1] * 6)  # first utterance -> finalize
    events = _run(seg, [0.9, 0.9, 0.9] + [0.1] * 6)  # second utterance
    finals = [e for e in events if isinstance(e, UtteranceFinalized)]
    assert len(finals) == 1
    assert finals[0].utterance.utterance_id == "utt-00002"
