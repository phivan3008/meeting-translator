"""Tests for acknowledgement batching."""

from __future__ import annotations

import pytest

from server.transport.acks import AckBatcher


def test_emits_after_packet_threshold() -> None:
    batcher = AckBatcher(every_packets=3, every_ms=10_000)
    assert batcher.record(0, now_ms=0) is None
    assert batcher.record(1, now_ms=1) is None
    # Third packet reaches the count threshold.
    assert batcher.record(2, now_ms=2) == 2
    # Counter resets; next two are below threshold again.
    assert batcher.record(3, now_ms=3) is None


def test_emits_after_time_interval() -> None:
    batcher = AckBatcher(every_packets=1000, every_ms=100)
    assert batcher.record(0, now_ms=0) is None
    # Time threshold reached even though packet count is far below.
    assert batcher.record(1, now_ms=100) == 1


def test_no_emit_without_advance() -> None:
    batcher = AckBatcher(every_packets=1, every_ms=1)
    assert batcher.record(5, now_ms=0) == 5
    # Same contiguous position -> nothing new to acknowledge.
    assert batcher.record(5, now_ms=100) is None


def test_flush_emits_only_on_advance() -> None:
    batcher = AckBatcher(every_packets=100, every_ms=100)
    batcher.record(2, now_ms=0)
    assert batcher.flush(4, now_ms=5) == 4
    assert batcher.flush(4, now_ms=6) is None


def test_invalid_configuration_rejected() -> None:
    with pytest.raises(ValueError):
        AckBatcher(every_packets=0, every_ms=10)
    with pytest.raises(ValueError):
        AckBatcher(every_packets=1, every_ms=0)
