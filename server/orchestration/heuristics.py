"""Deterministic completeness heuristic for soft-silence decisions.

Pure, framework-independent text/duration logic (no asyncio, vLLM or model
weights), matching the style of ``server.asr.stable_prefix``. Evaluates four
signals over the current partial transcription of an in-progress utterance:

1. Sentence-ending punctuation on the stable (committed) text.
2. Stable duration -- the utterance's confirmed speech time so far
   (``speech_ms``); very short bursts are treated as ambiguous even with a
   punctuation/ending-signal match, since they are unreliable.
3. Unstable tail length -- a long uncommitted tail means ASR is still
   actively catching up, so no confident decision can be made yet.
4. Configurable language-specific sentence-ending signal words/phrases
   (e.g. Japanese ``desu``/``masu`` forms, Vietnamese final particles).

The result is either a definite verdict (``ambiguous=False``) that the
caller may act on directly, or an ``ambiguous=True`` verdict whose
``complete`` value is the deterministic fallback to use if the optional
low-priority Qwen completeness check (docs/TRANSLATION.md) is disabled,
skipped under queue pressure, or returns an unknown/low-confidence result.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from shared.protocol.enums import Language

DEFAULT_SENTENCE_END_PUNCTUATION: dict[Language, tuple[str, ...]] = {
    Language.VIETNAMESE: ("...", "…", ".", "!", "?", ":"),
    # Includes both ASCII and fullwidth (U+FF01 "!", U+FF1F "?") punctuation,
    # since Japanese text mixes both conventions in practice.
    Language.JAPANESE: ("……", "…", "。", "！", "？", "!", "?"),
}

DEFAULT_ENDING_SIGNALS: dict[Language, tuple[str, ...]] = {
    Language.VIETNAMESE: (
        "nhé",
        "nha",
        "ạ",
        "rồi",
        "xong",
        "được không",
        "được rồi",
        "nhỉ",
    ),
    Language.JAPANESE: (
        "です",
        "ます",
        "ました",
        "ください",
        "でした",
        "ますね",
        "ますよ",
        "ますが",
    ),
}


def _strip_trailing_marks(text: str, marks: tuple[str, ...]) -> str:
    """Repeatedly strip any of ``marks`` from the end of ``text``."""
    changed = True
    while changed and text:
        changed = False
        for mark in marks:
            if mark and text.endswith(mark):
                text = text[: -len(mark)]
                changed = True
    return text


@dataclass(frozen=True)
class HeuristicConfig:
    """Thresholds and language-specific signal vocabularies for the heuristic."""

    sentence_end_punctuation: dict[Language, tuple[str, ...]] = field(
        default_factory=lambda: dict(DEFAULT_SENTENCE_END_PUNCTUATION)
    )
    ending_signals: dict[Language, tuple[str, ...]] = field(
        default_factory=lambda: dict(DEFAULT_ENDING_SIGNALS)
    )
    min_stable_speech_ms: int = 300
    max_unstable_tail_chars: int = 12

    def __post_init__(self) -> None:
        if self.min_stable_speech_ms < 0:
            raise ValueError("min_stable_speech_ms must be >= 0")
        if self.max_unstable_tail_chars < 0:
            raise ValueError("max_unstable_tail_chars must be >= 0")

    @classmethod
    def from_settings(cls, settings: object) -> HeuristicConfig:
        """Build a config from an application settings object.

        Reads the ``completeness_heuristic_*`` fields; any missing attribute
        falls back to the documented baseline default. Punctuation/ending
        -signal vocabularies are not environment-configurable (structured
        per-language data); construct a config directly to override them.
        """
        return cls(
            min_stable_speech_ms=int(
                getattr(settings, "completeness_heuristic_min_speech_ms", cls.min_stable_speech_ms)
            ),
            max_unstable_tail_chars=int(
                getattr(
                    settings,
                    "completeness_heuristic_max_unstable_tail_chars",
                    cls.max_unstable_tail_chars,
                )
            ),
        )


@dataclass(frozen=True)
class HeuristicVerdict:
    """The heuristic checker's decision for one soft-silence evaluation."""

    complete: bool
    ambiguous: bool
    reason: str


def evaluate_heuristic(
    *,
    language: Language,
    stable_text: str,
    unstable_text: str,
    speech_ms: int,
    config: HeuristicConfig | None = None,
) -> HeuristicVerdict:
    """Evaluate the deterministic completeness heuristic for one utterance.

    ``stable_text``/``unstable_text`` are the current partial transcription
    (``server.asr.partial.PartialTranscriber.current_text``); ``speech_ms``
    is the utterance's confirmed speech duration so far
    (``server.vad.state_machine.UtteranceSegmenter.speech_ms``).
    """
    cfg = config or HeuristicConfig()
    stripped_stable = stable_text.strip()
    stripped_tail = unstable_text.strip()

    if not stripped_stable:
        return HeuristicVerdict(complete=False, ambiguous=False, reason="empty_stable_text")

    if len(stripped_tail) > cfg.max_unstable_tail_chars:
        return HeuristicVerdict(complete=False, ambiguous=False, reason="unstable_tail_too_long")

    punctuation = cfg.sentence_end_punctuation.get(language, ())
    if stripped_stable.endswith(punctuation) and speech_ms >= cfg.min_stable_speech_ms:
        return HeuristicVerdict(complete=True, ambiguous=False, reason="punctuation")

    ending_signals = cfg.ending_signals.get(language, ())
    normalized = _strip_trailing_marks(stripped_stable, punctuation)
    if normalized.endswith(ending_signals) and speech_ms >= cfg.min_stable_speech_ms:
        return HeuristicVerdict(complete=True, ambiguous=False, reason="ending_signal")

    return HeuristicVerdict(complete=False, ambiguous=True, reason="no_deterministic_signal")
