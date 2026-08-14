"""Tests for privacy-preserving logging and redaction."""

from __future__ import annotations

import logging

from shared.logging import (
    REDACTED,
    RedactionFilter,
    configure_logging,
    redact_mapping,
    redact_text,
)


def test_redact_text_masks_bearer_token() -> None:
    out = redact_text("Authorization: Bearer abc.def.ghi")
    assert "abc.def.ghi" not in out
    assert REDACTED in out


def test_redact_text_masks_key_value_secret() -> None:
    out = redact_text("connecting with password=SuperSecret123 to db")
    assert "SuperSecret123" not in out
    assert REDACTED in out


def test_redact_mapping_masks_sensitive_keys() -> None:
    data = {
        "user": "alice",
        "api_key": "sk-12345",
        "nested": {"token": "t-abc", "keep": "value"},
        "transcript": "confidential meeting text",
    }
    out = redact_mapping(data)
    assert out["user"] == "alice"
    assert out["api_key"] == REDACTED
    assert out["transcript"] == REDACTED
    nested = out["nested"]
    assert isinstance(nested, dict)
    assert nested["token"] == REDACTED
    assert nested["keep"] == "value"


def test_redaction_filter_scrubs_message() -> None:
    record = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="login token=%s",
        args=("secret-token-value",),
        exc_info=None,
    )
    RedactionFilter().filter(record)
    rendered = record.getMessage()
    assert "secret-token-value" not in rendered
    assert REDACTED in rendered


def test_configure_logging_is_idempotent() -> None:
    configure_logging("INFO")
    configure_logging("INFO")
    root = logging.getLogger()
    for handler in root.handlers:
        redaction_filters = [f for f in handler.filters if isinstance(f, RedactionFilter)]
        assert len(redaction_filters) <= 1


def test_configure_logging_masks_emitted_record(caplog) -> None:  # type: ignore[no-untyped-def]
    configure_logging("INFO")
    logger = logging.getLogger("privacy.test")
    # Attach the filter to the caplog handler so emitted records are scrubbed.
    handler = caplog.handler
    if not any(isinstance(f, RedactionFilter) for f in handler.filters):
        handler.addFilter(RedactionFilter())
    with caplog.at_level(logging.INFO):
        logger.info("api_key=sk-should-not-appear")
    assert "sk-should-not-appear" not in caplog.text


def test_redact_text_masks_inline_transcript_translation_prompt_audio() -> None:
    # A call site that embeds the value directly in the message (rather than
    # as a separate structured extra) must still be caught -- this is the
    # gap CLAUDE.md's "no raw audio, transcript, prompt or translation
    # logged by default" rule guards against for free-form log messages.
    for field, value in (
        ("transcript", "confidential utterance text"),
        ("translation", "bí mật cuộc họp"),
        ("prompt", "system prompt content"),
        ("audio", "raw-pcm-marker"),
    ):
        out = redact_text(f"{field}={value}")
        assert value not in out, f"{field} value leaked into log text"
        assert REDACTED in out


def test_redact_mapping_masks_audio_and_prompt_keys() -> None:
    data = {"prompt": "do not log this", "audio": b"\x00\x01", "user_id": "u-1"}
    out = redact_mapping(data)
    assert out["prompt"] == REDACTED
    assert out["audio"] == REDACTED
    assert out["user_id"] == "u-1"
