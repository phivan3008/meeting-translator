"""Silero VAD adapter with lazy model initialization.

The real Silero model and its ``torch`` dependency are imported lazily on first
use so that importing this module (and running the CPU test suite) never pulls
in heavy dependencies or downloads weights. Silero runs on CPU per the project
constraints. Exercising this adapter requires the model and is performed
manually (marked ``gpu`` where appropriate); it is not part of the default CPU
suite.

Silero expects fixed-size analysis windows (512 samples at 16 kHz). Incoming
frames are buffered until a full window is available; the most recent window's
probability is returned for intermediate frames.
"""

from __future__ import annotations

import logging
from typing import Any

from server.vad.types import SAMPLE_RATE_HZ

_LOG = logging.getLogger("server.vad.silero")

# Silero 16 kHz analysis window size in samples.
_WINDOW_SAMPLES = 512
_WINDOW_BYTES = _WINDOW_SAMPLES * 2


class SileroVadModel:
    """Adapter exposing :class:`~server.vad.interface.VadModel` over Silero."""

    def __init__(self) -> None:
        self._model: Any = None
        self._torch: Any = None
        self._buffer = bytearray()
        self._last_probability = 0.0

    def _ensure_loaded(self) -> None:
        if self._model is not None:
            return
        import torch
        from silero_vad import load_silero_vad

        self._torch = torch
        self._model = load_silero_vad()

    def probability(self, frame: bytes, /) -> float:
        self._ensure_loaded()
        self._buffer.extend(frame)
        while len(self._buffer) >= _WINDOW_BYTES:
            window = bytes(self._buffer[:_WINDOW_BYTES])
            del self._buffer[:_WINDOW_BYTES]
            self._last_probability = self._score_window(window)
        return self._last_probability

    def _score_window(self, window: bytes) -> float:
        torch = self._torch
        import numpy as np

        samples = np.frombuffer(window, dtype="<i2").astype(np.float32) / 32768.0
        tensor = torch.from_numpy(samples)
        with torch.no_grad():
            score = self._model(tensor, SAMPLE_RATE_HZ)
        probability = float(score.item())
        # DEBUG-only: not raw audio, just a scalar score -- opt in with
        # LOG_LEVEL=DEBUG when diagnosing segmentation timing.
        _LOG.debug("silero window probability=%.4f", probability)
        return probability

    def reset(self) -> None:
        self._buffer.clear()
        self._last_probability = 0.0
        if self._model is not None and hasattr(self._model, "reset_states"):
            self._model.reset_states()
