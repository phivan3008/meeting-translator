"""Automatic-speech-recognition model interface.

The final transcription service depends only on :class:`AsrModel`. Concrete
models (faster-whisper, or a deterministic scripted model for tests) implement
this Protocol.

Implementations are synchronous CPU/GPU code and MUST be run in a worker thread
or executor; they must never block the asyncio event loop.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from server.asr.types import AsrRequest, TranscriptionResult


@runtime_checkable
class AsrModel(Protocol):
    """Transcribes completed utterance audio into text."""

    def transcribe(self, request: AsrRequest, /) -> TranscriptionResult:
        """Decode ``request.audio`` and return the transcription.

        Implementations should raise a :class:`server.asr.errors.AsrError` (or a
        subclass) for model unavailability, timeout or out-of-memory conditions.
        """
        ...
