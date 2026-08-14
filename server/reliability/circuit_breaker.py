"""Generic circuit breaker for backend calls (translation, ASR).

Pure, synchronous and time-injected -- no asyncio, no network. A caller
wraps one backend attempt as: check :meth:`CircuitBreaker.allow_request`
before attempting; if it returns ``False``, skip the call entirely (fail
fast instead of piling more load onto an already-overloaded backend); if
``True``, make the attempt and report the outcome via
:meth:`record_success`/:meth:`record_failure` afterward.

Three states (docs/PRODUCT_REQUIREMENTS.md: "graceful degradation during
model overload"):

- ``CLOSED``: normal operation, every call is allowed through.
- ``OPEN``: tripped after ``failure_threshold`` consecutive failures;
  calls are short-circuited until ``reset_timeout_ms`` has elapsed since
  the trip.
- ``HALF_OPEN``: once the reset timeout elapses, exactly one trial call is
  allowed through to test whether the backend has recovered. Success
  closes the breaker (failure count resets); failure re-opens it and
  restarts the timeout.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from enum import Enum


class CircuitState(Enum):
    """Current circuit-breaker state."""

    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitBreaker:
    """Trips after repeated consecutive failures; recovers via a trial call.

    Callers must always report the outcome of an attempt that
    ``allow_request()`` permitted (via ``record_success()`` or
    ``record_failure()``); otherwise a half-open trial that never reports
    back leaves the breaker unable to admit a new trial call.
    """

    def __init__(
        self,
        *,
        failure_threshold: int,
        reset_timeout_ms: int,
        now_fn: Callable[[], float] | None = None,
    ) -> None:
        if failure_threshold < 1:
            raise ValueError("failure_threshold must be >= 1")
        if reset_timeout_ms < 1:
            raise ValueError("reset_timeout_ms must be >= 1")
        self._failure_threshold = failure_threshold
        self._reset_timeout_s = reset_timeout_ms / 1000.0
        self._now = now_fn or time.monotonic
        self._state = CircuitState.CLOSED
        self._consecutive_failures = 0
        self._opened_at: float | None = None
        self._half_open_trial_in_flight = False

    @property
    def state(self) -> CircuitState:
        self._maybe_transition_to_half_open()
        return self._state

    def allow_request(self) -> bool:
        """Whether a new backend call should be attempted right now."""
        self._maybe_transition_to_half_open()
        if self._state is CircuitState.CLOSED:
            return True
        if self._state is CircuitState.HALF_OPEN:
            if self._half_open_trial_in_flight:
                return False  # a trial call is already outstanding
            self._half_open_trial_in_flight = True
            return True
        return False  # OPEN

    def record_success(self) -> None:
        """Report that an allowed call succeeded."""
        self._consecutive_failures = 0
        self._state = CircuitState.CLOSED
        self._opened_at = None
        self._half_open_trial_in_flight = False

    def record_failure(self) -> None:
        """Report that an allowed call failed."""
        was_half_open = self._state is CircuitState.HALF_OPEN
        self._half_open_trial_in_flight = False
        if was_half_open:
            # The trial call failed: re-open immediately and restart the
            # reset timeout, regardless of the pre-trial failure count.
            self._trip()
            return
        self._consecutive_failures += 1
        if self._consecutive_failures >= self._failure_threshold:
            self._trip()

    def _trip(self) -> None:
        self._state = CircuitState.OPEN
        self._opened_at = self._now()

    def _maybe_transition_to_half_open(self) -> None:
        if self._state is CircuitState.OPEN and self._opened_at is not None:
            if self._now() - self._opened_at >= self._reset_timeout_s:
                self._state = CircuitState.HALF_OPEN
                self._half_open_trial_in_flight = False


_STATE_METRIC_VALUES = {
    CircuitState.CLOSED: 0.0,
    CircuitState.HALF_OPEN: 1.0,
    CircuitState.OPEN: 2.0,
}


def circuit_state_value(state: CircuitState) -> float:
    """Numeric encoding for the ``circuit_breaker_state`` gauge.

    0=closed, 1=half_open, 2=open, matching the gauge's documented help text.
    """
    return _STATE_METRIC_VALUES[state]
