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


VadEvent = SpeechStarted | SoftSilence | ResumedSpeech | UtteranceFinalized
