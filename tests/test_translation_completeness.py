"""Tests for the optional low-priority completeness classifier."""

from __future__ import annotations

import asyncio

import pytest

from server.translation.completeness import CompletenessClassifier
from server.translation.errors import TranslationOverloadedError, TranslationTimeoutError
from server.translation.fake import ScriptedTranslationClient
from shared.protocol.enums import Language


async def test_classify_valid_json() -> None:
    client = ScriptedTranslationClient(['{"complete": true, "confidence": 0.9}'])
    classifier = CompletenessClassifier(client, timeout_ms=250, max_tokens=20)

    outcome = await classifier.classify(language=Language.JAPANESE, sentence="来週のリリースです。")

    assert outcome.complete is True
    assert outcome.confidence == pytest.approx(0.9)
    assert outcome.issue is None
    assert client.call_count == 1
    call = client.calls[0]
    assert call.max_tokens == 20
    assert "来週のリリースです。" in call.user_content


async def test_classify_valid_json_incomplete() -> None:
    client = ScriptedTranslationClient(['{"complete": false, "confidence": 0.7}'])
    classifier = CompletenessClassifier(client, timeout_ms=250, max_tokens=20)

    outcome = await classifier.classify(language=Language.VIETNAMESE, sentence="Tôi muốn")

    assert outcome.complete is False
    assert outcome.confidence == pytest.approx(0.7)


async def test_classify_extracts_json_wrapped_in_extra_text() -> None:
    client = ScriptedTranslationClient(
        ['Sure, here it is:\n```json\n{"complete": true, "confidence": 0.6}\n```']
    )
    classifier = CompletenessClassifier(client, timeout_ms=250, max_tokens=20)

    outcome = await classifier.classify(language=Language.JAPANESE, sentence="sentence")

    assert outcome.complete is True
    assert outcome.confidence == pytest.approx(0.6)
    assert outcome.issue is None


async def test_classify_invalid_json_is_unknown() -> None:
    client = ScriptedTranslationClient(["not json at all"])
    classifier = CompletenessClassifier(client, timeout_ms=250, max_tokens=20)

    outcome = await classifier.classify(language=Language.JAPANESE, sentence="sentence")

    assert outcome.complete is None
    assert outcome.confidence is None
    assert outcome.issue == "invalid_json"


async def test_classify_missing_keys_is_unknown() -> None:
    client = ScriptedTranslationClient(['{"confidence": 0.9}'])
    classifier = CompletenessClassifier(client, timeout_ms=250, max_tokens=20)

    outcome = await classifier.classify(language=Language.JAPANESE, sentence="sentence")

    assert outcome.complete is None
    assert outcome.issue == "invalid_json"


async def test_classify_wrong_types_is_unknown() -> None:
    client = ScriptedTranslationClient(['{"complete": "yes", "confidence": 0.9}'])
    classifier = CompletenessClassifier(client, timeout_ms=250, max_tokens=20)

    outcome = await classifier.classify(language=Language.JAPANESE, sentence="sentence")

    assert outcome.complete is None
    assert outcome.issue == "invalid_json"


async def test_classify_confidence_bool_rejected() -> None:
    # bool is a subclass of int in Python; must not be accepted as confidence.
    client = ScriptedTranslationClient(['{"complete": true, "confidence": true}'])
    classifier = CompletenessClassifier(client, timeout_ms=250, max_tokens=20)

    outcome = await classifier.classify(language=Language.JAPANESE, sentence="sentence")

    assert outcome.complete is None
    assert outcome.issue == "invalid_json"


async def test_classify_backend_error_is_unknown() -> None:
    client = ScriptedTranslationClient([TranslationOverloadedError("busy")])
    classifier = CompletenessClassifier(client, timeout_ms=250, max_tokens=20)

    outcome = await classifier.classify(language=Language.JAPANESE, sentence="sentence")

    assert outcome.complete is None
    assert outcome.issue == "overloaded"


async def test_classify_scripted_timeout_error_is_unknown() -> None:
    client = ScriptedTranslationClient([TranslationTimeoutError("slow")])
    classifier = CompletenessClassifier(client, timeout_ms=250, max_tokens=20)

    outcome = await classifier.classify(language=Language.JAPANESE, sentence="sentence")

    assert outcome.complete is None
    assert outcome.issue == "timeout"


async def test_classify_enforces_strict_timeout() -> None:
    class SlowClient:
        async def complete_chat(
            self, *, system_prompt: str, user_content: str, max_tokens: int
        ) -> str:
            await asyncio.sleep(0.5)
            return '{"complete": true, "confidence": 0.9}'

    classifier = CompletenessClassifier(SlowClient(), timeout_ms=10, max_tokens=20)

    outcome = await classifier.classify(language=Language.JAPANESE, sentence="sentence")

    assert outcome.complete is None
    assert outcome.issue == "timeout"


def test_invalid_config_rejected() -> None:
    client = ScriptedTranslationClient(["{}"])
    with pytest.raises(ValueError):
        CompletenessClassifier(client, timeout_ms=0, max_tokens=20)
    with pytest.raises(ValueError):
        CompletenessClassifier(client, timeout_ms=250, max_tokens=0)
