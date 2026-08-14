"""Typed ASR errors and mapping to protocol error codes.

Concrete adapters raise these typed errors for model unavailability, timeout and
out-of-memory conditions instead of leaking backend-specific exceptions. The
gateway maps them to a protocol ``error`` event with :class:`ErrorCode`.
"""

from __future__ import annotations

from enum import Enum

from shared.protocol.enums import ErrorCode


class AsrErrorKind(Enum):
    """Category of an ASR failure."""

    MODEL_UNAVAILABLE = "model_unavailable"
    TIMEOUT = "timeout"
    OUT_OF_MEMORY = "out_of_memory"
    DECODE_FAILED = "decode_failed"
    CIRCUIT_OPEN = "circuit_open"


class AsrError(Exception):
    """Base class for typed ASR failures.

    ``retryable`` indicates whether re-submitting the same request may succeed
    (e.g. a transient timeout) versus a persistent fault (e.g. a decode error).
    """

    kind: AsrErrorKind = AsrErrorKind.DECODE_FAILED
    retryable: bool = False

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message

    @property
    def error_code(self) -> ErrorCode:
        """Protocol error code for the ``error`` event (always ASR_FAILED)."""
        return ErrorCode.ASR_FAILED


class ModelUnavailableError(AsrError):
    """The ASR model could not be loaded or initialized."""

    kind = AsrErrorKind.MODEL_UNAVAILABLE
    retryable = False


class AsrTimeoutError(AsrError):
    """Decoding exceeded the configured time budget."""

    kind = AsrErrorKind.TIMEOUT
    retryable = True


class AsrOutOfMemoryError(AsrError):
    """The accelerator ran out of memory during decoding."""

    kind = AsrErrorKind.OUT_OF_MEMORY
    retryable = True


class AsrDecodeError(AsrError):
    """Decoding failed for a non-recoverable reason."""

    kind = AsrErrorKind.DECODE_FAILED
    retryable = False


class AsrCircuitOpenError(AsrError):
    """The ASR circuit breaker is open; the backend call was skipped."""

    kind = AsrErrorKind.CIRCUIT_OPEN
    retryable = True

    @property
    def error_code(self) -> ErrorCode:
        return ErrorCode.OVERLOADED


def classify_backend_error(exc: BaseException) -> AsrError:
    """Map a backend exception to a typed :class:`AsrError`.

    Uses the exception type name and message to detect out-of-memory and
    model-load failures without importing GPU/back-end libraries.
    """
    name = type(exc).__name__.lower()
    text = str(exc).lower()
    if "outofmemory" in name or "out of memory" in text or "cuda oom" in text:
        return AsrOutOfMemoryError(str(exc) or "ASR out of memory")
    if "notfound" in name or "no such file" in text or "failed to load" in text:
        return ModelUnavailableError(str(exc) or "ASR model unavailable")
    return AsrDecodeError(str(exc) or "ASR decode failed")
