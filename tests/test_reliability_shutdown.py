"""Tests for graceful-shutdown bookkeeping."""

from __future__ import annotations

from server.reliability.shutdown import ShutdownCoordinator


def test_starts_not_shutting_down() -> None:
    coordinator = ShutdownCoordinator()
    assert coordinator.is_shutting_down is False


def test_begin_shutdown_is_immediate_and_idempotent() -> None:
    coordinator = ShutdownCoordinator()
    coordinator.begin_shutdown()
    assert coordinator.is_shutting_down is True
    coordinator.begin_shutdown()  # no error, stays True
    assert coordinator.is_shutting_down is True


def test_drained_true_with_no_source_registered() -> None:
    coordinator = ShutdownCoordinator()
    assert coordinator.active_count() == 0
    assert coordinator.drained() is True


def test_active_count_reflects_registered_source() -> None:
    coordinator = ShutdownCoordinator()
    count = {"value": 3}
    coordinator.set_active_count_source(lambda: count["value"])

    assert coordinator.active_count() == 3
    assert coordinator.drained() is False

    count["value"] = 0
    assert coordinator.active_count() == 0
    assert coordinator.drained() is True
