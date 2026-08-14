"""Value types, configuration and result models for final ASR.

These types are framework-independent (no asyncio, FastAPI, CUDA or model
weights) so the ASR domain logic and error mapping are fully unit-testable.
Audio is the normalized pipeline format: mono 16 kHz PCM S16LE.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from shared.protocol.enums import Language

# Normalized audio format (docs/ARCHITECTURE.md).
SAMPLE_RATE_HZ = 16000
SAMPLE_WIDTH_BYTES = 2
# Bytes of PCM S16LE mono per millisecond: 16000 * 2 / 1000 = 32.
BYTES_PER_MS = SAMPLE_RATE_HZ * SAMPLE_WIDTH_BYTES // 1000


@dataclass(frozen=True)
class AsrConfig:
    """faster-whisper decoding configuration for final reconciliation.

    Mirrors the ``docs/ARCHITECTURE.md`` ASR baseline. ``final_beam_size`` and
    ``temperature`` control the deterministic final decode; ``initial_prompt``
    conditioning is enabled via ``condition_on_previous_text``.
    """

    model: str = "large-v3"
    device: str = "cuda"
    compute_type: str = "float16"
    final_beam_size: int = 3
    partial_beam_size: int = 1
    temperature: float = 0.0
    condition_on_previous_text: bool = True

    def __post_init__(self) -> None:
        if not self.model:
            raise ValueError("model must be a non-empty string")
        if not self.device:
            raise ValueError("device must be a non-empty string")
        if not self.compute_type:
            raise ValueError("compute_type must be a non-empty string")
        if self.final_beam_size < 1:
            raise ValueError("final_beam_size must be >= 1")
        if self.partial_beam_size < 1:
            raise ValueError("partial_beam_size must be >= 1")
        if self.temperature < 0.0:
            raise ValueError("temperature must be >= 0")

    @classmethod
    def from_settings(cls, settings: object) -> AsrConfig:
        """Build a config from an application settings object.

        Reads the ``whisper_*`` fields; any missing attribute falls back to the
        documented baseline default.
        """
        return cls(
            model=str(getattr(settings, "whisper_model", cls.model)),
            device=str(getattr(settings, "whisper_device", cls.device)),
            compute_type=str(getattr(settings, "whisper_compute_type", cls.compute_type)),
            final_beam_size=int(getattr(settings, "whisper_final_beam_size", cls.final_beam_size)),
            partial_beam_size=int(
                getattr(settings, "whisper_partial_beam_size", cls.partial_beam_size)
            ),
            temperature=float(getattr(settings, "whisper_temperature", cls.temperature)),
            condition_on_previous_text=bool(
                getattr(
                    settings,
                    "whisper_condition_on_previous_text",
                    cls.condition_on_previous_text,
                )
            ),
        )


@dataclass(frozen=True)
class AsrRequest:
    """A single decode request over completed utterance audio.

    ``audio`` is mono 16 kHz PCM S16LE. ``previous_text`` is the optional
    conditioning prompt (used only when the config enables it).
    """

    audio: bytes
    language: Language
    beam_size: int
    temperature: float
    condition_on_previous_text: bool
    previous_text: str | None = None

    @property
    def duration_ms(self) -> int:
        """Audio duration in milliseconds derived from the PCM byte length."""
        return len(self.audio) // BYTES_PER_MS


@dataclass(frozen=True)
class TranscriptionSegment:
    """A decoded segment with millisecond-relative timestamps."""

    text: str
    start_ms: int
    end_ms: int
    avg_logprob: float | None = None


@dataclass(frozen=True)
class TranscriptionResult:
    """The authoritative final transcription for an utterance."""

    text: str
    language: Language
    duration_ms: int
    segments: tuple[TranscriptionSegment, ...] = field(default_factory=tuple)
