"""Automatic speech recognition (final ASR) package.

Exposes the ASR model interface, a deterministic scripted model, the
faster-whisper adapter, typed errors, configuration/result types and the final
transcription service that reconciles completed utterances into
``utterance.final`` events (without translation).
"""

from __future__ import annotations

from server.asr.errors import (
    AsrDecodeError,
    AsrError,
    AsrErrorKind,
    AsrOutOfMemoryError,
    AsrTimeoutError,
    ModelUnavailableError,
    classify_backend_error,
)
from server.asr.fake import ScriptedAsrModel
from server.asr.interface import AsrModel
from server.asr.types import (
    AsrConfig,
    AsrRequest,
    TranscriptionResult,
    TranscriptionSegment,
)
from server.asr.whisper import WhisperAsrModel
from server.asr.worker import FinalTranscriber, build_asr_error_event

__all__ = [
    "AsrConfig",
    "AsrDecodeError",
    "AsrError",
    "AsrErrorKind",
    "AsrModel",
    "AsrOutOfMemoryError",
    "AsrRequest",
    "AsrTimeoutError",
    "FinalTranscriber",
    "ModelUnavailableError",
    "ScriptedAsrModel",
    "TranscriptionResult",
    "TranscriptionSegment",
    "WhisperAsrModel",
    "build_asr_error_event",
    "classify_backend_error",
]
