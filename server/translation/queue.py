"""Priority ordering for translation work: final, retry, completeness.

Pure, synchronous and dependency-free (matches the style of
``server.transport.acks.AckBatcher`` / ``client.transport.outbound.OutboundBuffer``)
so ordering and overload behavior are fully unit-testable without asyncio.
Per docs/ARCHITECTURE.md's vLLM scheduler priority policy, final translation
always drains before a retry, which always drains before a completeness
check.
"""

from __future__ import annotations

from collections import deque
from enum import IntEnum
from typing import Generic, TypeVar

T = TypeVar("T")


class TranslationPriority(IntEnum):
    """Lower value drains first (docs/ARCHITECTURE.md priority policy)."""

    FINAL = 0
    RETRY = 1
    COMPLETENESS = 2


class TranslationQueue(Generic[T]):
    """Bounded, priority-ordered FIFO for translation work.

    Each priority has its own bounded lane so a burst of low-priority
    completeness work cannot exhaust capacity meant for final translation or
    retries. Overflow is rejected explicitly (``put`` returns ``False``)
    rather than blocking or silently dropping a different priority's items.
    """

    def __init__(self, *, capacity_per_priority: int) -> None:
        if capacity_per_priority < 1:
            raise ValueError("capacity_per_priority must be >= 1")
        self._capacity = capacity_per_priority
        self._lanes: dict[TranslationPriority, deque[T]] = {
            priority: deque() for priority in TranslationPriority
        }

    def put(self, item: T, *, priority: TranslationPriority) -> bool:
        """Enqueue ``item`` at ``priority``. Returns False if that lane is full."""
        lane = self._lanes[priority]
        if len(lane) >= self._capacity:
            return False
        lane.append(item)
        return True

    def get(self) -> T | None:
        """Pop the highest-priority item (final, then retry, then completeness)."""
        for priority in TranslationPriority:
            lane = self._lanes[priority]
            if lane:
                return lane.popleft()
        return None

    def qsize(self, priority: TranslationPriority | None = None) -> int:
        """Total queued items, or the count for a single ``priority`` lane."""
        if priority is None:
            return sum(len(lane) for lane in self._lanes.values())
        return len(self._lanes[priority])

    def __len__(self) -> int:
        return self.qsize()


def should_skip_completeness(*, current_depth: int, skip_threshold: int) -> bool:
    """Whether completeness work should be skipped under queue pressure.

    Per docs/TRANSLATION.md: "Completeness must be skipped when queue
    pressure exceeds the configured threshold" (the
    ``completeness_skip_queue_depth`` setting). ``current_depth`` is
    typically :meth:`TranslationQueue.qsize` across all priorities.
    """
    if skip_threshold < 0:
        raise ValueError("skip_threshold must be >= 0")
    return current_depth >= skip_threshold
