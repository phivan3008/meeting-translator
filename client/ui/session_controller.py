"""Background network session for the client UI, with no PySide6 import.

Owns an :class:`~client.transport.sender.AudioSender` running on a
dedicated background thread with its own asyncio event loop, decodes
incoming JSON event dicts into typed protocol models, and delivers every
lifecycle signal (connection state, decoded event) through plain callables
supplied by the caller. Kept Qt-independent so it is fully unit-testable
with a fake transport; the only Qt-aware code needed to use it from the UI
is a thin cross-thread bridge (see ``client/ui/main_window.py``) that calls
``Signal.emit()`` from inside these callbacks -- safe because Qt's signal
mechanism marshals a cross-thread emission onto the receiving thread's
event loop automatically (a queued connection).
"""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Callable
from typing import Any

from pydantic import ValidationError

from client.transport.backoff import ReconnectBackoff
from client.transport.sender import AudioSender, ConnectionState, Transport
from client.ui.view_model import InboundEvent
from shared.protocol.enums import EventType
from shared.protocol.messages import (
    ErrorEvent,
    SessionStart,
    TranscriptionPartial,
    TranslationUpdated,
    UtteranceFinal,
)

_EVENT_MODEL_BY_TYPE: dict[str, type[InboundEvent]] = {
    EventType.TRANSCRIPTION_PARTIAL.value: TranscriptionPartial,
    EventType.UTTERANCE_FINAL.value: UtteranceFinal,
    EventType.TRANSLATION_UPDATED.value: TranslationUpdated,
    EventType.ERROR.value: ErrorEvent,
}


def parse_inbound_event(data: dict[str, Any]) -> InboundEvent | None:
    """Parse a raw decoded JSON dict into its typed protocol event.

    Returns ``None`` for an unrecognized ``type`` (e.g. ``audio.ack``,
    which ``AudioSender`` already handles internally) or a payload that
    fails schema validation.
    """
    model = _EVENT_MODEL_BY_TYPE.get(data.get("type", ""))
    if model is None:
        return None
    try:
        return model.model_validate(data)
    except ValidationError:
        return None


class SessionController:
    """Runs an :class:`AudioSender` reconnect loop on a background thread.

    ``send_audio`` and :meth:`stop` are safe to call from any thread (they
    marshal onto the background loop via ``call_soon_threadsafe``);
    ``start``/``stop`` manage the thread's lifecycle.
    """

    def __init__(
        self,
        *,
        session_start: SessionStart,
        transport_factory: Callable[[], Transport],
        backoff: ReconnectBackoff,
        buffer_capacity: int,
        on_state_change: Callable[[ConnectionState], None] | None = None,
        on_event: Callable[[InboundEvent], None] | None = None,
        on_fatal_error: Callable[[BaseException], None] | None = None,
    ) -> None:
        self._on_event = on_event
        self._on_fatal_error = on_fatal_error
        self._sender = AudioSender(
            session_start=session_start,
            transport_factory=transport_factory,
            backoff=backoff,
            buffer_capacity=buffer_capacity,
            on_state_change=on_state_change,
            on_message=self._on_message,
        )
        self._loop: asyncio.AbstractEventLoop | None = None
        self._stop_event: asyncio.Event | None = None
        self._thread: threading.Thread | None = None

    @property
    def sender(self) -> AudioSender:
        return self._sender

    @property
    def is_running(self) -> bool:
        """Whether the background thread is alive.

        Checks ``Thread.is_alive()`` rather than just ``thread is not
        None``: the background loop can exit on its own (an unhandled
        exception from ``AudioSender.run`` -- e.g. a genuinely broken
        transport dependency, found this way by WINDOWS-UI-001), and this
        must be detected so callers stop treating a dead session as live.
        """
        return self._thread is not None and self._thread.is_alive()

    def _on_message(self, data: dict[str, Any]) -> None:
        event = parse_inbound_event(data)
        if event is not None and self._on_event is not None:
            self._on_event(event)

    def start(self) -> None:
        """Start the background thread running the reconnect loop."""
        if self.is_running:
            raise RuntimeError("SessionController already started")
        ready = threading.Event()

        def _run() -> None:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            self._loop = loop
            self._stop_event = asyncio.Event()
            ready.set()
            try:
                loop.run_until_complete(self._sender.run(self._stop_event))
            except BaseException as exc:  # noqa: BLE001 - reported, not swallowed
                if self._on_fatal_error is not None:
                    self._on_fatal_error(exc)
            finally:
                loop.close()

        thread = threading.Thread(target=_run, name="session-controller", daemon=True)
        self._thread = thread
        thread.start()
        if not ready.wait(timeout=5.0):
            raise RuntimeError("SessionController background loop failed to start")

    def stop(self) -> None:
        """Signal the background loop to stop and join the thread.

        Safe to call even if the background thread already died on its own
        (``is_running`` is False): in that case there is no live loop to
        signal, so this just clears local bookkeeping instead of trying to
        schedule a callback on an already-closed event loop (which would
        raise ``RuntimeError: Event loop is closed``).
        """
        if self.is_running and self._loop is not None and self._stop_event is not None:
            self._loop.call_soon_threadsafe(self._stop_event.set)
        if self._thread is not None:
            self._thread.join(timeout=5.0)
        self._thread = None
        self._loop = None
        self._stop_event = None

    def send_audio(self, *, stream_number: int, pcm: bytes, client_timestamp_ms: int) -> None:
        """Enqueue one audio frame for sending (thread-safe)."""
        if not self.is_running or self._loop is None:
            raise RuntimeError("SessionController is not running")
        loop = self._loop
        loop.call_soon_threadsafe(
            lambda: self._sender.send_audio(
                stream_number=stream_number, pcm=pcm, client_timestamp_ms=client_timestamp_ms
            )
        )
