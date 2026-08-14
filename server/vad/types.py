"""Value types, constants and configuration for VAD and utterance segmentation.

These types are framework-independent (no asyncio, Qt, CUDA or model weights)
so the utterance state machine is fully unit-testable. Audio is the normalized
pipeline format: mono 16 kHz PCM S16LE.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from shared.protocol.enums import FinalReason, StreamSource

# Normalized audio format (docs/ARCHITECTURE.md).
SAMPLE_RATE_HZ = 16000
SAMPLE_WIDTH_BYTES = 2
# Bytes of PCM S16LE mono per millisecond: 16000 * 2 / 1000 = 32.
BYTES_PER_MS = SAMPLE_RATE_HZ * SAMPLE_WIDTH_BYTES // 1000


class VadState(Enum):
    """Per-stream utterance segmentation state."""

    IDLE = "idle"
    SPEECH_STARTING = "speech_starting"
    SPEAKING = "speaking"
    POSSIBLE_END = "possible_end"
    FINALIZING = "finalizing"


@dataclass(frozen=True)
class VadConfig:
    """Utterance segmentation thresholds (all durations in milliseconds)."""

    threshold: float = 0.5
    speech_start_ms: int = 160
    min_speech_ms: int = 250
    soft_silence_ms: int = 450
    hard_silence_ms: int = 900
    speech_pad_before_ms: int = 200
    speech_pad_after_ms: int = 250
    max_utterance_ms: int = 15000

    def __post_init__(self) -> None:
        if not 0.0 <= self.threshold <= 1.0:
            raise ValueError("threshold must be in [0, 1]")
        for name in (
            "speech_start_ms",
            "min_speech_ms",
            "soft_silence_ms",
            "hard_silence_ms",
            "speech_pad_before_ms",
            "speech_pad_after_ms",
        ):
            if getattr(self, name) < 0:
                raise ValueError(f"{name} must be >= 0")
        if self.max_utterance_ms < 1:
            raise ValueError("max_utterance_ms must be >= 1")
        if self.hard_silence_ms < self.soft_silence_ms:
            raise ValueError("hard_silence_ms must be >= soft_silence_ms")

    @classmethod
    def from_settings(cls, settings: object) -> VadConfig:
        """Build a config from an application settings object.

        Reads the ``vad_*`` fields; any missing attribute falls back to the
        documented baseline default.
        """

        def _get(name: str, default: float | int) -> float | int:
            value = getattr(settings, name, default)
            return value if value is not None else default

        return cls(
            threshold=float(_get("vad_threshold", cls.threshold)),
            speech_start_ms=int(_get("vad_speech_start_ms", cls.speech_start_ms)),
            min_speech_ms=int(_get("vad_min_speech_ms", cls.min_speech_ms)),
            soft_silence_ms=int(_get("vad_soft_silence_ms", cls.soft_silence_ms)),
            hard_silence_ms=int(_get("vad_hard_silence_ms", cls.hard_silence_ms)),
            speech_pad_before_ms=int(_get("vad_speech_pad_before_ms", cls.speech_pad_before_ms)),
            speech_pad_after_ms=int(_get("vad_speech_pad_after_ms", cls.speech_pad_after_ms)),
            max_utterance_ms=int(_get("vad_max_utterance_ms", cls.max_utterance_ms)),
        )


@dataclass(frozen=True)
class Utterance:
    """An immutable finalized utterance snapshot.

    ``audio`` is the buffered PCM (mono 16 kHz S16LE) including pre-roll and up
    to ``speech_pad_after_ms`` of trailing silence.
    """

    utterance_id: str
    source: StreamSource
    start_ms: int
    end_ms: int
    speech_ms: int
    final_reason: FinalReason
    audio: bytes
