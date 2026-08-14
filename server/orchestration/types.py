"""Configuration and shared type aliases for finalization orchestration."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from shared.protocol.messages import (
    ErrorEvent,
    TranscriptionPartial,
    TranslationUpdated,
    UtteranceFinal,
)

# Any protocol event the orchestrator may publish. A caller-supplied async
# sink (e.g. one that serializes and sends over a WebSocket, or a test
# double that appends to a list) receives every event in publish order.
OrchestratorEvent = TranscriptionPartial | UtteranceFinal | TranslationUpdated | ErrorEvent
PublishEvent = Callable[[OrchestratorEvent], Awaitable[None]]


@dataclass(frozen=True)
class CompletenessConfig:
    """Configuration for the optional low-priority Qwen completeness check.

    Mirrors the ``completeness_*`` settings baseline
    (docs/TRANSLATION.md/docs/ARCHITECTURE.md).
    """

    enabled: bool = True
    timeout_ms: int = 250
    skip_queue_depth: int = 4
    max_tokens: int = 20
    min_confidence: float = 0.55

    def __post_init__(self) -> None:
        if self.timeout_ms < 1:
            raise ValueError("timeout_ms must be >= 1")
        if self.skip_queue_depth < 0:
            raise ValueError("skip_queue_depth must be >= 0")
        if self.max_tokens < 1:
            raise ValueError("max_tokens must be >= 1")
        if not 0.0 <= self.min_confidence <= 1.0:
            raise ValueError("min_confidence must be in [0, 1]")

    @classmethod
    def from_settings(cls, settings: object) -> CompletenessConfig:
        """Build a config from an application settings object.

        Reads the ``completeness_*`` fields; any missing attribute falls
        back to the documented baseline default.
        """
        return cls(
            enabled=bool(getattr(settings, "completeness_enabled", cls.enabled)),
            timeout_ms=int(getattr(settings, "completeness_timeout_ms", cls.timeout_ms)),
            skip_queue_depth=int(
                getattr(settings, "completeness_skip_queue_depth", cls.skip_queue_depth)
            ),
            max_tokens=int(getattr(settings, "completeness_max_tokens", cls.max_tokens)),
            min_confidence=float(
                getattr(settings, "completeness_min_confidence", cls.min_confidence)
            ),
        )
