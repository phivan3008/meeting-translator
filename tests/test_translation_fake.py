"""Tests for the scripted translation test double."""

from __future__ import annotations

import pytest

from server.translation.errors import TranslationFailedError
from server.translation.fake import ScriptedTranslationClient


async def test_returns_scripted_results_in_order() -> None:
    client = ScriptedTranslationClient(["one", "two"])
    assert await client.complete_chat(system_prompt="s", user_content="u", max_tokens=10) == "one"
    assert await client.complete_chat(system_prompt="s", user_content="u", max_tokens=10) == "two"
    # Exhausted -> repeats the last outcome.
    assert await client.complete_chat(system_prompt="s", user_content="u", max_tokens=10) == "two"


async def test_records_calls() -> None:
    client = ScriptedTranslationClient(["hi"])
    await client.complete_chat(system_prompt="sys", user_content="hello", max_tokens=42)
    assert client.call_count == 1
    assert client.calls[0].system_prompt == "sys"
    assert client.calls[0].user_content == "hello"
    assert client.calls[0].max_tokens == 42


async def test_raises_scripted_error() -> None:
    client = ScriptedTranslationClient([TranslationFailedError("boom")])
    with pytest.raises(TranslationFailedError):
        await client.complete_chat(system_prompt="s", user_content="u", max_tokens=10)


def test_rejects_empty_outcomes() -> None:
    with pytest.raises(ValueError):
        ScriptedTranslationClient([])
