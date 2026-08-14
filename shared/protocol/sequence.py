"""Per-stream sequence tracking with duplicate detection and ack calculation.

Each audio stream carries a monotonically increasing ``sequence_number``. The
tracker computes the last contiguously received sequence (for ``audio.ack``),
idempotently ignores duplicates, and buffers out-of-order arrivals until the
gap is filled. Large gaps are surfaced via :attr:`SequenceTracker.pending_count`
and :attr:`SequenceTracker.gap_size` for policy decisions.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ObserveResult:
    """Outcome of observing a single sequence number."""

    sequence_number: int
    is_duplicate: bool
    accepted: bool
    last_contiguous: int
    advanced: bool


class SequenceTracker:
    """Track received sequence numbers for one stream.

    ``start`` is the first expected sequence number. Before any packet is
    accepted, :attr:`last_contiguous` is ``start - 1``.
    """

    def __init__(self, start: int = 0) -> None:
        if start < 0:
            raise ValueError("start must be >= 0")
        self._start = start
        self._last_contiguous = start - 1
        self._pending: set[int] = set()
        self._highest_seen: int | None = None

    @property
    def start(self) -> int:
        return self._start

    @property
    def last_contiguous(self) -> int:
        """Highest sequence number received with no preceding gap."""
        return self._last_contiguous

    @property
    def has_contiguous(self) -> bool:
        """True once at least one contiguous sequence has been accepted."""
        return self._last_contiguous >= self._start

    @property
    def pending_count(self) -> int:
        """Number of accepted-but-not-yet-contiguous (buffered) sequences."""
        return len(self._pending)

    @property
    def highest_seen(self) -> int | None:
        """Highest sequence number observed (duplicate or not), if any."""
        return self._highest_seen

    @property
    def gap_size(self) -> int:
        """Count of missing sequences between last_contiguous and highest_seen."""
        if self._highest_seen is None:
            return 0
        span = self._highest_seen - self._last_contiguous
        if span <= 0:
            return 0
        # span includes highest_seen itself; subtract the buffered pending ones.
        return span - len(self._pending)

    def observe(self, sequence_number: int) -> ObserveResult:
        """Observe a sequence number and return the resulting state."""
        if sequence_number < 0:
            raise ValueError("sequence_number must be >= 0")

        if self._highest_seen is None or sequence_number > self._highest_seen:
            self._highest_seen = sequence_number

        # Already covered by the contiguous run, or already buffered => duplicate.
        if sequence_number <= self._last_contiguous or sequence_number in self._pending:
            return ObserveResult(
                sequence_number=sequence_number,
                is_duplicate=True,
                accepted=False,
                last_contiguous=self._last_contiguous,
                advanced=False,
            )

        self._pending.add(sequence_number)
        before = self._last_contiguous
        while (self._last_contiguous + 1) in self._pending:
            self._pending.remove(self._last_contiguous + 1)
            self._last_contiguous += 1

        return ObserveResult(
            sequence_number=sequence_number,
            is_duplicate=False,
            accepted=True,
            last_contiguous=self._last_contiguous,
            advanced=self._last_contiguous > before,
        )
