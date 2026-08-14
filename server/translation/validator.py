"""Translation output validation.

Pure, backend-independent checks for empty output, leaked explanations,
pathological repetition, target-language plausibility, preservation of
numbers/dates/URLs/versions/identifiers, and extreme length ratio, per
docs/TRANSLATION.md "Output validation". A failing result names a machine
-readable ``reason`` so the caller can decide whether a corrective retry is
worthwhile.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from shared.protocol.enums import Language

_FORBIDDEN_PREFIXES = (
    "translation:",
    "translated text:",
    "bản dịch:",
    "dịch:",
    "answer:",
    "output:",
    "翻訳:",
    "訳:",
)

# Any 1-20 char run repeated at least 5 times back-to-back. Character-based
# (not word-tokenized) so it works uniformly for space-delimited Vietnamese
# and non-space-delimited Japanese.
_REPEAT_RE = re.compile(r"(.{1,20}?)\1{4,}", re.DOTALL)

_URL_RE = re.compile(r"https?://\S+")
_VERSION_RE = re.compile(r"\bv?\d+\.\d+(?:\.\d+){0,2}\b", re.IGNORECASE)
_DATE_RE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b|\b\d{1,2}/\d{1,2}/\d{2,4}\b")
_NUMBER_RE = re.compile(r"\b\d+(?:[.,]\d+)*\b")
_IDENTIFIER_RE = re.compile(r"\b[A-Za-z]+[-_][A-Za-z0-9_-]*\d[A-Za-z0-9_-]*\b|\b[A-Z]{2,}\d+\b")

_HIRAGANA = range(0x3040, 0x30A0)
_KATAKANA = range(0x30A0, 0x3100)
_CJK_UNIFIED = range(0x4E00, 0xA000)

_MIN_LENGTH_RATIO = 0.15
_MAX_LENGTH_RATIO = 4.0
_JAPANESE_CJK_RATIO_MIN = 0.3
_VIETNAMESE_CJK_RATIO_MAX = 0.2


@dataclass(frozen=True)
class ValidationResult:
    """Outcome of validating one translation output."""

    ok: bool
    reason: str | None = None


def _extract_identifiers(text: str) -> set[str]:
    found: set[str] = set()
    for pattern in (_URL_RE, _VERSION_RE, _DATE_RE, _NUMBER_RE, _IDENTIFIER_RE):
        found.update(match.group(0) for match in pattern.finditer(text))
    return found


def _has_pathological_repetition(text: str) -> bool:
    return _REPEAT_RE.search(text) is not None


def _is_cjk_char(char: str) -> bool:
    code_point = ord(char)
    return code_point in _HIRAGANA or code_point in _KATAKANA or code_point in _CJK_UNIFIED


def _cjk_ratio(text: str) -> float:
    letters = [char for char in text if char.isalpha()]
    if not letters:
        return 0.0
    cjk = sum(1 for char in letters if _is_cjk_char(char))
    return cjk / len(letters)


def _plausible_target_language(text: str, target_language: Language) -> bool:
    ratio = _cjk_ratio(text)
    if target_language is Language.JAPANESE:
        return ratio >= _JAPANESE_CJK_RATIO_MIN
    if target_language is Language.VIETNAMESE:
        return ratio <= _VIETNAMESE_CJK_RATIO_MAX
    return True


def _identifiers_preserved(source_text: str, translated_text: str) -> bool:
    identifiers = _extract_identifiers(source_text)
    return all(token in translated_text for token in identifiers)


def _length_ratio_ok(source_text: str, translated_text: str) -> bool:
    source_len = len(source_text.strip())
    translated_len = len(translated_text.strip())
    if source_len == 0:
        return translated_len > 0
    ratio = translated_len / source_len
    return _MIN_LENGTH_RATIO <= ratio <= _MAX_LENGTH_RATIO


def validate_translation(
    *, source_text: str, translated_text: str, target_language: Language
) -> ValidationResult:
    """Validate a raw translation output against the source text.

    Checks are ordered from cheapest/most-certain to most-heuristic so the
    ``reason`` reported for a multi-issue output is the most actionable one.
    """
    text = translated_text.strip()
    if not text:
        return ValidationResult(False, "empty_output")

    lowered = text.lower()
    if any(lowered.startswith(prefix) for prefix in _FORBIDDEN_PREFIXES):
        return ValidationResult(False, "forbidden_prefix")

    if _has_pathological_repetition(text):
        return ValidationResult(False, "repetition")

    if not _plausible_target_language(text, target_language):
        return ValidationResult(False, "wrong_language")

    if not _identifiers_preserved(source_text, text):
        return ValidationResult(False, "identifiers_not_preserved")

    if not _length_ratio_ok(source_text, text):
        return ValidationResult(False, "length_ratio")

    return ValidationResult(True, None)
