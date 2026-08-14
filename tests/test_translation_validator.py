"""Tests for translation output validation (docs/TRANSLATION.md)."""

from __future__ import annotations

from server.translation.validator import validate_translation
from shared.protocol.enums import Language


def test_valid_vietnamese_translation_passes() -> None:
    result = validate_translation(
        source_text="来週のリリースについて確認したいです。",
        translated_text="Tôi muốn xác nhận về đợt phát hành vào tuần tới.",
        target_language=Language.VIETNAMESE,
    )
    assert result.ok is True
    assert result.reason is None


def test_valid_japanese_translation_passes() -> None:
    result = validate_translation(
        source_text="Tôi muốn xác nhận về đợt phát hành vào tuần tới.",
        translated_text="来週のリリースについて確認したいです。",
        target_language=Language.JAPANESE,
    )
    assert result.ok is True


def test_empty_output_rejected() -> None:
    result = validate_translation(
        source_text="hello", translated_text="   ", target_language=Language.VIETNAMESE
    )
    assert result.ok is False
    assert result.reason == "empty_output"


def test_forbidden_prefix_rejected() -> None:
    result = validate_translation(
        source_text="hello",
        translated_text="Translation: xin chào",
        target_language=Language.VIETNAMESE,
    )
    assert result.ok is False
    assert result.reason == "forbidden_prefix"


def test_forbidden_prefix_rejected_vietnamese_label() -> None:
    result = validate_translation(
        source_text="hello",
        translated_text="Bản dịch: xin chào",
        target_language=Language.VIETNAMESE,
    )
    assert result.reason == "forbidden_prefix"


def test_pathological_repetition_rejected_vietnamese() -> None:
    result = validate_translation(
        source_text="xin chào",
        translated_text="xin chào xin chào xin chào xin chào xin chào xin chào",
        target_language=Language.VIETNAMESE,
    )
    assert result.ok is False
    assert result.reason == "repetition"


def test_pathological_repetition_rejected_japanese_no_spaces() -> None:
    result = validate_translation(
        source_text="こんにちは",
        translated_text="こんにちはこんにちはこんにちはこんにちはこんにちはこんにちは",
        target_language=Language.JAPANESE,
    )
    assert result.ok is False
    assert result.reason == "repetition"


def test_wrong_language_rejected_when_japanese_expected() -> None:
    result = validate_translation(
        source_text="Tôi muốn xác nhận.",
        translated_text="I want to confirm this next week please thank you very much indeed",
        target_language=Language.JAPANESE,
    )
    assert result.ok is False
    assert result.reason == "wrong_language"


def test_wrong_language_rejected_when_vietnamese_expected_but_japanese_returned() -> None:
    result = validate_translation(
        source_text="来週について確認したいです。",
        translated_text="来週のリリースについて確認したいです。",
        target_language=Language.VIETNAMESE,
    )
    assert result.ok is False
    assert result.reason == "wrong_language"


def test_identifiers_not_preserved_rejected_missing_version() -> None:
    result = validate_translation(
        source_text="Please upgrade to version 2.5.1 before the release.",
        translated_text="Vui lòng nâng cấp trước đợt phát hành.",
        target_language=Language.VIETNAMESE,
    )
    assert result.ok is False
    assert result.reason == "identifiers_not_preserved"


def test_identifiers_preserved_passes() -> None:
    result = validate_translation(
        source_text="Please upgrade to version 2.5.1 before 2026-08-12.",
        translated_text="Vui lòng nâng cấp lên phiên bản 2.5.1 trước 2026-08-12.",
        target_language=Language.VIETNAMESE,
    )
    assert result.ok is True


def test_url_not_preserved_rejected() -> None:
    result = validate_translation(
        source_text="See https://example.com/docs for details.",
        translated_text="Xem tài liệu để biết thêm chi tiết.",
        target_language=Language.VIETNAMESE,
    )
    assert result.reason == "identifiers_not_preserved"


def test_length_ratio_too_short_rejected() -> None:
    long_source = (
        "This is a reasonably long sentence that should translate to something of similar length."
    )
    result = validate_translation(
        source_text=long_source,
        translated_text="Ok.",
        target_language=Language.VIETNAMESE,
    )
    assert result.ok is False
    assert result.reason == "length_ratio"


def test_length_ratio_too_long_rejected() -> None:
    # Long but non-repetitive, so this exercises length_ratio specifically
    # rather than tripping the repetition check first.
    long_translation = (
        "Xin chào các bạn, hôm nay chúng ta sẽ thảo luận về rất nhiều chủ đề "
        "khác nhau trong buổi họp này, bao gồm kế hoạch dự án, tiến độ công "
        "việc, và các vấn đề cần giải quyết trong thời gian tới một cách chi "
        "tiết và đầy đủ hơn so với những lần trước."
    )
    result = validate_translation(
        source_text="Hi.",
        translated_text=long_translation,
        target_language=Language.VIETNAMESE,
    )
    assert result.ok is False
    assert result.reason == "length_ratio"
