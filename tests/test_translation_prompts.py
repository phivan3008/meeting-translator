"""Tests for translation prompt builders (docs/TRANSLATION.md)."""

from __future__ import annotations

import pytest

from server.translation.prompts import (
    build_completeness_prompt,
    build_glossary_block,
    build_system_prompt,
    build_user_content,
    select_relevant_glossary,
)
from server.translation.types import GlossaryEntry
from shared.protocol.enums import Language


def test_ja_to_vi_prompt_matches_documented_requirements() -> None:
    prompt = build_system_prompt(
        source_language=Language.JAPANESE, target_language=Language.VIETNAMESE
    )
    assert "Japanese-to-Vietnamese" in prompt
    assert "natural Vietnamese" in prompt
    assert 'labels such as "Translation:"' in prompt
    assert "Return only the translated text." in prompt
    assert "Relevant glossary:\n(none)" in prompt


def test_vi_to_ja_prompt_matches_documented_requirements() -> None:
    prompt = build_system_prompt(
        source_language=Language.VIETNAMESE, target_language=Language.JAPANESE
    )
    assert "Vietnamese-to-Japanese" in prompt
    assert "natural business Japanese" in prompt
    assert "business politeness" in prompt
    assert "Relevant glossary:\n(none)" in prompt


def test_unsupported_direction_rejected() -> None:
    with pytest.raises(ValueError):
        build_system_prompt(source_language=Language.JAPANESE, target_language=Language.JAPANESE)


def test_glossary_block_lists_relevant_entries() -> None:
    entries = (
        GlossaryEntry(term="vLLM", translation="vLLM"),
        GlossaryEntry(term="要件", translation="yêu cầu"),
    )
    prompt = build_system_prompt(
        source_language=Language.JAPANESE, target_language=Language.VIETNAMESE, glossary=entries
    )
    assert "vLLM -> vLLM" in prompt
    assert "要件 -> yêu cầu" in prompt


def test_glossary_block_empty_placeholder() -> None:
    assert build_glossary_block(()) == "(none)"


def test_select_relevant_glossary_filters_by_source_text() -> None:
    entries = (
        GlossaryEntry(term="vLLM", translation="vLLM"),
        GlossaryEntry(term="Qwen", translation="Qwen"),
        GlossaryEntry(term="unrelated", translation="không liên quan"),
    )
    selected = select_relevant_glossary(entries, "We deployed vLLM today.")
    assert selected == (entries[0],)


def test_select_relevant_glossary_case_insensitive() -> None:
    entries = (GlossaryEntry(term="release", translation="phát hành"),)
    selected = select_relevant_glossary(entries, "The RELEASE is ready.")
    assert selected == entries


def test_corrective_prompt_appends_stricter_reminder() -> None:
    normal = build_system_prompt(
        source_language=Language.JAPANESE, target_language=Language.VIETNAMESE
    )
    corrective = build_system_prompt(
        source_language=Language.JAPANESE, target_language=Language.VIETNAMESE, corrective=True
    )
    assert corrective.startswith(normal)
    assert len(corrective) > len(normal)
    assert "previous answer violated" in corrective


def test_user_content_without_context_is_plain_text() -> None:
    assert build_user_content("Xin chào") == "Xin chào"


def test_user_content_includes_at_most_two_prior_sentences() -> None:
    content = build_user_content(
        "Current sentence.", context_sentences=("First.", "Second.", "Third.")
    )
    assert "Second." in content
    assert "Third." in content
    assert "First." not in content
    assert "Current sentence." in content
    assert content.index("Text to translate:") > content.index("Context")


def test_completeness_prompt_matches_documented_schema() -> None:
    prompt = build_completeness_prompt(language=Language.JAPANESE, sentence="来週について")
    assert '{"complete": true, "confidence": 0.0}' in prompt
    assert "Language: ja" in prompt
    assert "Sentence: 来週について" in prompt
