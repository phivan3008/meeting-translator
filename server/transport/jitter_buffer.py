"""Per-stream jitter/reorder buffer.

Audio packets may arrive out of order or be duplicated. The jitter buffer holds
future packets until the missing predecessors arrive, then releases them in
contiguous order. It is bounded: when the number of buffered out-of-order
packets would exceed ``capacity``, the buffer force-advances past the missing
range (reporting the loss) so memory and latency stay bounded, matching the
"small gaps as silence, large gaps reported" policy in ``docs/PROTOCOL.md``.
"""

from __future__ import annotations

from dataclasses import dataclass

from shared.protocol.binary import AudioFrameHeader


@dataclass(frozen=True)
class ReleasedFrame:
    """A packet released from the buffer in contiguous order."""

    sequence_number: int
    header: AudioFrameHeader
    payload: bytes


@dataclass(frozen=True)
class OfferResult:
    """Outcome of offering one packet to the buffer."""

    accepted: bool
    duplicate: bool
    stale: bool
    overflow_skipped: int
    released: tuple[ReleasedFrame, ...]
    last_contiguous: int


class JitterBuffer:
    """Reorder buffer for a single stream.

    ``start`` is the first expected sequence number. ``capacity`` bounds the
    number of out-of-order packets buffered before a forced advance.
    """

    def __init__(self, *, start: int = 0, capacity: int = 64) -> None:
        if start < 0:
            raise ValueError("start must be >= 0")
        if capacity < 1:
            raise ValueError("capacity must be >= 1")
        self._next_expected = start
        self._capacity = capacity
        self._buffered: dict[int, tuple[AudioFrameHeader, bytes]] = {}

    @property
    def last_contiguous(self) -> int:
        """Highest sequence number released so far (start - 1 before any)."""
        return self._next_expected - 1

    @property
    def next_expected(self) -> int:
        return self._next_expected

    @property
    def pending_count(self) -> int:
        return len(self._buffered)

    def offer(self, header: AudioFrameHeader, payload: bytes) -> OfferResult:
        """Offer a packet; return released frames and buffer state."""
        seq = header.sequence_number

        # Already released (or skipped past): stale duplicate.
        if seq < self._next_expected:
            return OfferResult(
                accepted=False,
                duplicate=True,
                stale=True,
                overflow_skipped=0,
                released=(),
                last_contiguous=self.last_contiguous,
            )

        # Already buffered: in-window duplicate.
        if seq in self._buffered:
            return OfferResult(
                accepted=False,
                duplicate=True,
                stale=False,
                overflow_skipped=0,
                released=(),
                last_contiguous=self.last_contiguous,
            )

        self._buffered[seq] = (header, payload)

        overflow_skipped = 0
        if len(self._buffered) > self._capacity:
            # Bound memory/latency: skip the missing prefix and resume at the
            # smallest buffered sequence. The skipped span is reported as loss.
            smallest = min(self._buffered)
            overflow_skipped = smallest - self._next_expected
            self._next_expected = smallest

        released = self._drain()
        return OfferResult(
            accepted=True,
            duplicate=False,
            stale=False,
            overflow_skipped=overflow_skipped,
            released=released,
            last_contiguous=self.last_contiguous,
        )

    def _drain(self) -> tuple[ReleasedFrame, ...]:
        out: list[ReleasedFrame] = []
        while self._next_expected in self._buffered:
            header, payload = self._buffered.pop(self._next_expected)
            out.append(
                ReleasedFrame(
                    sequence_number=self._next_expected,
                    header=header,
                    payload=payload,
                )
            )
            self._next_expected += 1
        return tuple(out)
