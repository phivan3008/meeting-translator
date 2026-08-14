"""Bounded pre-roll ring buffer.

Holds the most recent audio up to a configured duration so that, when speech is
confirmed, a short lead-in (pre-roll) can be prepended to the utterance. Sized
in whole frames from ``capacity_ms`` and the fixed ``frame_ms``.
"""

from __future__ import annotations

from collections import deque


class PreRollBuffer:
    """Ring buffer retaining up to ``capacity_ms`` of recent audio frames."""

    def __init__(self, *, capacity_ms: int, frame_ms: int) -> None:
        if capacity_ms < 0:
            raise ValueError("capacity_ms must be >= 0")
        if frame_ms < 1:
            raise ValueError("frame_ms must be >= 1")
        # Number of whole frames needed to cover capacity_ms.
        self._max_frames = capacity_ms // frame_ms
        self._frames: deque[bytes] = deque(maxlen=self._max_frames if self._max_frames else 1)
        self._enabled = self._max_frames > 0

    @property
    def max_frames(self) -> int:
        return self._max_frames

    def push(self, frame: bytes) -> None:
        if not self._enabled:
            return
        self._frames.append(frame)

    def snapshot(self) -> bytes:
        """Return the buffered audio concatenated in chronological order."""
        if not self._enabled:
            return b""
        return b"".join(self._frames)

    def clear(self) -> None:
        self._frames.clear()
