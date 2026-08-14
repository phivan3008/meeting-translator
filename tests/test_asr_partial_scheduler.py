"""Tests for the fair, time-injected partial-decode scheduler."""

from __future__ import annotations

import pytest

from server.asr.partial_scheduler import PartialDecodeScheduler


def test_rejects_invalid_interval() -> None:
    with pytest.raises(ValueError):
        PartialDecodeScheduler(interval_ms=0)


def test_not_due_before_interval() -> None:
    scheduler = PartialDecodeScheduler(interval_ms=500)
    scheduler.start("u1", now_ms=0)
    assert scheduler.due(now_ms=499) == []


def test_due_after_interval() -> None:
    scheduler = PartialDecodeScheduler(interval_ms=500)
    scheduler.start("u1", now_ms=0)
    assert scheduler.due(now_ms=500) == ["u1"]


def test_due_reschedules_for_next_interval() -> None:
    scheduler = PartialDecodeScheduler(interval_ms=500)
    scheduler.start("u1", now_ms=0)
    assert scheduler.due(now_ms=500) == ["u1"]
    assert scheduler.due(now_ms=999) == []
    assert scheduler.due(now_ms=1000) == ["u1"]


def test_stop_removes_utterance() -> None:
    scheduler = PartialDecodeScheduler(interval_ms=500)
    scheduler.start("u1", now_ms=0)
    scheduler.stop("u1")
    assert scheduler.is_active("u1") is False
    assert scheduler.due(now_ms=1000) == []


def test_independent_streams_scheduled_by_own_start_time() -> None:
    scheduler = PartialDecodeScheduler(interval_ms=500)
    scheduler.start("a", now_ms=0)
    scheduler.start("b", now_ms=100)
    assert scheduler.due(now_ms=500) == ["a"]
    assert scheduler.due(now_ms=600) == ["b"]


def test_simultaneous_due_returns_all_no_stream_starved() -> None:
    scheduler = PartialDecodeScheduler(interval_ms=500)
    scheduler.start("a", now_ms=0)
    scheduler.start("b", now_ms=0)
    scheduler.start("c", now_ms=0)
    assert scheduler.due(now_ms=500) == ["a", "b", "c"]


def test_missed_tick_reschedules_from_now_not_from_due() -> None:
    scheduler = PartialDecodeScheduler(interval_ms=500)
    scheduler.start("a", now_ms=0)
    assert scheduler.due(now_ms=5000) == ["a"]
    assert scheduler.due(now_ms=5499) == []
    assert scheduler.due(now_ms=5500) == ["a"]


def test_is_active() -> None:
    scheduler = PartialDecodeScheduler(interval_ms=500)
    assert scheduler.is_active("u1") is False
    scheduler.start("u1", now_ms=0)
    assert scheduler.is_active("u1") is True
