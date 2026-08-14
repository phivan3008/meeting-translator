"""Value types, configuration and result models for Qwen/vLLM translation.

Framework-independent (no httpx, asyncio or vLLM imports) so config
validation and request/outcome construction are fully unit-testable.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from shared.protocol.enums import Language, TranslationStatus

# Fixed per docs/TRANSLATION.md and docs/ARCHITECTURE.md baseline: temperature
# 0, top-p 1, no output streaming. Not environment-configurable.
FIXED_TEMPERATURE = 0.0
FIXED_TOP_P = 1.0

# At most two prior final sentences may be included as non-translatable
# context (docs/TRANSLATION.md "Request policy").
MAX_CONTEXT_SENTENCES = 2


@dataclass(frozen=True)
class TranslationConfig:
    """vLLM OpenAI-compatible client configuration.

    Mirrors the ``vllm_*``/``translation_*`` settings baseline. Temperature
    and top-p are fixed constants, not configurable, per the documented
    architecture.
    """

    base_url: str = "http://localhost:8000/v1"
    api_key: str = "EMPTY"
    model: str = "qwen3.6-27b-translate"
    max_input_tokens: int = 768
    max_output_tokens: int = 256
    timeout_ms: int = 3000
    max_concurrency: int = 8
    temperature: float = FIXED_TEMPERATURE
    top_p: float = FIXED_TOP_P

    def __post_init__(self) -> None:
        if not self.base_url:
            raise ValueError("base_url must be a non-empty string")
        if not self.model:
            raise ValueError("model must be a non-empty string")
        if self.max_input_tokens < 1:
            raise ValueError("max_input_tokens must be >= 1")
        if self.max_output_tokens < 1:
            raise ValueError("max_output_tokens must be >= 1")
        if self.timeout_ms < 1:
            raise ValueError("timeout_ms must be >= 1")
        if self.max_concurrency < 1:
            raise ValueError("max_concurrency must be >= 1")
        if self.temperature < 0.0:
            raise ValueError("temperature must be >= 0")
        if not 0.0 < self.top_p <= 1.0:
            raise ValueError("top_p must be in (0, 1]")

    @classmethod
    def from_settings(cls, settings: object) -> TranslationConfig:
        """Build a config from an application settings object.

        Reads the ``vllm_*``/``translation_*`` fields; any missing attribute
        falls back to the documented baseline default. Temperature/top-p are
        always the fixed constants regardless of settings.
        """
        return cls(
            base_url=str(getattr(settings, "vllm_base_url", cls.base_url)),
            api_key=str(getattr(settings, "vllm_api_key", cls.api_key)),
            model=str(getattr(settings, "vllm_model", cls.model)),
            max_input_tokens=int(
                getattr(settings, "translation_max_input_tokens", cls.max_input_tokens)
            ),
            max_output_tokens=int(
                getattr(settings, "translation_max_output_tokens", cls.max_output_tokens)
            ),
            timeout_ms=int(getattr(settings, "translation_timeout_ms", cls.timeout_ms)),
            max_concurrency=int(
                getattr(settings, "translation_max_concurrency", cls.max_concurrency)
            ),
        )


@dataclass(frozen=True)
class GlossaryEntry:
    """A single source-term -> target-translation glossary mapping."""

    term: str
    translation: str

    def __post_init__(self) -> None:
        if not self.term:
            raise ValueError("term must be a non-empty string")
        if not self.translation:
            raise ValueError("translation must be a non-empty string")


@dataclass(frozen=True)
class TranslationRequest:
    """A single finalized-utterance translation request.

    ``text`` is the finalized transcription only -- partial ASR is never
    translated. ``context_sentences`` should hold at most
    :data:`MAX_CONTEXT_SENTENCES` prior final sentences; extra entries are
    trimmed by the prompt builder, not rejected here.
    """

    text: str
    source_language: Language
    target_language: Language
    glossary: tuple[GlossaryEntry, ...] = field(default_factory=tuple)
    context_sentences: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not self.text.strip():
            raise ValueError("text must be non-empty")
        if self.source_language == self.target_language:
            raise ValueError("source_language and target_language must differ")


@dataclass(frozen=True)
class TranslationOutcome:
    """The result of one translation attempt (initial or retry)."""

    text: str | None
    status: TranslationStatus
    issue: str | None = None

    def __post_init__(self) -> None:
        if self.status is TranslationStatus.COMPLETED and not self.text:
            raise ValueError("a COMPLETED outcome must carry non-empty text")
        if self.status is TranslationStatus.FAILED and self.text is not None:
            raise ValueError("a FAILED outcome must not carry text")
