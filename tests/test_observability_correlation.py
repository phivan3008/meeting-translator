"""Tests for structured correlation IDs."""

from __future__ import annotations

import logging

from server.observability.correlation import CorrelationFilter, bind, current, new_request_id


def test_current_is_empty_by_default() -> None:
    assert current() == {}


def test_bind_sets_and_restores() -> None:
    assert current() == {}
    with bind(session_id="sess-1"):
        assert current() == {"session_id": "sess-1"}
    assert current() == {}


def test_bind_layers_and_unwinds_in_order() -> None:
    with bind(session_id="sess-1", stream_id="mic-01"):
        assert current() == {"session_id": "sess-1", "stream_id": "mic-01"}
        with bind(utterance_id="utt-1", request_id="req-1"):
            assert current() == {
                "session_id": "sess-1",
                "stream_id": "mic-01",
                "utterance_id": "utt-1",
                "request_id": "req-1",
            }
        # Inner block's IDs are gone; outer ones remain.
        assert current() == {"session_id": "sess-1", "stream_id": "mic-01"}
    assert current() == {}


def test_bind_restores_even_on_exception() -> None:
    with bind(session_id="sess-1"):
        try:
            with bind(request_id="req-1"):
                raise ValueError("boom")
        except ValueError:
            pass
        assert current() == {"session_id": "sess-1"}
    assert current() == {}


def test_bind_unspecified_ids_left_unchanged() -> None:
    with bind(session_id="sess-1"):
        with bind(session_id=None, stream_id="mic-01"):
            # session_id not re-specified -> stays bound from the outer block.
            assert current() == {"session_id": "sess-1", "stream_id": "mic-01"}


def test_new_request_id_is_short_and_unique() -> None:
    a = new_request_id()
    b = new_request_id()
    assert a != b
    assert 1 <= len(a) <= 32
    assert 1 <= len(b) <= 32


def _make_record() -> logging.LogRecord:
    return logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="hi",
        args=(),
        exc_info=None,
    )


def test_correlation_filter_injects_bound_ids() -> None:
    with bind(session_id="sess-1", utterance_id="utt-7"):
        record = _make_record()
        result = CorrelationFilter().filter(record)
        assert result is True
        assert record.session_id == "sess-1"  # type: ignore[attr-defined]
        assert record.utterance_id == "utt-7"  # type: ignore[attr-defined]
        assert not hasattr(record, "stream_id")
        assert not hasattr(record, "request_id")


def test_correlation_filter_adds_nothing_when_unbound() -> None:
    record = _make_record()
    CorrelationFilter().filter(record)
    for attr in ("session_id", "stream_id", "utterance_id", "request_id"):
        assert not hasattr(record, attr)
