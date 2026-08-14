"""Graceful shutdown bookkeeping.

Pure, synchronous state (no asyncio here, so it is trivially unit
-testable); the FastAPI lifespan handler in ``server/app.py`` drives the
actual async wait loop, polling this coordinator. Two responsibilities:

1. ``is_shutting_down`` flips to ``True`` the instant shutdown begins, so
   ``/health/ready`` can report not-ready immediately (a load balancer or
   orchestrator should stop routing new connections right away, before any
   draining happens).
2. Reports whether active sessions have drained, via a caller-supplied
   count source (typically ``SessionManager.active_count``), so the
   shutdown handler knows when it is safe to stop waiting.
"""

from __future__ import annotations

from collections.abc import Callable


class ShutdownCoordinator:
    """Tracks shutdown state and active-work drainage for graceful shutdown."""

    def __init__(self) -> None:
        self._shutting_down = False
        self._active_count_fn: Callable[[], int] | None = None

    @property
    def is_shutting_down(self) -> bool:
        return self._shutting_down

    def begin_shutdown(self) -> None:
        """Mark shutdown as started. Idempotent."""
        self._shutting_down = True

    def set_active_count_source(self, fn: Callable[[], int]) -> None:
        """Register the callable used to report the current active-work count."""
        self._active_count_fn = fn

    def active_count(self) -> int:
        """Current active-work count, or 0 if no source has been registered."""
        if self._active_count_fn is None:
            return 0
        return self._active_count_fn()

    def drained(self) -> bool:
        """Whether there is currently no active work to wait for."""
        return self.active_count() == 0
