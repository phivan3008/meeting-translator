"""Tests for ASR configuration and typed errors."""

from __future__ import annotations

import pytest

from server.asr.errors import (
    AsrDecodeError,
    AsrErrorKind,
    AsrOutOfMemoryError,
    AsrTimeoutError,
    ModelUnavailableError,
    classify_backend_error,
)
from server.asr.types import AsrConfig
from shared.protocol.enums import ErrorCode
from shared.settings import Settings


def test_config_from_settings_maps_fields() -> None:
    settings = Settings(_env_file=None)  # type: ignore[call-arg]
    config = AsrConfig.from_settings(settings)
    assert config.model == settings.whisper_model
    assert config.device == settings.whisper_device
    assert config.compute_type == settings.whisper_compute_type
    assert config.final_beam_size == settings.whisper_final_beam_size
    assert config.partial_beam_size == settings.whisper_partial_beam_size
    assert config.temperature == settings.whisper_temperature
    assert config.condition_on_previous_text == settings.whisper_condition_on_previous_text


def test_config_rejects_invalid_beam_size() -> None:
    with pytest.raises(ValueError):
        AsrConfig(final_beam_size=0)


def test_config_rejects_invalid_partial_beam_size() -> None:
    with pytest.raises(ValueError):
        AsrConfig(partial_beam_size=0)


def test_config_rejects_negative_temperature() -> None:
    with pytest.raises(ValueError):
        AsrConfig(temperature=-0.1)


def test_config_rejects_empty_model() -> None:
    with pytest.raises(ValueError):
        AsrConfig(model="")


def test_error_kinds_and_retryable_flags() -> None:
    assert ModelUnavailableError("x").kind is AsrErrorKind.MODEL_UNAVAILABLE
    assert ModelUnavailableError("x").retryable is False
    assert AsrTimeoutError("x").kind is AsrErrorKind.TIMEOUT
    assert AsrTimeoutError("x").retryable is True
    assert AsrOutOfMemoryError("x").kind is AsrErrorKind.OUT_OF_MEMORY
    assert AsrOutOfMemoryError("x").retryable is True
    assert AsrDecodeError("x").kind is AsrErrorKind.DECODE_FAILED
    assert AsrDecodeError("x").retryable is False


def test_all_errors_map_to_asr_failed_code() -> None:
    for error in (
        ModelUnavailableError("a"),
        AsrTimeoutError("b"),
        AsrOutOfMemoryError("c"),
        AsrDecodeError("d"),
    ):
        assert error.error_code is ErrorCode.ASR_FAILED


def test_classify_backend_error_detects_oom() -> None:
    class CudaOutOfMemoryError(RuntimeError):
        pass

    mapped = classify_backend_error(CudaOutOfMemoryError("CUDA out of memory"))
    assert isinstance(mapped, AsrOutOfMemoryError)


def test_classify_backend_error_detects_missing_model() -> None:
    mapped = classify_backend_error(RuntimeError("failed to load model"))
    assert isinstance(mapped, ModelUnavailableError)


def test_classify_backend_error_defaults_to_decode() -> None:
    mapped = classify_backend_error(ValueError("weird tensor shape"))
    assert isinstance(mapped, AsrDecodeError)
