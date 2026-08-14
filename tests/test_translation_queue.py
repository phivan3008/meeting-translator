"""Tests for the translation priority queue and completeness-skip policy."""

from __future__ import annotations

import pytest

from server.translation.queue import TranslationPriority, TranslationQueue, should_skip_completeness


def test_rejects_invalid_capacity() -> None:
    with pytest.raises(ValueError):
        TranslationQueue(capacity_per_priority=0)


def test_final_drains_before_retry_and_completeness() -> None:
    queue: TranslationQueue[str] = TranslationQueue(capacity_per_priority=4)
    queue.put("completeness-1", priority=TranslationPriority.COMPLETENESS)
    queue.put("retry-1", priority=TranslationPriority.RETRY)
    queue.put("final-1", priority=TranslationPriority.FINAL)

    assert queue.get() == "final-1"
    assert queue.get() == "retry-1"
    assert queue.get() == "completeness-1"
    assert queue.get() is None


def test_fifo_within_same_priority() -> None:
    queue: TranslationQueue[str] = TranslationQueue(capacity_per_priority=4)
    queue.put("a", priority=TranslationPriority.FINAL)
    queue.put("b", priority=TranslationPriority.FINAL)
    queue.put("c", priority=TranslationPriority.FINAL)

    assert queue.get() == "a"
    assert queue.get() == "b"
    assert queue.get() == "c"


def test_new_final_item_still_drains_before_older_retry() -> None:
    queue: TranslationQueue[str] = TranslationQueue(capacity_per_priority=4)
    queue.put("retry-old", priority=TranslationPriority.RETRY)
    queue.put("final-new", priority=TranslationPriority.FINAL)

    assert queue.get() == "final-new"
    assert queue.get() == "retry-old"


def test_lane_overflow_is_rejected_explicitly() -> None:
    queue: TranslationQueue[str] = TranslationQueue(capacity_per_priority=2)
    assert queue.put("a", priority=TranslationPriority.COMPLETENESS) is True
    assert queue.put("b", priority=TranslationPriority.COMPLETENESS) is True
    assert queue.put("c", priority=TranslationPriority.COMPLETENESS) is False
    assert queue.qsize(TranslationPriority.COMPLETENESS) == 2


def test_lane_overflow_does_not_affect_other_priorities() -> None:
    queue: TranslationQueue[str] = TranslationQueue(capacity_per_priority=1)
    assert queue.put("c", priority=TranslationPriority.COMPLETENESS) is True
    assert queue.put("c2", priority=TranslationPriority.COMPLETENESS) is False
    assert queue.put("f", priority=TranslationPriority.FINAL) is True
    assert queue.get() == "f"


def test_qsize_total_and_per_priority() -> None:
    queue: TranslationQueue[str] = TranslationQueue(capacity_per_priority=4)
    queue.put("f", priority=TranslationPriority.FINAL)
    queue.put("r1", priority=TranslationPriority.RETRY)
    queue.put("r2", priority=TranslationPriority.RETRY)
    assert queue.qsize() == 3
    assert len(queue) == 3
    assert queue.qsize(TranslationPriority.RETRY) == 2
    assert queue.qsize(TranslationPriority.COMPLETENESS) == 0


def test_should_skip_completeness_threshold() -> None:
    assert should_skip_completeness(current_depth=3, skip_threshold=4) is False
    assert should_skip_completeness(current_depth=4, skip_threshold=4) is True
    assert should_skip_completeness(current_depth=5, skip_threshold=4) is True


def test_should_skip_completeness_rejects_negative_threshold() -> None:
    with pytest.raises(ValueError):
        should_skip_completeness(current_depth=0, skip_threshold=-1)
