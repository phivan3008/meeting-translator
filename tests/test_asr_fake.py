"""Tests for the scripted ASR test double."""

from __future__ import annotations

import pytest

from server.asr.errors import AsrDecodeError
from server.asr.fake import ScriptedAsrModel
from server.asr.types import AsrRequest, TranscriptionResult
from shared.protocol.enums import Language


def _request(language: Language = Language.JAPANESE) -> AsrRequest:
    return AsrRequest(
        audio=b"\x00\x00" * 160,
        language=language,
        beam_size=3,
        temperature=0.0,
        condition_on_previous_text=True,
    )


def _result(text: str) -> TranscriptionResult:
    return TranscriptionResult(text=text, language=Language.JAPANESE, duration_ms=10)


def test_returns_scripted_results_in_order() -> None:
    model = ScriptedAsrModel([_result("one"), _result("two")])
    assert model.transcribe(_request()).text == "one"
    assert model.transcribe(_request()).text == "two"
    # Exhausted -> repeats the last outcome.
    assert model.transcribe(_request()).text == "two"


def test_records_requests() -> None:
    model = ScriptedAsrModel([_result("hi")])
    request = _request(Language.VIETNAMESE)
    model.transcribe(request)
    assert model.call_count == 1
    assert model.requests[0] is request
    assert model.requests[0].language is Language.VIETNAMESE


def test_raises_scripted_error() -> None:
    model = ScriptedAsrModel([AsrDecodeError("boom")])
    with pytest.raises(AsrDecodeError):
        model.transcribe(_request())


def test_rejects_empty_outcomes() -> None:
    with pytest.raises(ValueError):
        ScriptedAsrModel([])


def test_request_duration_ms() -> None:
    # 160 samples * 2 bytes = 320 bytes = 10 ms.
    assert _request().duration_ms == 10
