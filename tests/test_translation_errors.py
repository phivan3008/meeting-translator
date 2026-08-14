"""Tests for typed translation errors and backend-exception classification."""

from __future__ import annotations

from server.translation.errors import (
    TranslationErrorKind,
    TranslationFailedError,
    TranslationOverloadedError,
    TranslationTimeoutError,
    classify_backend_error,
)
from shared.protocol.enums import ErrorCode


def test_error_kinds_and_retryable_flags() -> None:
    assert TranslationTimeoutError("x").kind is TranslationErrorKind.TIMEOUT
    assert TranslationTimeoutError("x").retryable is True
    assert TranslationOverloadedError("x").kind is TranslationErrorKind.OVERLOADED
    assert TranslationOverloadedError("x").retryable is True
    assert TranslationFailedError("x").kind is TranslationErrorKind.FAILED
    assert TranslationFailedError("x").retryable is False


def test_error_code_mapping() -> None:
    assert TranslationTimeoutError("x").error_code is ErrorCode.TRANSLATION_TIMEOUT
    assert TranslationOverloadedError("x").error_code is ErrorCode.OVERLOADED
    assert TranslationFailedError("x").error_code is ErrorCode.TRANSLATION_FAILED


def test_classify_backend_error_detects_timeout() -> None:
    class ReadTimeout(Exception):
        pass

    mapped = classify_backend_error(ReadTimeout("the request timed out"))
    assert isinstance(mapped, TranslationTimeoutError)


def test_classify_backend_error_detects_connection_issue() -> None:
    class ConnectError(Exception):
        pass

    mapped = classify_backend_error(ConnectError("connection refused"))
    assert isinstance(mapped, TranslationOverloadedError)


def test_classify_backend_error_defaults_to_failed() -> None:
    mapped = classify_backend_error(ValueError("unexpected payload"))
    assert isinstance(mapped, TranslationFailedError)
