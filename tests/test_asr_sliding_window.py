"""Tests for the sliding audio window used by streaming partial decode."""

from __future__ import annotations

import pytest

from server.asr.sliding_window import SlidingAudioWindow
from server.asr.types import BYTES_PER_MS


def _pcm(ms: int) -> bytes:
    return bytes(ms * BYTES_PER_MS)


def test_rejects_negative_overlap() -> None:
    with pytest.raises(ValueError):
        SlidingAudioWindow(overlap_ms=-1)


def test_initial_state_is_empty() -> None:
    window = SlidingAudioWindow(overlap_ms=200)
    assert window.window() == b""
    assert window.buffered_ms == 0
    assert window.window_start_ms == 0


def test_append_accumulates() -> None:
    window = SlidingAudioWindow(overlap_ms=200)
    window.append(_pcm(100))
    assert window.buffered_ms == 100
    window.append(_pcm(50))
    assert window.buffered_ms == 150
    assert window.window() == _pcm(150)


def test_append_ignores_empty_chunk() -> None:
    window = SlidingAudioWindow(overlap_ms=200)
    window.append(b"")
    assert window.buffered_ms == 0


def test_advance_noop_when_boundary_not_positive() -> None:
    window = SlidingAudioWindow(overlap_ms=200)
    window.append(_pcm(100))
    assert window.advance(0) is False
    assert window.advance(-5) is False
    assert window.buffered_ms == 100
    assert window.window_start_ms == 0


def test_advance_keeps_overlap_margin() -> None:
    window = SlidingAudioWindow(overlap_ms=200)
    window.append(_pcm(1000))
    trimmed = window.advance(600)
    assert trimmed is True
    assert window.window_start_ms == 400
    assert window.buffered_ms == 600
    assert window.window() == _pcm(600)


def test_advance_clamped_at_zero_when_overlap_exceeds_boundary() -> None:
    window = SlidingAudioWindow(overlap_ms=1000)
    window.append(_pcm(500))
    trimmed = window.advance(300)
    assert trimmed is False
    assert window.window_start_ms == 0
    assert window.buffered_ms == 500


def test_advance_clamps_boundary_to_buffered_length() -> None:
    # A boundary beyond what is actually buffered (e.g. inconsistent segment
    # timestamps from a backend) must never drop more than is buffered.
    window = SlidingAudioWindow(overlap_ms=0)
    window.append(_pcm(100))
    trimmed = window.advance(500)
    assert trimmed is True
    assert window.window_start_ms == 100
    assert window.buffered_ms == 0


def test_advance_is_relative_to_current_window() -> None:
    window = SlidingAudioWindow(overlap_ms=100)
    window.append(_pcm(1000))
    window.advance(500)
    assert window.window_start_ms == 400
    assert window.buffered_ms == 600

    window.append(_pcm(200))
    assert window.buffered_ms == 800

    trimmed = window.advance(300)
    assert trimmed is True
    assert window.window_start_ms == 600
    assert window.buffered_ms == 600
