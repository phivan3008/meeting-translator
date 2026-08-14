"""Bounded outbound frame buffer for the client sender.

Encoded audio packets are appended per stream while awaiting server
acknowledgement. On reconnect, unacknowledged frames are resent in order;
because the server deduplicates by sequence number, resending is idempotent.
The buffer is bounded: under sustained overflow the oldest unacknowledged
frames are dropped (reported via :attr:`OutboundBuffer.dropped`).
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass


@dataclass(frozen=True)
class PendingFrame:
    """An encoded packet awaiting acknowledgement."""

    sequence_number: int
    packet: bytes


class OutboundBuffer:
    """Bounded FIFO of unacknowledged frames for a single stream."""

    def __init__(self, *, capacity: int) -> None:
        if capacity < 1:
            raise ValueError("capacity must be >= 1")
        self._capacity = capacity
        self._frames: deque[PendingFrame] = deque()
        self.added = 0
        self.dropped = 0
        self.acked = 0

    def __len__(self) -> int:
        return len(self._frames)

    @property
    def capacity(self) -> int:
        return self._capacity

    def add(self, sequence_number: int, packet: bytes) -> bool:
        """Append a frame. Returns False if an oldest frame was dropped."""
        self._frames.append(PendingFrame(sequence_number=sequence_number, packet=packet))
        self.added += 1
        if len(self._frames) > self._capacity:
            self._frames.popleft()
            self.dropped += 1
            return False
        return True

    def ack(self, last_contiguous: int) -> int:
        """Drop frames with sequence <= ``last_contiguous``. Returns the count."""
        removed = 0
        while self._frames and self._frames[0].sequence_number <= last_contiguous:
            self._frames.popleft()
            removed += 1
        self.acked += removed
        return removed

    def pending(self) -> tuple[PendingFrame, ...]:
        """Return unacknowledged frames in order (for resend)."""
        return tuple(self._frames)
