"""Reliability primitives shared across backend adapters.

Framework-independent, pure and time-injected (matching the project's
existing style for testable primitives like
``client.transport.backoff.ReconnectBackoff`` and
``server.transport.limits.TokenBucket``) -- no asyncio, no network, no I/O.
"""

from __future__ import annotations

from server.reliability.circuit_breaker import CircuitBreaker, CircuitState, circuit_state_value
from server.reliability.shutdown import ShutdownCoordinator

__all__ = [
    "CircuitBreaker",
    "CircuitState",
    "ShutdownCoordinator",
    "circuit_state_value",
]
