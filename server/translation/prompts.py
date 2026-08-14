"""Prompt builders matching docs/TRANSLATION.md.

Pure string construction, independent of any HTTP client or vLLM backend, so
prompt content and glossary/context selection are fully unit-testable.
"""

from __future__ import annotations

from collections.abc import Sequence

from server.translation.types import MAX_CONTEXT_SENTENCES, GlossaryEntry
from shared.protocol.enums import Language

_JA_TO_VI_PRESERVE_LINE = (
    "2. Preserve names, project names, product names, numbers, dates, "
    "versions, URLs, identifiers and technical terms."
)

JA_TO_VI_SYSTEM_PROMPT = f"""You are a professional Japanese-to-Vietnamese meeting translator.

Requirements:
1. Translate only into natural Vietnamese.
{_JA_TO_VI_PRESERVE_LINE}
3. Preserve the original meaning and level of politeness.
4. Do not summarize.
5. Do not explain.
6. Do not add missing information.
7. Do not output reasoning or labels such as "Translation:".
8. Return only the translated text.

Relevant glossary:
{{glossary}}"""

VI_TO_JA_SYSTEM_PROMPT = f"""You are a professional Vietnamese-to-Japanese meeting translator.

Requirements:
1. Translate only into natural business Japanese.
{_JA_TO_VI_PRESERVE_LINE}
3. Use an appropriate level of business politeness without changing the meaning.
4. Do not summarize.
5. Do not explain.
6. Do not add missing information.
7. Do not output reasoning or labels such as "Translation:".
8. Return only the translated text.

Relevant glossary:
{{glossary}}"""

_CORRECTIVE_SUFFIX = (
    "\n\nYour previous answer violated one or more of the requirements above "
    "(e.g. it was empty, included an explanation/label, repeated itself, or "
    "dropped a preserved term). Follow the requirements exactly this time: "
    "return only the corrected translated text, nothing else."
)

_COMPLETENESS_PROMPT_TEMPLATE = """Determine whether the spoken sentence is semantically complete.
Return JSON only with this exact schema:
{{"complete": true, "confidence": 0.0}}
Do not explain.

Language: {language}
Sentence: {sentence}"""

_NO_GLOSSARY_PLACEHOLDER = "(none)"


def select_relevant_glossary(
    entries: Sequence[GlossaryEntry], text: str
) -> tuple[GlossaryEntry, ...]:
    """Return only the glossary entries whose term appears in ``text``.

    Case-insensitive substring match. Keeps the request focused (and within
    token limits) instead of always sending the full glossary.
    """
    lowered = text.lower()
    return tuple(entry for entry in entries if entry.term.lower() in lowered)


def build_glossary_block(entries: Sequence[GlossaryEntry]) -> str:
    """Render glossary entries as ``term -> translation`` lines."""
    if not entries:
        return _NO_GLOSSARY_PLACEHOLDER
    return "\n".join(f"{entry.term} -> {entry.translation}" for entry in entries)


def build_system_prompt(
    *,
    source_language: Language,
    target_language: Language,
    glossary: Sequence[GlossaryEntry] = (),
    corrective: bool = False,
) -> str:
    """Build the system prompt for one language-pair direction.

    ``corrective`` appends a stricter reminder for the single allowed retry
    after a validation failure (docs/TRANSLATION.md "Retry once with a
    stricter corrective prompt for validation failures that may be
    recoverable").
    """
    if source_language is Language.JAPANESE and target_language is Language.VIETNAMESE:
        template = JA_TO_VI_SYSTEM_PROMPT
    elif source_language is Language.VIETNAMESE and target_language is Language.JAPANESE:
        template = VI_TO_JA_SYSTEM_PROMPT
    else:
        raise ValueError(
            f"unsupported translation direction: {source_language.value} -> {target_language.value}"
        )
    prompt = template.format(glossary=build_glossary_block(glossary))
    if corrective:
        prompt += _CORRECTIVE_SUFFIX
    return prompt


def build_user_content(text: str, *, context_sentences: Sequence[str] = ()) -> str:
    """Build the user message: the text to translate plus optional context.

    Only the current finalized ``text`` is to be translated; at most the last
    :data:`~server.translation.types.MAX_CONTEXT_SENTENCES` prior final
    sentences are included as explicitly non-translatable context.
    """
    context = list(context_sentences)[-MAX_CONTEXT_SENTENCES:]
    if not context:
        return text
    context_block = "\n".join(f"- {sentence}" for sentence in context)
    return (
        f"Context (do not translate, for reference only):\n{context_block}"
        f"\n\nText to translate:\n{text}"
    )


def build_completeness_prompt(*, language: Language, sentence: str) -> str:
    """Build the optional low-priority completeness-classification prompt.

    Matches docs/TRANSLATION.md's "Completeness request" template. Only the
    prompt text is built here; scheduling/consuming this request (deciding
    when to ask, applying the queue-pressure skip and the deterministic
    fallback) is finalization-orchestration work for a later phase.
    """
    return _COMPLETENESS_PROMPT_TEMPLATE.format(language=language.value, sentence=sentence)
