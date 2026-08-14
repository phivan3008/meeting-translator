"""Tests for translation configuration and request/outcome value types."""

from __future__ import annotations

import pytest

from server.translation.types import (
    FIXED_TEMPERATURE,
    FIXED_TOP_P,
    GlossaryEntry,
    TranslationConfig,
    TranslationOutcome,
    TranslationRequest,
)
from shared.protocol.enums import Language, TranslationStatus
from shared.settings import Settings


def test_config_defaults_match_documented_baseline() -> None:
    config = TranslationConfig()
    assert config.model == "qwen3.6-27b-translate"
    assert config.temperature == FIXED_TEMPERATURE
    assert config.top_p == FIXED_TOP_P


def test_config_from_settings_maps_fields() -> None:
    settings = Settings(_env_file=None)  # type: ignore[call-arg]
    config = TranslationConfig.from_settings(settings)
    assert config.base_url == settings.vllm_base_url
    assert config.api_key == settings.vllm_api_key
    assert config.model == settings.vllm_model
    assert config.max_input_tokens == settings.translation_max_input_tokens
    assert config.max_output_tokens == settings.translation_max_output_tokens
    assert config.timeout_ms == settings.translation_timeout_ms
    assert config.max_concurrency == settings.translation_max_concurrency
    # Temperature/top-p are fixed, not settings-driven.
    assert config.temperature == FIXED_TEMPERATURE
    assert config.top_p == FIXED_TOP_P


def test_config_rejects_invalid_fields() -> None:
    with pytest.raises(ValueError):
        TranslationConfig(base_url="")
    with pytest.raises(ValueError):
        TranslationConfig(model="")
    with pytest.raises(ValueError):
        TranslationConfig(max_input_tokens=0)
    with pytest.raises(ValueError):
        TranslationConfig(max_output_tokens=0)
    with pytest.raises(ValueError):
        TranslationConfig(timeout_ms=0)
    with pytest.raises(ValueError):
        TranslationConfig(max_concurrency=0)
    with pytest.raises(ValueError):
        TranslationConfig(temperature=-0.1)
    with pytest.raises(ValueError):
        TranslationConfig(top_p=0.0)
    with pytest.raises(ValueError):
        TranslationConfig(top_p=1.1)


def test_glossary_entry_rejects_empty_fields() -> None:
    with pytest.raises(ValueError):
        GlossaryEntry(term="", translation="x")
    with pytest.raises(ValueError):
        GlossaryEntry(term="x", translation="")


def test_translation_request_rejects_empty_text() -> None:
    with pytest.raises(ValueError):
        TranslationRequest(
            text="   ", source_language=Language.JAPANESE, target_language=Language.VIETNAMESE
        )


def test_translation_request_rejects_same_source_and_target() -> None:
    with pytest.raises(ValueError):
        TranslationRequest(
            text="hello", source_language=Language.JAPANESE, target_language=Language.JAPANESE
        )


def test_translation_outcome_completed_requires_text() -> None:
    with pytest.raises(ValueError):
        TranslationOutcome(text=None, status=TranslationStatus.COMPLETED)


def test_translation_outcome_failed_forbids_text() -> None:
    with pytest.raises(ValueError):
        TranslationOutcome(text="oops", status=TranslationStatus.FAILED)


def test_translation_outcome_valid_cases() -> None:
    completed = TranslationOutcome(text="Xin chào", status=TranslationStatus.COMPLETED)
    assert completed.text == "Xin chào"
    failed = TranslationOutcome(text=None, status=TranslationStatus.FAILED, issue="timeout")
    assert failed.issue == "timeout"
