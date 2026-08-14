"""Rate limiting primitives for the WebSocket gateway.

A simple monotonic-time token bucket bounds the packet ingest rate per
connection. Time is injected as ``now`` (monotonic seconds) so the limiter is
deterministic and unit-testable without real clocks.
"""

from __future__ import annotations


class TokenBucket:
    """Token bucket rate limiter.

    Refills at ``rate_per_sec`` tokens per second up to ``burst`` capacity.
    :meth:`try_consume` returns whether the requested tokens were available.
    """

    def __init__(self, *, rate_per_sec: float, burst: int) -> None:
        if rate_per_sec <= 0.0:
            raise ValueError("rate_per_sec must be > 0")
        if burst < 1:
            raise ValueError("burst must be >= 1")
        self._rate = rate_per_sec
        self._capacity = float(burst)
        self._tokens = float(burst)
        self._last: float | None = None

    @property
    def tokens(self) -> float:
        """Currently available tokens (not refilled since the last consume)."""
        return self._tokens

    def try_consume(self, tokens: int = 1, *, now: float) -> bool:
        """Attempt to consume ``tokens`` at monotonic time ``now`` (seconds)."""
        if tokens < 0:
            raise ValueError("tokens must be >= 0")
        if self._last is None:
            self._last = now
        elapsed = now - self._last
        if elapsed > 0:
            self._tokens = min(self._capacity, self._tokens + elapsed * self._rate)
            self._last = now
        if self._tokens >= tokens:
            self._tokens -= tokens
            return True
        return False
