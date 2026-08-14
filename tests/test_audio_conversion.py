"""Tests for audio normalization (downmix, resample, packetization)."""

from __future__ import annotations

import numpy as np

from client.audio.conversion import (
    FrameAssembler,
    convert_to_mono_16k_s16le,
    downmix_to_mono,
    resample_to_target,
)
from client.audio.types import FRAME_BYTES, AudioFormat

_S16LE = np.dtype("<i2")


def _pcm(samples: list[int], channels: int = 1) -> bytes:
    return np.array(samples, dtype=_S16LE).tobytes()


def test_downmix_averages_channels() -> None:
    # Two channels: [100, 200] and [300, 400] interleaved.
    interleaved = np.array([100, 300, 200, 400], dtype=np.int16).reshape(-1, 2)
    mono = downmix_to_mono(interleaved)
    assert mono.tolist() == [200, 300]


def test_downmix_mono_passthrough() -> None:
    mono_in = np.array([1, 2, 3], dtype=np.int16).reshape(-1, 1)
    mono = downmix_to_mono(mono_in)
    assert mono.tolist() == [1, 2, 3]


def test_resample_passthrough_when_already_target() -> None:
    mono = np.array([10, 20, 30], dtype=np.int16)
    out = resample_to_target(mono, 16000)
    assert out.tolist() == [10, 20, 30]


def test_resample_downsamples_length() -> None:
    # 48 kHz -> 16 kHz should reduce sample count by ~3x.
    mono = np.zeros(48000, dtype=np.int16)
    out = resample_to_target(mono, 48000)
    assert out.size == 16000


def test_convert_produces_mono_16k_bytes() -> None:
    fmt = AudioFormat(sample_rate=48000, channels=2)
    # 480 stereo sample-frames (10 ms at 48k) -> 160 mono samples (10 ms at 16k).
    interleaved = np.zeros(480 * 2, dtype=_S16LE).tobytes()
    out = convert_to_mono_16k_s16le(interleaved, fmt)
    assert len(out) == 160 * 2  # 160 samples * 2 bytes


def test_convert_empty_input() -> None:
    fmt = AudioFormat(sample_rate=48000, channels=2)
    assert convert_to_mono_16k_s16le(b"", fmt) == b""


def test_frame_assembler_emits_640_byte_frames() -> None:
    assembler = FrameAssembler()
    # Feed 1.5 frames worth of bytes.
    frames = assembler.push(b"\x00" * (FRAME_BYTES + FRAME_BYTES // 2))
    assert len(frames) == 1
    assert len(frames[0]) == FRAME_BYTES
    assert assembler.buffered_bytes == FRAME_BYTES // 2
    # Feed the remaining half; a second frame completes.
    frames2 = assembler.push(b"\x00" * (FRAME_BYTES // 2))
    assert len(frames2) == 1
    assert assembler.buffered_bytes == 0


def test_frame_assembler_flush_pads() -> None:
    assembler = FrameAssembler()
    assembler.push(b"\x01" * 100)
    padded = assembler.flush(pad=True)
    assert padded is not None
    assert len(padded) == FRAME_BYTES
    assert assembler.flush() is None
