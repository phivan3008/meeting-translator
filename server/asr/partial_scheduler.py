"""Fair, time-injected scheduling of periodic partial ASR decodes.

Decides, given the current monotonic time, which active utterances are due
for their next partial decode, at a configurable interval per utterance
(``whisper_partial_interval_ms``, default 500 ms). Utterances are scheduled
independently, so a stream that started later is not penalized by one that
started earlier, and a missed/slow tick reschedules from "now" rather than
the missed due time, so a long gap cannot trigger a burst of catch-up
decodes. When multiple utterances are simultaneously due, all are returned
(oldest-registered first for ties) rather than only the one the caller
happens to check first, so no active stream is starved.

Pure and time-injected: contains no asyncio, threads or I/O, matching the
style of ``server.transport.acks.AckBatcher``.
"""

from __future__ import annotations


class PartialDecodeScheduler:
    """Tracks per-utterance due times for periodic partial decoding."""

    def __init__(self, *, interval_ms: int) -> None:
        if interval_ms < 1:
            raise ValueError("interval_ms must be >= 1")
        self._interval_ms = interval_ms
        self._next_due_ms: dict[str, int] = {}

    def start(self, utterance_id: str, *, now_ms: int) -> None:
        """Register a new utterance; its first decode is due after one interval."""
        self._next_due_ms[utterance_id] = now_ms + self._interval_ms

    def stop(self, utterance_id: str) -> None:
        """Remove an utterance (finalized or abandoned) from scheduling."""
        self._next_due_ms.pop(utterance_id, None)

    def is_active(self, utterance_id: str) -> bool:
        return utterance_id in self._next_due_ms

    def due(self, *, now_ms: int) -> list[str]:
        """Return ids due for decode now, and reschedule them from ``now_ms``."""
        due_ids = sorted(
            (uid for uid, due_ms in self._next_due_ms.items() if now_ms >= due_ms),
            key=lambda uid: self._next_due_ms[uid],
        )
        for utterance_id in due_ids:
            self._next_due_ms[utterance_id] = now_ms + self._interval_ms
        return due_ids
