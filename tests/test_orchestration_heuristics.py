"""Tests for the deterministic completeness heuristic checker."""

from __future__ import annotations

from server.orchestration.heuristics import HeuristicConfig, evaluate_heuristic
from shared.protocol.enums import Language

CONFIG = HeuristicConfig(min_stable_speech_ms=300, max_unstable_tail_chars=12)


def test_vietnamese_punctuation_is_definite_complete() -> None:
    verdict = evaluate_heuristic(
        language=Language.VIETNAMESE,
        stable_text="Tôi muốn xác nhận về đợt phát hành.",
        unstable_text="",
        speech_ms=500,
        config=CONFIG,
    )
    assert verdict.complete is True
    assert verdict.ambiguous is False
    assert verdict.reason == "punctuation"


def test_japanese_punctuation_is_definite_complete() -> None:
    verdict = evaluate_heuristic(
        language=Language.JAPANESE,
        stable_text="来週のリリースについて確認したいです。",
        unstable_text="",
        speech_ms=500,
        config=CONFIG,
    )
    assert verdict.complete is True
    assert verdict.ambiguous is False
    assert verdict.reason == "punctuation"


def test_vietnamese_ending_signal_without_punctuation_is_complete() -> None:
    verdict = evaluate_heuristic(
        language=Language.VIETNAMESE,
        stable_text="Xong rồi",
        unstable_text="",
        speech_ms=500,
        config=CONFIG,
    )
    assert verdict.complete is True
    assert verdict.ambiguous is False
    assert verdict.reason == "ending_signal"


def test_japanese_ending_signal_without_punctuation_is_complete() -> None:
    verdict = evaluate_heuristic(
        language=Language.JAPANESE,
        stable_text="来週確認します",
        unstable_text="",
        speech_ms=500,
        config=CONFIG,
    )
    assert verdict.complete is True
    assert verdict.ambiguous is False
    assert verdict.reason == "ending_signal"


def test_long_unstable_tail_is_definite_incomplete_not_ambiguous() -> None:
    verdict = evaluate_heuristic(
        language=Language.JAPANESE,
        stable_text="来週のリリースについて",
        unstable_text="確認したいのですがまだ話しています",
        speech_ms=500,
        config=CONFIG,
    )
    assert verdict.complete is False
    assert verdict.ambiguous is False
    assert verdict.reason == "unstable_tail_too_long"


def test_empty_stable_text_is_definite_incomplete_not_ambiguous() -> None:
    verdict = evaluate_heuristic(
        language=Language.VIETNAMESE,
        stable_text="  ",
        unstable_text="Xin",
        speech_ms=500,
        config=CONFIG,
    )
    assert verdict.complete is False
    assert verdict.ambiguous is False
    assert verdict.reason == "empty_stable_text"


def test_short_speech_duration_makes_punctuation_ambiguous() -> None:
    verdict = evaluate_heuristic(
        language=Language.VIETNAMESE,
        stable_text="Vâng.",
        unstable_text="",
        speech_ms=50,  # below min_stable_speech_ms=300
        config=CONFIG,
    )
    assert verdict.complete is False
    assert verdict.ambiguous is True
    assert verdict.reason == "no_deterministic_signal"


def test_no_signal_is_ambiguous_with_deterministic_fallback_incomplete() -> None:
    verdict = evaluate_heuristic(
        language=Language.JAPANESE,
        stable_text="来週のリリースについて確認したい",
        unstable_text="",
        speech_ms=500,
        config=CONFIG,
    )
    assert verdict.complete is False
    assert verdict.ambiguous is True
    assert verdict.reason == "no_deterministic_signal"


def test_short_unstable_tail_within_threshold_does_not_block_completion() -> None:
    verdict = evaluate_heuristic(
        language=Language.VIETNAMESE,
        stable_text="Tôi muốn xác nhận.",
        unstable_text="à",
        speech_ms=500,
        config=CONFIG,
    )
    assert verdict.complete is True
    assert verdict.reason == "punctuation"


def test_invalid_config_rejected() -> None:
    import pytest

    with pytest.raises(ValueError):
        HeuristicConfig(min_stable_speech_ms=-1)
    with pytest.raises(ValueError):
        HeuristicConfig(max_unstable_tail_chars=-1)


def test_from_settings_reads_completeness_heuristic_fields() -> None:
    class FakeSettings:
        completeness_heuristic_min_speech_ms = 400
        completeness_heuristic_max_unstable_tail_chars = 5

    config = HeuristicConfig.from_settings(FakeSettings())
    assert config.min_stable_speech_ms == 400
    assert config.max_unstable_tail_chars == 5
