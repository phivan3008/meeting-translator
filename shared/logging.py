"""Privacy-preserving logging utilities.

Production logs must not contain raw audio, full transcripts, prompts or
translations by default. This module provides:

- A redaction filter that masks values of sensitive keys and common secret
  patterns in log records.
- A helper to configure structured, privacy-preserving logging.

Redaction is applied defensively so that accidental inclusion of sensitive
content in a log message is masked rather than emitted.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterable

# Substrings (case-insensitive) that mark a key/field as sensitive.
SENSITIVE_KEY_HINTS: tuple[str, ...] = (
    "password",
    "passwd",
    "secret",
    "token",
    "api_key",
    "apikey",
    "authorization",
    "auth",
    "private_key",
    "jwt",
    "transcript",
    "translation",
    "prompt",
    "audio",
)

REDACTED = "***REDACTED***"

# Patterns for secret-like or privacy-sensitive values embedded in free-form
# message text, e.g. a call site that writes ``f"transcript={text}"`` into
# the message directly instead of passing it as a structured (key-redacted)
# extra. Kept in sync with SENSITIVE_KEY_HINTS so a key considered sensitive
# for structured extras is also caught inline in message text.
_BEARER_RE = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._\-]+")
_KV_SECRET_RE = re.compile(
    r"(?i)\b(" + "|".join(SENSITIVE_KEY_HINTS) + r")\b\s*[=:]\s*(\"[^\"]*\"|'[^']*'|[^\s,;]+)"
)


def _is_sensitive_key(key: str, hints: Iterable[str]) -> bool:
    lowered = key.lower()
    return any(hint in lowered for hint in hints)


def redact_text(text: str) -> str:
    """Mask secret-like tokens and key/value secrets in free-form text."""
    redacted = _BEARER_RE.sub("Bearer " + REDACTED, text)
    redacted = _KV_SECRET_RE.sub(lambda m: f"{m.group(1)}={REDACTED}", redacted)
    return redacted


def redact_mapping(
    data: dict[str, object],
    hints: Iterable[str] = SENSITIVE_KEY_HINTS,
) -> dict[str, object]:
    """Return a copy of ``data`` with sensitive values masked.

    Nested dictionaries are redacted recursively. Non-sensitive scalar values
    are preserved. String values are additionally scrubbed for embedded
    secrets.
    """
    hint_tuple = tuple(hints)
    result: dict[str, object] = {}
    for key, value in data.items():
        if _is_sensitive_key(key, hint_tuple):
            result[key] = REDACTED
            continue
        if isinstance(value, dict):
            result[key] = redact_mapping(value, hint_tuple)
        elif isinstance(value, str):
            result[key] = redact_text(value)
        else:
            result[key] = value
    return result


class RedactionFilter(logging.Filter):
    """Logging filter that redacts secret-like content from records."""

    def __init__(self, hints: Iterable[str] = SENSITIVE_KEY_HINTS) -> None:
        super().__init__()
        self._hints = tuple(hints)

    def filter(self, record: logging.LogRecord) -> bool:
        # Redact the rendered message. getMessage() applies args to msg.
        try:
            message = record.getMessage()
        except Exception:  # noqa: BLE001 - never let logging crash the app
            return True
        record.msg = redact_text(message)
        record.args = ()

        # Redact any structured extras attached to the record.
        for attr, value in list(record.__dict__.items()):
            if attr in _RESERVED_RECORD_ATTRS:
                continue
            if _is_sensitive_key(attr, self._hints):
                setattr(record, attr, REDACTED)
            elif isinstance(value, dict):
                setattr(record, attr, redact_mapping(value, self._hints))
            elif isinstance(value, str):
                setattr(record, attr, redact_text(value))
        return True


# Standard LogRecord attributes that must not be treated as structured extras.
_RESERVED_RECORD_ATTRS: frozenset[str] = frozenset(
    {
        "name",
        "msg",
        "args",
        "levelname",
        "levelno",
        "pathname",
        "filename",
        "module",
        "exc_info",
        "exc_text",
        "stack_info",
        "lineno",
        "funcName",
        "created",
        "msecs",
        "relativeCreated",
        "thread",
        "threadName",
        "processName",
        "process",
        "taskName",
    }
)


def configure_logging(level: str = "INFO") -> None:
    """Configure root logging with the redaction filter attached.

    This is idempotent for the redaction filter: repeated calls do not attach
    duplicate filters to the same handler.
    """
    root = logging.getLogger()
    root.setLevel(level)

    if not root.handlers:
        stream_handler = logging.StreamHandler()
        stream_handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
        )
        root.addHandler(stream_handler)

    redaction = RedactionFilter()
    for handler in root.handlers:
        if not any(isinstance(f, RedactionFilter) for f in handler.filters):
            handler.addFilter(redaction)
