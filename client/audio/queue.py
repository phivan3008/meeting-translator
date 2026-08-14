"""Bounded queue for raw audio chunks with an explicit drop policy.

Used between the capture callback (producer) and the conversion worker
(consumer). ``put`` is non-blocking so it is safe to call from a real-time
audio callback. Overflow and drop counts are exposed for metrics.
"""

from __future__ import annotations

from collections import deque
from typing import Generic, TypeVar

from client.audio.types import DropPolicy

T = TypeVar("T")


class BoundedAudioQueue(Generic[T]):
    """A bounded FIFO queue with a configurable overflow drop policy."""

    def __init__(self, maxsize: int, policy: DropPolicy = DropPolicy.DROP_OLDEST) -> None:
        if maxsize < 1:
            raise ValueError("maxsize must be >= 1")
        self._maxsize = maxsize
        self._policy = policy
        self._items: deque[T] = deque()
        self._accepted = 0
        self._dropped = 0
        self._overflow_events = 0

    @property
    def maxsize(self) -> int:
        return self._maxsize

    @property
    def policy(self) -> DropPolicy:
        return self._policy

    @property
    def depth(self) -> int:
        return len(self._items)

    @property
    def accepted(self) -> int:
        """Total items successfully retained (excludes dropped)."""
        return self._accepted

    @property
    def dropped(self) -> int:
        """Total items discarded due to overflow."""
        return self._dropped

    @property
    def overflow_events(self) -> int:
        """Number of ``put`` calls that hit a full queue."""
        return self._overflow_events

    def put(self, item: T) -> bool:
        """Enqueue an item. Returns True if the new item was retained.

        Non-blocking. On overflow, applies the drop policy:
        - DROP_OLDEST: evict the oldest item and retain the new one.
        - DROP_NEWEST: discard the incoming item.
        """
        if len(self._items) < self._maxsize:
            self._items.append(item)
            self._accepted += 1
            return True

        self._overflow_events += 1
        if self._policy is DropPolicy.DROP_OLDEST:
            self._items.popleft()
            self._items.append(item)
            self._dropped += 1
            self._accepted += 1
            return True

        # DROP_NEWEST
        self._dropped += 1
        return False

    def get(self) -> T | None:
        """Dequeue the oldest item, or return None if empty."""
        if not self._items:
            return None
        return self._items.popleft()

    def drain(self) -> list[T]:
        """Remove and return all queued items in FIFO order."""
        items = list(self._items)
        self._items.clear()
        return items
