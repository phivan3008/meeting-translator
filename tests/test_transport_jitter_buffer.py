"""Tests for the per-stream jitter/reorder buffer."""

from __future__ import annotations

import pytest

from server.transport.jitter_buffer import JitterBuffer
from shared.protocol.binary import AudioFrameHeader
from shared.protocol.enums import PROTOCOL_VERSION


def _header(seq: int) -> AudioFrameHeader:
    return AudioFrameHeader(
        protocol_version=PROTOCOL_VERSION,
        stream_number=1,
        flags=0,
        sequence_number=seq,
        client_timestamp_ms=1000 + seq,
        payload_length=2,
    )


def _payload(seq: int) -> bytes:
    return seq.to_bytes(2, "big")


def _offer(buffer: JitterBuffer, seq: int):  # type: ignore[no-untyped-def]
    return buffer.offer(_header(seq), _payload(seq))


def test_in_order_releases_immediately() -> None:
    buffer = JitterBuffer(start=0, capacity=8)
    released_seqs = []
    for seq in range(4):
        result = _offer(buffer, seq)
        released_seqs.extend(f.sequence_number for f in result.released)
    assert released_seqs == [0, 1, 2, 3]
    assert buffer.last_contiguous == 3
    assert buffer.pending_count == 0


def test_out_of_order_buffers_then_releases_contiguously() -> None:
    buffer = JitterBuffer(start=0, capacity=8)
    # Deliver 0, then 2 (gap), then 1 fills the gap.
    assert [f.sequence_number for f in _offer(buffer, 0).released] == [0]
    gap = _offer(buffer, 2)
    assert gap.released == ()
    assert buffer.pending_count == 1
    filled = _offer(buffer, 1)
    assert [f.sequence_number for f in filled.released] == [1, 2]
    assert buffer.last_contiguous == 2


def test_duplicate_in_window_is_ignored() -> None:
    buffer = JitterBuffer(start=0, capacity=8)
    _offer(buffer, 0)
    _offer(buffer, 2)  # buffered
    dup = _offer(buffer, 2)
    assert dup.duplicate is True
    assert dup.stale is False
    assert dup.released == ()


def test_stale_below_contiguous_is_reported() -> None:
    buffer = JitterBuffer(start=0, capacity=8)
    _offer(buffer, 0)
    _offer(buffer, 1)
    stale = _offer(buffer, 0)
    assert stale.duplicate is True
    assert stale.stale is True
    assert stale.released == ()


def test_overflow_forces_advance_and_reports_loss() -> None:
    buffer = JitterBuffer(start=0, capacity=2)
    # Waiting for 0; buffer 1,2 (capacity=2). Offering 3 overflows.
    _offer(buffer, 1)
    _offer(buffer, 2)
    assert buffer.pending_count == 2
    overflow = _offer(buffer, 3)
    # Missing seq 0 is skipped; 1,2,3 release contiguously.
    assert overflow.overflow_skipped == 1
    assert [f.sequence_number for f in overflow.released] == [1, 2, 3]
    assert buffer.last_contiguous == 3


def test_invalid_configuration_rejected() -> None:
    with pytest.raises(ValueError):
        JitterBuffer(start=-1, capacity=4)
    with pytest.raises(ValueError):
        JitterBuffer(start=0, capacity=0)
