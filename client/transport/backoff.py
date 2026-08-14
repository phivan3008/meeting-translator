"""Exponential reconnect backoff with optional jitter.

The backoff produces increasing delays between reconnection attempts, capped at
a maximum. Jitter is a fraction in ``[0, 1]``; with ``jitter=0`` the sequence is
fully deterministic and unit-testable. A random source can be injected for
deterministic jitter tests.
"""

from __future__ import annotations

import random
from collections.abc import Callable


class ReconnectBackoff:
    """Compute successive reconnect delays in milliseconds."""

    def __init__(
        self,
        *,
        initial_ms: int,
        max_ms: int,
        multiplier: float = 2.0,
        jitter: float = 0.0,
        rand: Callable[[], float] | None = None,
    ) -> None:
        if initial_ms < 1:
            raise ValueError("initial_ms must be >= 1")
        if max_ms < initial_ms:
            raise ValueError("max_ms must be >= initial_ms")
        if multiplier < 1.0:
            raise ValueError("multiplier must be >= 1.0")
        if not 0.0 <= jitter <= 1.0:
            raise ValueError("jitter must be in [0, 1]")
        self._initial = initial_ms
        self._max = max_ms
        self._multiplier = multiplier
        self._jitter = jitter
        self._rand = rand if rand is not None else random.random
        self._attempts = 0

    @property
    def attempts(self) -> int:
        """Number of delays produced since the last :meth:`reset`."""
        return self._attempts

    def reset(self) -> None:
        """Reset the sequence after a successful connection."""
        self._attempts = 0

    def next_delay_ms(self) -> int:
        """Return the next delay and advance the sequence."""
        base = min(self._max, self._initial * (self._multiplier**self._attempts))
        self._attempts += 1
        if self._jitter > 0.0:
            # Symmetric jitter around the base delay, clamped to [1, max].
            factor = 1.0 + self._jitter * (2.0 * self._rand() - 1.0)
            base = base * factor
        return max(1, min(self._max, int(base)))
