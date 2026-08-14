"""Deterministic ASR test double.

``ScriptedAsrModel`` returns pre-programmed results (or raises pre-programmed
errors) in sequence, records the requests it received, and is fully synchronous
and dependency-free. It is used for CPU tests of the final transcription service
and the finalization-to-event integration.
"""

from __future__ import annotations

from collections.abc import Sequence

from server.asr.errors import AsrError
from server.asr.types import AsrRequest, TranscriptionResult


class ScriptedAsrModel:
    """Return scripted results/errors per :meth:`transcribe` call."""

    def __init__(self, outcomes: Sequence[TranscriptionResult | AsrError]) -> None:
        if not outcomes:
            raise ValueError("outcomes must be non-empty")
        self._outcomes: list[TranscriptionResult | AsrError] = list(outcomes)
        self._index = 0
        self.requests: list[AsrRequest] = []

    def transcribe(self, request: AsrRequest, /) -> TranscriptionResult:
        self.requests.append(request)
        outcome = self._outcomes[min(self._index, len(self._outcomes) - 1)]
        self._index += 1
        if isinstance(outcome, AsrError):
            raise outcome
        return outcome

    @property
    def call_count(self) -> int:
        return len(self.requests)
