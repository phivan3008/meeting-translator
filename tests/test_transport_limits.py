"""Tests for the token-bucket rate limiter."""

from __future__ import annotations

import pytest

from server.transport.limits import TokenBucket


def test_burst_then_denied() -> None:
    bucket = TokenBucket(rate_per_sec=10.0, burst=3)
    assert bucket.try_consume(now=0.0) is True
    assert bucket.try_consume(now=0.0) is True
    assert bucket.try_consume(now=0.0) is True
    # Burst exhausted at the same instant.
    assert bucket.try_consume(now=0.0) is False


def test_refill_over_time() -> None:
    bucket = TokenBucket(rate_per_sec=10.0, burst=2)
    assert bucket.try_consume(now=0.0) is True
    assert bucket.try_consume(now=0.0) is True
    assert bucket.try_consume(now=0.0) is False
    # After 0.1s at 10/s, one token is available again.
    assert bucket.try_consume(now=0.1) is True


def test_capacity_caps_refill() -> None:
    bucket = TokenBucket(rate_per_sec=100.0, burst=5)
    # Idle a long time; tokens must not exceed burst capacity.
    assert bucket.try_consume(5, now=100.0) is True
    assert bucket.try_consume(1, now=100.0) is False


def test_invalid_configuration_rejected() -> None:
    with pytest.raises(ValueError):
        TokenBucket(rate_per_sec=0.0, burst=1)
    with pytest.raises(ValueError):
        TokenBucket(rate_per_sec=1.0, burst=0)
