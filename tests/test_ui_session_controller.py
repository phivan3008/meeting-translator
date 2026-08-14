"""Tests for the background (Qt-free) network session controller."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime

import pytest

from client.transport.backoff import ReconnectBackoff
from client.transport.sender import ConnectionState, TransportClosed
from client.ui.session_controller import SessionController, parse_inbound_event
from shared.protocol.enums import FinalReason, Language, StreamSource, TranslationStatus
from shared.protocol.messages import SessionStart, StreamConfig, UtteranceFinal


def _session_start() -> SessionStart:
    return SessionStart(
        session_id="sess-1",
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
        ],
    )


def _final_event_json() -> str:
    event = UtteranceFinal(
        session_id="sess-1",
        stream_id="mic-01",
        utterance_id="utt-1",
        revision=1,
        source=StreamSource.MICROPHONE,
        source_language=Language.VIETNAMESE,
        target_language=Language.JAPANESE,
        transcription="Xin chào.",
        translation="こんにちは。",
        translation_status=TranslationStatus.COMPLETED,
        start_ms=0,
        end_ms=500,
        final_reason=FinalReason.VAD_HARD_SILENCE,
        timestamp=datetime.now(UTC),
    )
    return event.model_dump_json()


class FakeTransport:
    """Delivers one queued message per instance, then fails fast.

    Mirrors ``tests/test_transport_sender.py``'s ``FakeTransport``: ``recv``
    never blocks, so the reconnect loop cycles quickly and predictably
    instead of hanging on a stuck receive.
    """

    _lock = threading.Lock()

    def __init__(self, *, message: str | None = None) -> None:
        self._message = message
        self.connected = False
        self.closed = False

    async def connect(self) -> None:
        self.connected = True

    async def send_text(self, data: str, /) -> None:
        pass

    async def send_bytes(self, data: bytes, /) -> None:
        pass

    async def recv(self) -> str | bytes:
        with self._lock:
            message, self._message = self._message, None
        if message is not None:
            return message
        raise TransportClosed("closed")

    async def close(self) -> None:
        self.closed = True


def _wait_until(predicate: Callable[[], bool], *, timeout_s: float = 2.0) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return predicate()


# --- parse_inbound_event -----------------------------------------------------


def test_parse_inbound_event_valid_final() -> None:
    import json

    data = json.loads(_final_event_json())
    event = parse_inbound_event(data)
    assert isinstance(event, UtteranceFinal)
    assert event.utterance_id == "utt-1"


def test_parse_inbound_event_unknown_type_returns_none() -> None:
    assert parse_inbound_event({"type": "audio.ack"}) is None
    assert parse_inbound_event({"type": "session.start"}) is None
    assert parse_inbound_event({}) is None


def test_parse_inbound_event_invalid_payload_returns_none() -> None:
    assert parse_inbound_event({"type": "utterance.final"}) is None  # missing required fields


# --- SessionController lifecycle ---------------------------------------------


def test_send_audio_before_start_raises() -> None:
    controller = SessionController(
        session_start=_session_start(),
        transport_factory=FakeTransport,
        backoff=ReconnectBackoff(initial_ms=1, max_ms=5),
        buffer_capacity=8,
    )
    with pytest.raises(RuntimeError):
        controller.send_audio(stream_number=1, pcm=b"\x00\x00", client_timestamp_ms=1)


def test_start_stop_lifecycle() -> None:
    controller = SessionController(
        session_start=_session_start(),
        transport_factory=FakeTransport,
        backoff=ReconnectBackoff(initial_ms=1, max_ms=5),
        buffer_capacity=8,
    )
    assert controller.is_running is False
    controller.start()
    assert controller.is_running is True
    with pytest.raises(RuntimeError):
        controller.start()
    controller.stop()
    assert controller.is_running is False


def test_start_stop_reports_connection_states() -> None:
    states: list[ConnectionState] = []
    controller = SessionController(
        session_start=_session_start(),
        transport_factory=FakeTransport,
        backoff=ReconnectBackoff(initial_ms=1, max_ms=5),
        buffer_capacity=8,
        on_state_change=states.append,
    )
    controller.start()
    assert _wait_until(lambda: ConnectionState.CONNECTED in states)
    controller.stop()
    assert states[0] is ConnectionState.CONNECTING
    assert ConnectionState.CONNECTED in states
    assert states[-1] is ConnectionState.DISCONNECTED


def test_received_final_event_is_parsed_and_delivered() -> None:
    events: list[object] = []
    controller = SessionController(
        session_start=_session_start(),
        transport_factory=lambda: FakeTransport(message=_final_event_json()),
        backoff=ReconnectBackoff(initial_ms=1, max_ms=5),
        buffer_capacity=8,
        on_event=events.append,
    )
    controller.start()
    try:
        assert _wait_until(lambda: len(events) >= 1)
    finally:
        controller.stop()

    assert isinstance(events[0], UtteranceFinal)
    assert events[0].utterance_id == "utt-1"


def test_send_audio_after_stop_raises() -> None:
    controller = SessionController(
        session_start=_session_start(),
        transport_factory=FakeTransport,
        backoff=ReconnectBackoff(initial_ms=1, max_ms=5),
        buffer_capacity=8,
    )
    controller.start()
    controller.stop()
    with pytest.raises(RuntimeError):
        controller.send_audio(stream_number=1, pcm=b"\x00\x00", client_timestamp_ms=1)


# --- Background thread crashes (regression: WINDOWS-UI-001 found a real -----
# --- websockets import bug that crashed the thread; the controller must ----
# --- degrade cleanly instead of leaving stale state that raises forever. ---


class CrashingTransport:
    """Simulates a transport whose ``connect`` raises immediately.

    Mirrors what a genuinely broken dependency (e.g. the
    ``websockets.asyncio`` import bug WINDOWS-UI-001 found) looks like from
    ``AudioSender.run``'s perspective: an exception that is neither
    ``TransportClosed`` nor ``(OSError, ConnectionError)``, so it is not
    caught there and propagates out of the background thread's run loop.
    """

    async def connect(self) -> None:
        raise ModuleNotFoundError("No module named 'websockets.asyncio'")

    async def send_text(self, data: str, /) -> None:
        pass

    async def send_bytes(self, data: bytes, /) -> None:
        pass

    async def recv(self) -> str | bytes:
        raise TransportClosed("closed")

    async def close(self) -> None:
        pass


def test_crashed_background_thread_reports_fatal_error() -> None:
    errors: list[BaseException] = []
    controller = SessionController(
        session_start=_session_start(),
        transport_factory=CrashingTransport,
        backoff=ReconnectBackoff(initial_ms=1, max_ms=5),
        buffer_capacity=8,
        on_fatal_error=errors.append,
    )
    controller.start()
    try:
        assert _wait_until(lambda: len(errors) >= 1)
    finally:
        controller.stop()

    assert isinstance(errors[0], ModuleNotFoundError)


def test_is_running_becomes_false_after_thread_crashes() -> None:
    controller = SessionController(
        session_start=_session_start(),
        transport_factory=CrashingTransport,
        backoff=ReconnectBackoff(initial_ms=1, max_ms=5),
        buffer_capacity=8,
    )
    controller.start()
    try:
        assert _wait_until(lambda: controller.is_running is False)
    finally:
        controller.stop()


def test_stop_after_crash_does_not_raise() -> None:
    controller = SessionController(
        session_start=_session_start(),
        transport_factory=CrashingTransport,
        backoff=ReconnectBackoff(initial_ms=1, max_ms=5),
        buffer_capacity=8,
    )
    controller.start()
    assert _wait_until(lambda: controller.is_running is False)

    controller.stop()  # must not raise "Event loop is closed"

    assert controller.is_running is False


def test_send_audio_after_crash_raises_clean_runtime_error() -> None:
    controller = SessionController(
        session_start=_session_start(),
        transport_factory=CrashingTransport,
        backoff=ReconnectBackoff(initial_ms=1, max_ms=5),
        buffer_capacity=8,
    )
    controller.start()
    assert _wait_until(lambda: controller.is_running is False)

    with pytest.raises(RuntimeError):
        controller.send_audio(stream_number=1, pcm=b"\x00\x00", client_timestamp_ms=1)
    controller.stop()
