"""Qwen/vLLM final translation package.

Exposes the translation client interface, a deterministic scripted client,
the vLLM OpenAI-compatible adapter, typed errors, prompt builders, the
output validator, the priority queue, the final translation service that
attaches a completed (or failed) translation outcome to an ``utterance.final``
event (or produces a ``translation.updated`` event after a later retry), and
the optional low-priority semantic-completeness classifier.
"""

from __future__ import annotations

from server.translation.client import VllmTranslationClient
from server.translation.completeness import CompletenessClassifier, CompletenessOutcome
from server.translation.errors import (
    TranslationError,
    TranslationErrorKind,
    TranslationFailedError,
    TranslationOverloadedError,
    TranslationTimeoutError,
    classify_backend_error,
)
from server.translation.fake import RecordedChatCall, ScriptedTranslationClient
from server.translation.interface import TranslationClient
from server.translation.prompts import (
    build_completeness_prompt,
    build_glossary_block,
    build_system_prompt,
    build_user_content,
    select_relevant_glossary,
)
from server.translation.queue import TranslationPriority, TranslationQueue, should_skip_completeness
from server.translation.types import (
    FIXED_TEMPERATURE,
    FIXED_TOP_P,
    MAX_CONTEXT_SENTENCES,
    GlossaryEntry,
    TranslationConfig,
    TranslationOutcome,
    TranslationRequest,
)
from server.translation.validator import ValidationResult, validate_translation
from server.translation.worker import FinalTranslator, apply_translation, build_translation_updated

__all__ = [
    "FIXED_TEMPERATURE",
    "FIXED_TOP_P",
    "MAX_CONTEXT_SENTENCES",
    "CompletenessClassifier",
    "CompletenessOutcome",
    "FinalTranslator",
    "GlossaryEntry",
    "RecordedChatCall",
    "ScriptedTranslationClient",
    "TranslationClient",
    "TranslationConfig",
    "TranslationError",
    "TranslationErrorKind",
    "TranslationFailedError",
    "TranslationOutcome",
    "TranslationOverloadedError",
    "TranslationPriority",
    "TranslationQueue",
    "TranslationRequest",
    "TranslationTimeoutError",
    "ValidationResult",
    "VllmTranslationClient",
    "apply_translation",
    "build_completeness_prompt",
    "build_glossary_block",
    "build_system_prompt",
    "build_translation_updated",
    "build_user_content",
    "classify_backend_error",
    "select_relevant_glossary",
    "should_skip_completeness",
    "validate_translation",
]
