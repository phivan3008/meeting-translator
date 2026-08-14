"""Audio normalization: downmix to mono and resample to 16 kHz PCM S16LE.

Conversion is deterministic (linear interpolation) so it can be unit tested on
Linux without any audio hardware. The :class:`FrameAssembler` packetizes the
normalized stream into fixed 20 ms (640-byte) frames, buffering any remainder.
"""

from __future__ import annotations

import numpy as np
import numpy.typing as npt

from client.audio.types import (
    FRAME_BYTES,
    TARGET_SAMPLE_RATE,
    AudioFormat,
)

# Little-endian signed 16-bit PCM sample type.
_S16LE = np.dtype("<i2")
_INT16_MIN = -32768
_INT16_MAX = 32767


def _decode_s16le(data: bytes, channels: int) -> npt.NDArray[np.int16]:
    """Decode interleaved S16LE bytes into an (n_samples, channels) array."""
    if not data:
        return np.zeros((0, channels), dtype=np.int16)
    flat = np.frombuffer(data, dtype=_S16LE)
    usable = (flat.size // channels) * channels
    return flat[:usable].reshape(-1, channels)


def downmix_to_mono(samples: npt.NDArray[np.int16]) -> npt.NDArray[np.int16]:
    """Average interleaved channels into a single mono channel."""
    if samples.shape[0] == 0:
        return np.zeros(0, dtype=np.int16)
    if samples.shape[1] == 1:
        return samples.reshape(-1)
    mono = samples.astype(np.float64).mean(axis=1)
    clipped = np.clip(np.rint(mono), _INT16_MIN, _INT16_MAX)
    return clipped.astype(np.int16)


def resample_to_target(mono: npt.NDArray[np.int16], source_rate: int) -> npt.NDArray[np.int16]:
    """Resample a mono int16 signal to ``TARGET_SAMPLE_RATE`` via linear interp."""
    if source_rate == TARGET_SAMPLE_RATE or mono.size == 0:
        return mono
    n_in = mono.size
    n_out = int(round(n_in * TARGET_SAMPLE_RATE / source_rate))
    if n_out <= 0:
        return np.zeros(0, dtype=np.int16)
    if n_in == 1:
        return np.full(n_out, mono[0], dtype=np.int16)
    x_old = np.arange(n_in, dtype=np.float64)
    x_new = np.linspace(0.0, n_in - 1, n_out, dtype=np.float64)
    y_new = np.interp(x_new, x_old, mono.astype(np.float64))
    clipped = np.clip(np.rint(y_new), _INT16_MIN, _INT16_MAX)
    return clipped.astype(np.int16)


def convert_to_mono_16k_s16le(data: bytes, audio_format: AudioFormat) -> bytes:
    """Convert raw interleaved PCM S16LE to mono 16 kHz PCM S16LE bytes."""
    samples = _decode_s16le(data, audio_format.channels)
    mono = downmix_to_mono(samples)
    resampled = resample_to_target(mono, audio_format.sample_rate)
    # Ensure little-endian on-wire byte order regardless of host endianness.
    return bytes(resampled.astype(_S16LE).tobytes())


class FrameAssembler:
    """Accumulates normalized mono 16 kHz bytes into fixed 20 ms frames."""

    def __init__(self) -> None:
        self._buffer = bytearray()

    @property
    def buffered_bytes(self) -> int:
        return len(self._buffer)

    def push(self, pcm: bytes) -> list[bytes]:
        """Append normalized bytes and return any complete 640-byte frames."""
        self._buffer.extend(pcm)
        frames: list[bytes] = []
        while len(self._buffer) >= FRAME_BYTES:
            frames.append(bytes(self._buffer[:FRAME_BYTES]))
            del self._buffer[:FRAME_BYTES]
        return frames

    def flush(self, pad: bool = False) -> bytes | None:
        """Return any remaining buffered bytes.

        If ``pad`` is True, the remainder is zero-padded to a full 640-byte
        frame; otherwise the raw remainder is returned. Returns None if empty.
        """
        if not self._buffer:
            return None
        remainder = bytes(self._buffer)
        self._buffer.clear()
        if pad and len(remainder) < FRAME_BYTES:
            remainder = remainder + b"\x00" * (FRAME_BYTES - len(remainder))
        return remainder
