"""Tests for the stable-prefix (local-agreement) text-merging component."""

from __future__ import annotations

from server.asr.stable_prefix import StablePrefixTracker
from server.asr.types import TranscriptionSegment


def _seg(text: str, start_ms: int, end_ms: int) -> TranscriptionSegment:
    return TranscriptionSegment(text=text, start_ms=start_ms, end_ms=end_ms)


def test_first_hypothesis_commits_nothing() -> None:
    tracker = StablePrefixTracker()
    result = tracker.update([_seg("Xin chào", 0, 800)])
    assert result.stable_text == ""
    assert result.unstable_text == "Xin chào"
    assert result.display_text == "Xin chào"


def test_commits_after_two_agreeing_segments_vietnamese() -> None:
    tracker = StablePrefixTracker()
    tracker.update([_seg("Xin chào", 0, 800)])
    result = tracker.update([_seg("Xin chào", 0, 800), _seg(" các bạn", 800, 1200)])
    assert result.stable_text == "Xin chào"
    assert result.unstable_text == " các bạn"
    assert tracker.committed_text == "Xin chào"


def test_commits_after_two_agreeing_segments_japanese_no_spaces() -> None:
    tracker = StablePrefixTracker()
    tracker.update([_seg("こんにちは", 0, 900)])
    result = tracker.update([_seg("こんにちは", 0, 900), _seg("元気ですか", 900, 1500)])
    assert result.stable_text == "こんにちは"
    assert result.unstable_text == "元気ですか"


def test_punctuation_variation_does_not_prematurely_commit() -> None:
    tracker = StablePrefixTracker()
    tracker.update([_seg("こんにちは", 0, 900)])
    # Differs only by trailing punctuation -> segments are not equal -> no agreement yet.
    result = tracker.update([_seg("こんにちは。", 0, 900)])
    assert result.stable_text == ""
    assert result.unstable_text == "こんにちは。"

    # Only commits once the punctuated form itself repeats.
    result2 = tracker.update([_seg("こんにちは。", 0, 900), _seg("元気", 900, 1200)])
    assert result2.stable_text == "こんにちは。"
    assert result2.unstable_text == "元気"


def test_hypothesis_correction_does_not_rewrite_committed_text() -> None:
    tracker = StablePrefixTracker()
    tracker.update([_seg("Xin chào", 0, 800)])
    tracker.update([_seg("Xin chào", 0, 800), _seg(" các bạn", 800, 1200)])
    assert tracker.committed_text == "Xin chào"

    # A later, noisy decode revises the first segment entirely.
    result = tracker.update([_seg("Xin sao", 0, 800), _seg(" các bạn", 800, 1200)])
    assert tracker.committed_text == "Xin chào"
    assert result.stable_text == "Xin chào"
    assert result.unstable_text == ""


def test_committed_text_never_shrinks() -> None:
    tracker = StablePrefixTracker()
    lengths: list[int] = []
    sequences = [
        [_seg("A", 0, 200)],
        [_seg("A", 0, 200), _seg("B", 200, 400)],
        [_seg("A", 0, 200), _seg("B", 200, 400), _seg("C", 400, 600)],
        [_seg("X", 0, 200)],  # a much shorter, contradicting hypothesis
        [_seg("A", 0, 200), _seg("B", 200, 400), _seg("C", 400, 600), _seg("D", 600, 800)],
    ]
    for segments in sequences:
        tracker.update(segments)
        lengths.append(len(tracker.committed_text))
    assert lengths == sorted(lengths)


def test_stable_boundary_ms_tracks_committed_segment_end() -> None:
    tracker = StablePrefixTracker()
    tracker.update([_seg("A", 0, 500)])
    segments = [_seg("A", 0, 500), _seg("B", 500, 900)]
    tracker.update(segments)
    assert tracker.committed_text == "A"
    assert tracker.stable_boundary_ms(segments) == 500


def test_stable_boundary_ms_zero_when_nothing_committed() -> None:
    tracker = StablePrefixTracker()
    segments = [_seg("A", 0, 500)]
    tracker.update(segments)
    assert tracker.stable_boundary_ms(segments) == 0


def test_reset_window_keeps_committed_text_but_restarts_agreement() -> None:
    tracker = StablePrefixTracker()
    tracker.update([_seg("A", 0, 500)])
    tracker.update([_seg("A", 0, 500), _seg("B", 500, 900)])
    assert tracker.committed_text == "A"

    tracker.reset_window()
    # A fresh decode of the new (shifted) window; timestamps restart at 0 and
    # the leading segment does not literally reproduce "A".
    result = tracker.update([_seg("B", 0, 400)])
    assert tracker.committed_text == "A"
    assert result.stable_text == "A"
    assert result.unstable_text == ""

    # Agreement resumes normally once two fresh decodes of the new window agree.
    result2 = tracker.update([_seg("B", 0, 400), _seg("C", 400, 700)])
    assert result2.unstable_text == ""  # "B" doesn't extend committed "A"; still contradicting


def test_finalize_commits_full_text() -> None:
    tracker = StablePrefixTracker()
    tracker.update([_seg("Xin", 0, 400)])
    result = tracker.finalize("Xin chào các bạn")
    assert result.stable_text == "Xin chào các bạn"
    assert result.unstable_text == ""
    assert tracker.committed_text == "Xin chào các bạn"
