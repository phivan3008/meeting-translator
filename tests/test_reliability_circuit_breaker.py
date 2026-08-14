"""Tests for the generic circuit breaker."""

from __future__ import annotations

import pytest

from server.reliability.circuit_breaker import CircuitBreaker, CircuitState


class _FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _breaker(
    clock: _FakeClock, *, failure_threshold: int = 3, reset_timeout_ms: int = 1000
) -> CircuitBreaker:
    return CircuitBreaker(
        failure_threshold=failure_threshold, reset_timeout_ms=reset_timeout_ms, now_fn=clock
    )


def test_starts_closed_and_allows_requests() -> None:
    clock = _FakeClock()
    breaker = _breaker(clock)
    assert breaker.state is CircuitState.CLOSED
    assert breaker.allow_request() is True


def test_success_before_threshold_resets_failure_count() -> None:
    clock = _FakeClock()
    breaker = _breaker(clock, failure_threshold=3)
    breaker.allow_request()
    breaker.record_failure()
    breaker.allow_request()
    breaker.record_failure()
    breaker.allow_request()
    breaker.record_success()  # resets the streak before hitting threshold

    breaker.allow_request()
    breaker.record_failure()
    breaker.allow_request()
    breaker.record_failure()
    assert breaker.state is CircuitState.CLOSED  # only 2 consecutive, not 3


def test_trips_open_after_consecutive_failures() -> None:
    clock = _FakeClock()
    breaker = _breaker(clock, failure_threshold=3)
    for _ in range(3):
        breaker.allow_request()
        breaker.record_failure()

    assert breaker.state is CircuitState.OPEN
    assert breaker.allow_request() is False


def test_open_rejects_until_reset_timeout_elapses() -> None:
    clock = _FakeClock()
    breaker = _breaker(clock, failure_threshold=1, reset_timeout_ms=1000)
    breaker.allow_request()
    breaker.record_failure()
    assert breaker.state is CircuitState.OPEN

    clock.advance(0.5)
    assert breaker.allow_request() is False
    assert breaker.state is CircuitState.OPEN

    clock.advance(0.6)  # total 1.1s >= 1.0s reset timeout
    assert breaker.state is CircuitState.HALF_OPEN


def test_half_open_allows_exactly_one_trial_call() -> None:
    clock = _FakeClock()
    breaker = _breaker(clock, failure_threshold=1, reset_timeout_ms=1000)
    breaker.allow_request()
    breaker.record_failure()
    clock.advance(1.1)

    assert breaker.state is CircuitState.HALF_OPEN
    assert breaker.allow_request() is True  # the one trial call
    assert breaker.allow_request() is False  # a second concurrent caller is refused


def test_half_open_success_closes_breaker() -> None:
    clock = _FakeClock()
    breaker = _breaker(clock, failure_threshold=1, reset_timeout_ms=1000)
    breaker.allow_request()
    breaker.record_failure()
    clock.advance(1.1)

    assert breaker.allow_request() is True
    breaker.record_success()

    assert breaker.state is CircuitState.CLOSED
    assert breaker.allow_request() is True


def test_half_open_failure_reopens_and_restarts_timeout() -> None:
    clock = _FakeClock()
    breaker = _breaker(clock, failure_threshold=1, reset_timeout_ms=1000)
    breaker.allow_request()
    breaker.record_failure()
    clock.advance(1.1)

    assert breaker.allow_request() is True  # trial call
    breaker.record_failure()  # trial fails
    assert breaker.state is CircuitState.OPEN
    assert breaker.allow_request() is False

    clock.advance(1.1)  # timeout restarted at the trial failure, not the original trip
    assert breaker.state is CircuitState.HALF_OPEN


def test_invalid_construction_rejected() -> None:
    with pytest.raises(ValueError):
        CircuitBreaker(failure_threshold=0, reset_timeout_ms=1000)
    with pytest.raises(ValueError):
        CircuitBreaker(failure_threshold=1, reset_timeout_ms=0)


def test_default_clock_is_real_monotonic_time() -> None:
    # No injected now_fn: must not raise and must behave sanely.
    breaker = CircuitBreaker(failure_threshold=1, reset_timeout_ms=1)
    assert breaker.allow_request() is True
    breaker.record_failure()
    assert breaker.state is CircuitState.OPEN
