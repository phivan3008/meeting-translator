"""Tests for the session manager and per-stream contexts."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from server.transport.session import SessionError, SessionManager
from shared.protocol.enums import Language, StreamSource
from shared.protocol.messages import SessionStart, StreamConfig


def _session_start(session_id: str = "sess-1") -> SessionStart:
    return SessionStart(
        session_id=session_id,
        client_id="client-1",
        timestamp=datetime.now(UTC),
        streams=[
            StreamConfig(
                stream_number=1,
                stream_id="mic-01",
                source=StreamSource.MICROPHONE,
                source_language=Language.VIETNAMESE,
                target_language=Language.JAPANESE,
            ),
            StreamConfig(
                stream_number=2,
                stream_id="loopback-01",
                source=StreamSource.LOOPBACK,
                source_language=Language.JAPANESE,
                target_language=Language.VIETNAMESE,
            ),
        ],
    )


def _manager(max_streams: int = 8, max_sessions: int = 500) -> SessionManager:
    return SessionManager(
        max_streams_per_session=max_streams,
        jitter_capacity=16,
        ack_every_packets=4,
        ack_every_ms=100,
        max_sessions=max_sessions,
    )


def test_create_session_builds_independent_stream_contexts() -> None:
    manager = _manager()
    session = manager.create_session(_session_start())
    assert session.stream_numbers == (1, 2)
    mic = session.stream_by_number(1)
    loopback = session.stream_by_number(2)
    assert mic is not None and loopback is not None
    assert mic.stream_id == "mic-01"
    assert loopback.stream_id == "loopback-01"
    # Independent buffers: they are distinct objects.
    assert mic.jitter is not loopback.jitter
    assert manager.active_count == 1


def test_duplicate_session_id_rejected() -> None:
    manager = _manager()
    manager.create_session(_session_start("dup"))
    with pytest.raises(SessionError):
        manager.create_session(_session_start("dup"))


def test_too_many_streams_rejected() -> None:
    manager = _manager(max_streams=1)
    with pytest.raises(SessionError):
        manager.create_session(_session_start())


def test_remove_session() -> None:
    manager = _manager()
    manager.create_session(_session_start("s"))
    assert manager.get("s") is not None
    manager.remove("s")
    assert manager.get("s") is None
    assert manager.active_count == 0


def test_max_sessions_enforced() -> None:
    manager = _manager(max_sessions=2)
    manager.create_session(_session_start("s1"))
    manager.create_session(_session_start("s2"))
    with pytest.raises(SessionError):
        manager.create_session(_session_start("s3"))
    assert manager.active_count == 2


def test_max_sessions_frees_up_after_remove() -> None:
    manager = _manager(max_sessions=1)
    manager.create_session(_session_start("s1"))
    with pytest.raises(SessionError):
        manager.create_session(_session_start("s2"))
    manager.remove("s1")
    manager.create_session(_session_start("s2"))  # capacity freed, now succeeds
    assert manager.active_count == 1


def test_invalid_max_sessions_rejected() -> None:
    with pytest.raises(ValueError):
        SessionManager(
            max_streams_per_session=8,
            jitter_capacity=16,
            ack_every_packets=4,
            ack_every_ms=100,
            max_sessions=0,
        )
