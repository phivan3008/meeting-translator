"""Tests for VAD configuration and settings mapping."""

from __future__ import annotations

import pytest

from server.vad.types import VadConfig
from shared.settings import Settings


def test_from_settings_maps_all_fields() -> None:
    settings = Settings(_env_file=None)  # type: ignore[call-arg]
    config = VadConfig.from_settings(settings)
    assert config.threshold == settings.vad_threshold
    assert config.speech_start_ms == settings.vad_speech_start_ms
    assert config.min_speech_ms == settings.vad_min_speech_ms
    assert config.soft_silence_ms == settings.vad_soft_silence_ms
    assert config.hard_silence_ms == settings.vad_hard_silence_ms
    assert config.speech_pad_before_ms == settings.vad_speech_pad_before_ms
    assert config.speech_pad_after_ms == settings.vad_speech_pad_after_ms
    assert config.max_utterance_ms == settings.vad_max_utterance_ms


def test_invalid_threshold_rejected() -> None:
    with pytest.raises(ValueError):
        VadConfig(threshold=1.5)


def test_hard_silence_below_soft_rejected() -> None:
    with pytest.raises(ValueError):
        VadConfig(soft_silence_ms=500, hard_silence_ms=400)


def test_negative_duration_rejected() -> None:
    with pytest.raises(ValueError):
        VadConfig(speech_start_ms=-1)
