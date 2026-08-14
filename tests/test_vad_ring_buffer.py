"""Tests for the pre-roll ring buffer and the scripted VAD model."""

from __future__ import annotations

import pytest

from server.vad.fake import ScriptedVadModel
from server.vad.ring_buffer import PreRollBuffer


def _frame(marker: int) -> bytes:
    return bytes([marker]) * 4


def test_ring_buffer_retains_last_frames() -> None:
    buffer = PreRollBuffer(capacity_ms=40, frame_ms=20)  # 2 frames
    assert buffer.max_frames == 2
    buffer.push(_frame(1))
    buffer.push(_frame(2))
    buffer.push(_frame(3))  # evicts frame(1)
    assert buffer.snapshot() == _frame(2) + _frame(3)


def test_ring_buffer_clear() -> None:
    buffer = PreRollBuffer(capacity_ms=40, frame_ms=20)
    buffer.push(_frame(1))
    buffer.clear()
    assert buffer.snapshot() == b""


def test_ring_buffer_zero_capacity_is_empty() -> None:
    buffer = PreRollBuffer(capacity_ms=0, frame_ms=20)
    assert buffer.max_frames == 0
    buffer.push(_frame(1))
    assert buffer.snapshot() == b""


def test_scripted_model_returns_then_repeats_last() -> None:
    model = ScriptedVadModel([0.9, 0.1])
    assert model.probability(b"") == pytest.approx(0.9)
    assert model.probability(b"") == pytest.approx(0.1)
    # Exhausted -> repeats the last value.
    assert model.probability(b"") == pytest.approx(0.1)
    model.reset()
    assert model.probability(b"") == pytest.approx(0.9)


def test_scripted_model_rejects_bad_input() -> None:
    with pytest.raises(ValueError):
        ScriptedVadModel([])
    with pytest.raises(ValueError):
        ScriptedVadModel([1.5])
