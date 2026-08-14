"""Typed translation errors and mapping to protocol error codes.

Concrete adapters (the vLLM client) raise these typed errors for timeout,
overload and other backend failures instead of leaking `httpx`-specific
exceptions. Callers never let these propagate as protocol `error` events for
a single translation attempt -- translation failure degrades to a
``translation_status`` on the final event, never blocking final
transcription -- but the typed hierarchy and `error_code` mapping stay
available for logging/metrics and for the rare case a caller does want a
protocol `error` event.
"""

from __future__ import annotations

from enum import Enum

from shared.protocol.enums import ErrorCode


class TranslationErrorKind(Enum):
    """Category of a translation backend failure."""

    TIMEOUT = "timeout"
    OVERLOADED = "overloaded"
    FAILED = "failed"


class TranslationError(Exception):
    """Base class for typed translation failures.

    ``retryable`` indicates whether re-submitting the same request may
    succeed (timeout/overload) versus a persistent fault (malformed
    response, non-2xx status other than overload).
    """

    kind: TranslationErrorKind = TranslationErrorKind.FAILED
    retryable: bool = False

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message

    @property
    def error_code(self) -> ErrorCode:
        """Protocol error code for this failure kind."""
        return _ERROR_CODE_BY_KIND[self.kind]


class TranslationTimeoutError(TranslationError):
    """The translation request exceeded the configured time budget."""

    kind = TranslationErrorKind.TIMEOUT
    retryable = True


class TranslationOverloadedError(TranslationError):
    """The translation backend reported it is overloaded (e.g. HTTP 429/503)."""

    kind = TranslationErrorKind.OVERLOADED
    retryable = True


class TranslationFailedError(TranslationError):
    """Translation failed for a non-recoverable reason."""

    kind = TranslationErrorKind.FAILED
    retryable = False


_ERROR_CODE_BY_KIND: dict[TranslationErrorKind, ErrorCode] = {
    TranslationErrorKind.TIMEOUT: ErrorCode.TRANSLATION_TIMEOUT,
    TranslationErrorKind.OVERLOADED: ErrorCode.OVERLOADED,
    TranslationErrorKind.FAILED: ErrorCode.TRANSLATION_FAILED,
}


def classify_backend_error(exc: BaseException) -> TranslationError:
    """Map a backend exception (e.g. an `httpx` error) to a typed error.

    Uses the exception type name and message to detect timeouts and
    connection/overload conditions without requiring callers to import
    `httpx` exception types directly.
    """
    name = type(exc).__name__.lower()
    text = str(exc).lower()
    if "timeout" in name or "timed out" in text:
        return TranslationTimeoutError(str(exc) or "translation request timed out")
    if "connect" in name or "connection" in text:
        return TranslationOverloadedError(str(exc) or "translation backend unreachable")
    return TranslationFailedError(str(exc) or "translation request failed")
