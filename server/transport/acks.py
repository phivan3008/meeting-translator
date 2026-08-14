"""Acknowledgement batching.

Rather than acknowledging every audio packet, the gateway batches acks per
stream and emits one ``audio.ack`` after a configured number of packets or after
a configured time interval, whichever comes first. This reduces control-frame
overhead while bounding ack latency. The batcher is pure and time-injected.
"""

from __future__ import annotations


class AckBatcher:
    """Decide when to emit an ``audio.ack`` for a single stream."""

    def __init__(self, *, every_packets: int, every_ms: int) -> None:
        if every_packets < 1:
            raise ValueError("every_packets must be >= 1")
        if every_ms < 1:
            raise ValueError("every_ms must be >= 1")
        self._every_packets = every_packets
        self._every_ms = every_ms
        self._since_ack = 0
        self._last_emit_ms: int | None = None
        self._last_acked: int | None = None

    def record(self, last_contiguous: int, *, now_ms: int) -> int | None:
        """Record contiguous progress; return a sequence to ack or ``None``.

        Emits when the packet threshold or time interval is reached and the
        contiguous position advanced past the last acknowledged value.
        """
        self._since_ack += 1
        if self._last_emit_ms is None:
            self._last_emit_ms = now_ms

        advanced = self._last_acked is None or last_contiguous > self._last_acked
        count_due = self._since_ack >= self._every_packets
        time_due = (now_ms - self._last_emit_ms) >= self._every_ms

        if advanced and (count_due or time_due):
            return self._emit(last_contiguous, now_ms)
        return None

    def flush(self, last_contiguous: int, *, now_ms: int) -> int | None:
        """Force an ack if the contiguous position advanced since the last ack."""
        if self._last_acked is not None and last_contiguous <= self._last_acked:
            return None
        if last_contiguous < 0:
            return None
        return self._emit(last_contiguous, now_ms)

    def _emit(self, last_contiguous: int, now_ms: int) -> int:
        self._since_ack = 0
        self._last_emit_ms = now_ms
        self._last_acked = last_contiguous
        return last_contiguous
