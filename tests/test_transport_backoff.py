"""Tests for the reconnect backoff sequence."""

from __future__ import annotations

import pytest

from client.transport.backoff import ReconnectBackoff


def test_deterministic_exponential_sequence() -> None:
    backoff = ReconnectBackoff(initial_ms=100, max_ms=2000, multiplier=2.0)
    delays = [backoff.next_delay_ms() for _ in range(6)]
    assert delays == [100, 200, 400, 800, 1600, 2000]


def test_reset_restarts_sequence() -> None:
    backoff = ReconnectBackoff(initial_ms=50, max_ms=1000, multiplier=3.0)
    assert backoff.next_delay_ms() == 50
    assert backoff.next_delay_ms() == 150
    backoff.reset()
    assert backoff.attempts == 0
    assert backoff.next_delay_ms() == 50


def test_jitter_stays_within_bounds() -> None:
    # rand() -> 1.0 gives the maximum positive jitter factor.
    backoff = ReconnectBackoff(
        initial_ms=100,
        max_ms=10000,
        multiplier=2.0,
        jitter=0.5,
        rand=lambda: 1.0,
    )
    delay = backoff.next_delay_ms()
    # base=100, factor = 1 + 0.5*(2*1-1) = 1.5 -> 150, clamped to max.
    assert delay == 150


def test_invalid_configuration_rejected() -> None:
    with pytest.raises(ValueError):
        ReconnectBackoff(initial_ms=0, max_ms=10)
    with pytest.raises(ValueError):
        ReconnectBackoff(initial_ms=100, max_ms=50)
    with pytest.raises(ValueError):
        ReconnectBackoff(initial_ms=100, max_ms=200, multiplier=0.5)
    with pytest.raises(ValueError):
        ReconnectBackoff(initial_ms=100, max_ms=200, jitter=2.0)
