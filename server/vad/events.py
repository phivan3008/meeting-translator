"""Events emitted by the utterance state machine.

Each event is an immutable dataclass carrying a :class:`VadEventType`
discriminator. ``UtteranceFinalized`` carries the finalized
:class:`~server.vad.types.Utterance` snapshot.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from server.vad.types import Utterance


class VadEventType(Enum):
    """Discriminator for VAD/utterance events."""

    SPEECH_STARTED = "speech_started"
    SOFT_SILENCE = "soft_silence"
    RESUMED_SPEECH = "resumed_speech"
    UTTERANCE_FINALIZED = "utterance_finalized"
    UTTERANCE_ABANDONED = "utterance_abandoned"


@dataclass(frozen=True)
class SpeechStarted:
    """Speech has been confirmed and an utterance opened."""

    type = VadEventType.SPEECH_STARTED
    utterance_id: str
    start_ms: int


@dataclass(frozen=True)
class SoftSilence:
    """A soft-silence gap was detected inside an open utterance."""

    type = VadEventType.SOFT_SILENCE
    utterance_id: str
    at_ms: int


@dataclass(frozen=True)
class ResumedSpeech:
    """Speech resumed after a soft-silence gap; the utterance continues."""

    type = VadEventType.RESUMED_SPEECH
    utterance_id: str
    at_ms: int


@dataclass(frozen=True)
class UtteranceFinalized:
    """An utterance was finalized (by silence, max length or forced flush)."""

    type = VadEventType.UTTERANCE_FINALIZED
    utterance: Utterance


@dataclass(frozen=True)
class UtteranceAbandoned:
    """A confirmed utterance was discarded without finalizing.

    Emitted when hard silence (or max-utterance) is reached but too little
    confirmed speech accumulated (below ``min_speech_ms``) to treat it as a
    real utterance -- e.g. a brief noise blip. No transcript or translation
    is produced, and by design the client is not notified either (this
    mirrors the pre-existing "not a real utterance" filtering intent).
    This event exists purely so orchestration layers can release any
    per-utterance state (partial ASR buffers, decode scheduling) instead of
    leaking it forever on an utterance_id that will never finalize.
    """

    type = VadEventType.UTTERANCE_ABANDONED
    utterance_id: str
    speech_ms: int


VadEvent = SpeechStarted | SoftSilence | ResumedSpeech | UtteranceFinalized | UtteranceAbandoned
