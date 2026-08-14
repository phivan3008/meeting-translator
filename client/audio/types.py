"""Value types and constants for audio capture.

Reuses :class:`shared.protocol.enums.StreamSource` so the client and protocol
agree on source identity. All types are plain dataclasses/enums with no audio
library or GPU dependency.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from shared.protocol.enums import StreamSource

# Normalized output format required by the pipeline (docs/ARCHITECTURE.md).
TARGET_SAMPLE_RATE = 16000
TARGET_CHANNELS = 1
SAMPLE_WIDTH_BYTES = 2  # PCM S16LE

# 20 ms output frames.
FRAME_DURATION_MS = 20
FRAME_SAMPLES = TARGET_SAMPLE_RATE * FRAME_DURATION_MS // 1000  # 320
FRAME_BYTES = FRAME_SAMPLES * SAMPLE_WIDTH_BYTES  # 640


class DropPolicy(Enum):
    """Policy applied when a bounded audio queue is full."""

    DROP_NEWEST = "drop_newest"
    DROP_OLDEST = "drop_oldest"


class CaptureEventType(Enum):
    """Lifecycle and health events emitted by a capture context."""

    STARTED = "started"
    STOPPED = "stopped"
    OVERFLOW = "overflow"
    DEVICE_LOST = "device_lost"
    DEVICE_RECONFIGURED = "device_reconfigured"


@dataclass(frozen=True)
class AudioFormat:
    """Describes a raw PCM S16LE stream layout."""

    sample_rate: int
    channels: int
    sample_width: int = SAMPLE_WIDTH_BYTES

    def __post_init__(self) -> None:
        if self.sample_rate <= 0:
            raise ValueError("sample_rate must be positive")
        if self.channels < 1:
            raise ValueError("channels must be >= 1")
        if self.sample_width != SAMPLE_WIDTH_BYTES:
            raise ValueError("only 16-bit PCM (sample_width=2) is supported")

    @property
    def frame_stride_bytes(self) -> int:
        """Bytes for one interleaved sample frame across all channels."""
        return self.channels * self.sample_width


@dataclass(frozen=True)
class DeviceInfo:
    """A capture device discovered from a backend."""

    index: int
    name: str
    max_input_channels: int
    default_sample_rate: int
    is_loopback: bool
    host_api: str = ""


@dataclass(frozen=True)
class RawChunk:
    """A raw capture chunk as enqueued from a capture callback.

    The callback only assigns ``sequence`` and ``capture_timestamp_ms`` and
    enqueues; all conversion happens later in the worker.
    """

    sequence: int
    capture_timestamp_ms: int
    data: bytes
    audio_format: AudioFormat


@dataclass(frozen=True)
class AudioFrame:
    """A normalized 20 ms mono 16 kHz PCM S16LE output frame."""

    stream_number: int
    sequence_number: int
    capture_timestamp_ms: int
    pcm: bytes


@dataclass(frozen=True)
class CaptureEvent:
    """A capture lifecycle/health event."""

    type: CaptureEventType
    source: StreamSource
    detail: str = ""
