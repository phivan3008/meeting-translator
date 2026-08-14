"""Structured correlation IDs across session, stream, utterance and model request.

Uses ``contextvars`` so an ID bound at one point (e.g. the gateway's
per-connection handler binding ``session_id``) is automatically visible to
every log call made while handling that connection, without threading IDs
through every function signature. :class:`CorrelationFilter` injects
whichever IDs are currently bound into each ``LogRecord`` as structured
attributes, so they appear on every log line without each call site
remembering to pass them explicitly.

Never carries content (transcript/translation/prompt text) -- only opaque
identifiers -- so it composes safely with
``shared.logging.RedactionFilter`` without needing special-casing.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

_session_id: ContextVar[str | None] = ContextVar("session_id", default=None)
_stream_id: ContextVar[str | None] = ContextVar("stream_id", default=None)
_utterance_id: ContextVar[str | None] = ContextVar("utterance_id", default=None)
_request_id: ContextVar[str | None] = ContextVar("request_id", default=None)

_VARS: dict[str, ContextVar[str | None]] = {
    "session_id": _session_id,
    "stream_id": _stream_id,
    "utterance_id": _utterance_id,
    "request_id": _request_id,
}


def new_request_id() -> str:
    """Generate a new short, unique ID for one backend model request."""
    return uuid.uuid4().hex[:16]


@contextmanager
def bind(
    *,
    session_id: str | None = None,
    stream_id: str | None = None,
    utterance_id: str | None = None,
    request_id: str | None = None,
) -> Iterator[None]:
    """Bind the given correlation IDs for the duration of the ``with`` block.

    Unspecified IDs are left unchanged, so nested calls layer naturally --
    e.g. an outer ``bind(session_id=..., stream_id=...)`` around connection
    handling plus an inner ``bind(request_id=...)`` around one model call.
    IDs are restored to their prior value on exit, not cleared outright, so
    nesting/un-nesting is exception-safe.
    """
    values = {
        "session_id": session_id,
        "stream_id": stream_id,
        "utterance_id": utterance_id,
        "request_id": request_id,
    }
    tokens = [
        (_VARS[key], _VARS[key].set(value)) for key, value in values.items() if value is not None
    ]
    try:
        yield
    finally:
        for var, token in reversed(tokens):
            var.reset(token)


def current() -> dict[str, str]:
    """Snapshot of the currently-bound correlation IDs (only the set ones)."""
    return {name: value for name, var in _VARS.items() if (value := var.get()) is not None}


class CorrelationFilter(logging.Filter):
    """Injects currently-bound correlation IDs into every log record."""

    def filter(self, record: logging.LogRecord) -> bool:
        for key, value in current().items():
            setattr(record, key, value)
        return True
