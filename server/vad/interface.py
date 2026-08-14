"""Voice-activity-detection model interface.

The utterance state machine depends only on :class:`VadModel`, which returns a
speech probability in ``[0, 1]`` for a single audio frame. Concrete models
(Silero, or a deterministic scripted model for tests) implement this Protocol.

Implementations are synchronous CPU code and MUST be run in a worker thread or
executor; they must never block the asyncio event loop.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class VadModel(Protocol):
    """Returns a speech probability for a mono 16 kHz PCM S16LE frame."""

    def probability(self, frame: bytes, /) -> float:
        """Return the speech probability in ``[0, 1]`` for ``frame``."""
        ...

    def reset(self) -> None:
        """Reset any internal recurrent state between utterances/streams."""
        ...
