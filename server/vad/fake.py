"""Deterministic VAD model for tests and offline pipeline validation.

:class:`ScriptedVadModel` returns a predetermined sequence of speech
probabilities, one per :meth:`probability` call, independent of the audio bytes.
This makes utterance segmentation fully deterministic without any model weights.
"""

from __future__ import annotations

from collections.abc import Sequence


class ScriptedVadModel:
    """Return probabilities from a fixed script.

    Once the script is exhausted the final value is repeated, so callers may
    supply a short prefix followed by a steady tail. :meth:`reset` rewinds to
    the start of the script.
    """

    def __init__(self, probabilities: Sequence[float]) -> None:
        if not probabilities:
            raise ValueError("probabilities must be non-empty")
        for value in probabilities:
            if not 0.0 <= value <= 1.0:
                raise ValueError("probabilities must be in [0, 1]")
        self._probabilities = list(probabilities)
        self._index = 0

    def probability(self, frame: bytes, /) -> float:
        value = self._probabilities[min(self._index, len(self._probabilities) - 1)]
        self._index += 1
        return value

    def reset(self) -> None:
        self._index = 0
