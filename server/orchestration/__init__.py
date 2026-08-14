"""Completeness and finalization orchestration package.

Exposes the deterministic completeness heuristic, its configuration, and the
:class:`~server.orchestration.pipeline.UtteranceOrchestrator` that composes
VAD, partial ASR, final ASR, translation and the optional low-priority
semantic-completeness check into the full per-session pipeline documented in
``docs/ARCHITECTURE.md``.
"""

from __future__ import annotations

from server.orchestration.heuristics import (
    DEFAULT_ENDING_SIGNALS,
    DEFAULT_SENTENCE_END_PUNCTUATION,
    HeuristicConfig,
    HeuristicVerdict,
    evaluate_heuristic,
)
from server.orchestration.pipeline import UtteranceOrchestrator
from server.orchestration.types import CompletenessConfig, OrchestratorEvent, PublishEvent

__all__ = [
    "DEFAULT_ENDING_SIGNALS",
    "DEFAULT_SENTENCE_END_PUNCTUATION",
    "CompletenessConfig",
    "HeuristicConfig",
    "HeuristicVerdict",
    "OrchestratorEvent",
    "PublishEvent",
    "UtteranceOrchestrator",
    "evaluate_heuristic",
]
