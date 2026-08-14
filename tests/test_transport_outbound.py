"""Tests for the bounded outbound frame buffer."""

from __future__ import annotations

import pytest

from client.transport.outbound import OutboundBuffer


def _packet(seq: int) -> bytes:
    return f"packet-{seq}".encode()


def test_add_and_pending_order() -> None:
    buffer = OutboundBuffer(capacity=8)
    for seq in range(3):
        assert buffer.add(seq, _packet(seq)) is True
    pending = buffer.pending()
    assert [f.sequence_number for f in pending] == [0, 1, 2]
    assert buffer.added == 3


def test_ack_drops_up_to_last_contiguous() -> None:
    buffer = OutboundBuffer(capacity=8)
    for seq in range(5):
        buffer.add(seq, _packet(seq))
    removed = buffer.ack(2)
    assert removed == 3
    assert [f.sequence_number for f in buffer.pending()] == [3, 4]
    assert buffer.acked == 3


def test_overflow_drops_oldest() -> None:
    buffer = OutboundBuffer(capacity=2)
    assert buffer.add(0, _packet(0)) is True
    assert buffer.add(1, _packet(1)) is True
    # Third add exceeds capacity -> oldest (seq 0) dropped.
    assert buffer.add(2, _packet(2)) is False
    assert [f.sequence_number for f in buffer.pending()] == [1, 2]
    assert buffer.dropped == 1


def test_capacity_must_be_positive() -> None:
    with pytest.raises(ValueError):
        OutboundBuffer(capacity=0)
