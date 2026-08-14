"""faster-whisper ASR adapter with lazy model initialization.

The real ``faster_whisper`` package and its heavy dependencies are imported
lazily on first use so that importing this module (and running the CPU test
suite) never pulls in GPU libraries or downloads weights. Exercising this
adapter requires the model and a GPU; it is performed manually (marked ``gpu``)
and is not part of the default CPU suite.
"""

from __future__ import annotations

from typing import Any

from server.asr.errors import ModelUnavailableError, classify_backend_error
from server.asr.types import (
    AsrConfig,
    AsrRequest,
    TranscriptionResult,
    TranscriptionSegment,
)


class WhisperAsrModel:
    """Adapter exposing :class:`~server.asr.interface.AsrModel` over faster-whisper."""

    def __init__(self, config: AsrConfig) -> None:
        self._config = config
        self._model: Any = None

    def _ensure_loaded(self) -> None:
        if self._model is not None:
            return
        try:
            from faster_whisper import WhisperModel
        except ImportError as exc:  # pragma: no cover - exercised on GPU host
            raise ModelUnavailableError(
                "faster-whisper is not installed; install the 'gpu' extra"
            ) from exc
        try:
            self._model = WhisperModel(
                self._config.model,
                device=self._config.device,
                compute_type=self._config.compute_type,
            )
        except Exception as exc:  # pragma: no cover - exercised on GPU host
            raise classify_backend_error(exc) from exc

    def transcribe(self, request: AsrRequest, /) -> TranscriptionResult:
        self._ensure_loaded()
        samples = self._to_float32(request.audio)
        try:
            segments_iter, info = self._model.transcribe(
                samples,
                language=request.language.value,
                beam_size=request.beam_size,
                temperature=request.temperature,
                condition_on_previous_text=request.condition_on_previous_text,
                initial_prompt=request.previous_text or None,
            )
            segments = tuple(
                TranscriptionSegment(
                    text=segment.text.strip(),
                    start_ms=int(segment.start * 1000),
                    end_ms=int(segment.end * 1000),
                    avg_logprob=getattr(segment, "avg_logprob", None),
                )
                for segment in segments_iter
            )
        except Exception as exc:  # pragma: no cover - exercised on GPU host
            raise classify_backend_error(exc) from exc

        text = " ".join(segment.text for segment in segments if segment.text).strip()
        return TranscriptionResult(
            text=text,
            language=request.language,
            duration_ms=request.duration_ms,
            segments=segments,
        )

    @staticmethod
    def _to_float32(audio: bytes) -> Any:  # pragma: no cover - needs numpy/GPU
        import numpy as np

        return np.frombuffer(audio, dtype="<i2").astype(np.float32) / 32768.0
