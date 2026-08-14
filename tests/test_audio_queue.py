"""Tests for the bounded audio queue drop policies and counters."""

from __future__ import annotations

from client.audio.queue import BoundedAudioQueue
from client.audio.types import DropPolicy


def test_put_and_get_fifo() -> None:
    q: BoundedAudioQueue[int] = BoundedAudioQueue(maxsize=3)
    assert q.put(1) is True
    assert q.put(2) is True
    assert q.get() == 1
    assert q.get() == 2
    assert q.get() is None


def test_drop_oldest_evicts_and_retains_new() -> None:
    q: BoundedAudioQueue[int] = BoundedAudioQueue(maxsize=2, policy=DropPolicy.DROP_OLDEST)
    q.put(1)
    q.put(2)
    accepted = q.put(3)  # full -> evict 1, keep 3
    assert accepted is True
    assert q.dropped == 1
    assert q.overflow_events == 1
    assert q.depth == 2
    assert q.get() == 2
    assert q.get() == 3


def test_drop_newest_discards_incoming() -> None:
    q: BoundedAudioQueue[int] = BoundedAudioQueue(maxsize=2, policy=DropPolicy.DROP_NEWEST)
    q.put(1)
    q.put(2)
    accepted = q.put(3)  # full -> discard 3
    assert accepted is False
    assert q.dropped == 1
    assert q.overflow_events == 1
    assert q.depth == 2
    assert q.get() == 1
    assert q.get() == 2


def test_counters_track_accepted() -> None:
    q: BoundedAudioQueue[int] = BoundedAudioQueue(maxsize=5)
    for i in range(3):
        q.put(i)
    assert q.accepted == 3
    assert q.dropped == 0
    assert q.drain() == [0, 1, 2]
    assert q.depth == 0
