"""Tests for per-stream sequence tracking and ack calculation."""

from __future__ import annotations

import pytest

from shared.protocol.sequence import SequenceTracker


def test_in_order_advances_contiguous() -> None:
    tracker = SequenceTracker(start=0)
    assert tracker.has_contiguous is False
    for seq in range(5):
        result = tracker.observe(seq)
        assert result.accepted is True
        assert result.is_duplicate is False
        assert result.last_contiguous == seq
    assert tracker.last_contiguous == 4
    assert tracker.pending_count == 0
    assert tracker.gap_size == 0


def test_duplicate_is_idempotent() -> None:
    tracker = SequenceTracker(start=0)
    tracker.observe(0)
    tracker.observe(1)
    dup = tracker.observe(1)
    assert dup.is_duplicate is True
    assert dup.accepted is False
    assert dup.last_contiguous == 1
    # Re-observing an already-contiguous sequence is also a duplicate.
    dup0 = tracker.observe(0)
    assert dup0.is_duplicate is True


def test_out_of_order_buffers_until_gap_filled() -> None:
    tracker = SequenceTracker(start=0)
    tracker.observe(0)
    # Skip 1, deliver 2 and 3 out of order.
    r2 = tracker.observe(2)
    assert r2.accepted is True
    assert r2.advanced is False
    assert tracker.last_contiguous == 0
    assert tracker.pending_count == 1
    assert tracker.gap_size == 1  # sequence 1 is missing

    r3 = tracker.observe(3)
    assert r3.advanced is False
    assert tracker.pending_count == 2
    assert tracker.gap_size == 1

    # Fill the gap; contiguous run jumps to 3.
    r1 = tracker.observe(1)
    assert r1.accepted is True
    assert r1.advanced is True
    assert tracker.last_contiguous == 3
    assert tracker.pending_count == 0
    assert tracker.gap_size == 0


def test_non_zero_start() -> None:
    tracker = SequenceTracker(start=100)
    assert tracker.last_contiguous == 99
    assert tracker.has_contiguous is False
    r = tracker.observe(100)
    assert r.last_contiguous == 100
    assert tracker.has_contiguous is True
    # A sequence below start is treated as duplicate/already-covered.
    below = tracker.observe(50)
    assert below.is_duplicate is True


def test_highest_seen_tracks_max() -> None:
    tracker = SequenceTracker(start=0)
    tracker.observe(0)
    tracker.observe(10)
    tracker.observe(5)
    assert tracker.highest_seen == 10


def test_negative_inputs_rejected() -> None:
    with pytest.raises(ValueError):
        SequenceTracker(start=-1)
    tracker = SequenceTracker(start=0)
    with pytest.raises(ValueError):
        tracker.observe(-5)


def test_large_gap_reported() -> None:
    tracker = SequenceTracker(start=0)
    tracker.observe(0)
    tracker.observe(1000)
    assert tracker.last_contiguous == 0
    assert tracker.gap_size == 999
    assert tracker.pending_count == 1
