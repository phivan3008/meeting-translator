"""Client audio sender with reconnect, bounded buffering and idempotent resend.

The sender is decoupled from any concrete socket through the :class:`Transport`
protocol, so its reconnect and resend behavior is unit-testable with a fake
transport. A concrete :class:`WebSocketClientTransport` backed by the
``websockets`` library is provided for production use (imported lazily).

Privacy: only sizes/sequence numbers are handled here; no audio payload or text
content is logged.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Callable
from enum import Enum
from typing import Any, Protocol, runtime_checkable

from client.transport.backoff import ReconnectBackoff
from client.transport.outbound import OutboundBuffer
from shared.protocol.binary import AudioFlags, encode_packet
from shared.protocol.enums import EventType
from shared.protocol.messages import AudioAck, ErrorEvent, SessionStart

_LOG = logging.getLogger("client.transport.sender")


class TransportClosed(Exception):
    """Raised by a transport when the underlying connection is closed."""


class ConnectionState(Enum):
    """Connection lifecycle state, reported via ``AudioSender``'s state callback.

    ``CONNECTING`` is the very first connection attempt; a later reconnect
    attempt after a successful connection was lost is reported as
    ``RECONNECTING`` instead, so a UI can distinguish first-connect from
    recovering a dropped link.
    """

    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    RECONNECTING = "reconnecting"


@runtime_checkable
class Transport(Protocol):
    """Bidirectional message transport abstraction."""

    async def connect(self) -> None: ...

    async def send_text(self, data: str, /) -> None: ...

    async def send_bytes(self, data: bytes, /) -> None: ...

    async def recv(self) -> str | bytes: ...

    async def close(self) -> None: ...


class AudioSender:
    """Sends session handshake and binary audio frames with reconnect/resend."""

    def __init__(
        self,
        *,
        session_start: SessionStart,
        transport_factory: Callable[[], Transport],
        backoff: ReconnectBackoff,
        buffer_capacity: int,
        on_error: Callable[[ErrorEvent], None] | None = None,
        on_state_change: Callable[[ConnectionState], None] | None = None,
        on_message: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        self._session_start = session_start
        self._factory = transport_factory
        self._backoff = backoff
        self._on_error = on_error
        self._on_state_change = on_state_change
        self._on_message = on_message
        self._buffers: dict[int, OutboundBuffer] = {
            s.stream_number: OutboundBuffer(capacity=buffer_capacity) for s in session_start.streams
        }
        self._next_seq: dict[int, int] = {s.stream_number: 0 for s in session_start.streams}
        self._stream_number_by_id: dict[str, int] = {
            s.stream_id: s.stream_number for s in session_start.streams
        }
        self._outgoing: asyncio.Queue[bytes] = asyncio.Queue()

    # --- Introspection -------------------------------------------------------
    def buffer_for(self, stream_number: int) -> OutboundBuffer:
        return self._buffers[stream_number]

    # --- Producer API --------------------------------------------------------
    def send_audio(
        self,
        *,
        stream_number: int,
        pcm: bytes,
        client_timestamp_ms: int,
        flags: int = AudioFlags.NONE,
    ) -> int:
        """Assign a sequence, encode, buffer and queue a frame. Returns the seq."""
        if stream_number not in self._buffers:
            raise KeyError(f"unknown stream_number {stream_number}")
        sequence_number = self._next_seq[stream_number]
        self._next_seq[stream_number] += 1
        packet = encode_packet(
            stream_number=stream_number,
            sequence_number=sequence_number,
            client_timestamp_ms=client_timestamp_ms,
            payload=pcm,
            flags=flags,
        )
        self._buffers[stream_number].add(sequence_number, packet)
        self._outgoing.put_nowait(packet)
        return sequence_number

    # --- Connection lifecycle ------------------------------------------------
    async def _open(self, transport: Transport) -> None:
        """Connect, perform the handshake, reset backoff and resend unacked."""
        await transport.connect()
        await transport.send_text(self._session_start.model_dump_json())
        self._backoff.reset()
        await self._resend_pending(transport)

    async def _resend_pending(self, transport: Transport) -> None:
        for stream_number in sorted(self._buffers):
            for frame in self._buffers[stream_number].pending():
                await transport.send_bytes(frame.packet)

    def _handle_message(self, message: str | bytes) -> None:
        if isinstance(message, (bytes, bytearray)):
            return
        try:
            data = json.loads(message)
        except (ValueError, TypeError):
            return
        if not isinstance(data, dict):
            return
        message_type = data.get("type")
        if message_type == EventType.AUDIO_ACK.value:
            ack = AudioAck.model_validate(data)
            stream_number = self._stream_number_by_id.get(ack.stream_id)
            if stream_number is not None:
                self._buffers[stream_number].ack(ack.last_contiguous_sequence)
        elif message_type == EventType.ERROR.value:
            error = ErrorEvent.model_validate(data)
            if self._on_error is not None:
                self._on_error(error)
        if self._on_message is not None:
            self._on_message(data)

    async def _pump_outgoing(self, transport: Transport, stop: asyncio.Event) -> None:
        while not stop.is_set():
            try:
                packet = await asyncio.wait_for(self._outgoing.get(), timeout=0.05)
            except TimeoutError:
                continue
            await transport.send_bytes(packet)

    async def _pump_incoming(self, transport: Transport, stop: asyncio.Event) -> None:
        # Polls with a short timeout (matching _pump_outgoing's style)
        # rather than a bare `await transport.recv()`: an unbounded recv()
        # blocks until the peer sends something or closes the connection,
        # so it never notices `stop` on its own -- observed in practice as
        # a Disconnect that appeared to hang/freeze while a real
        # WebSocket's recv() sat blocked with nothing incoming, only
        # actually unblocking (and only then discovering `stop` was set)
        # once the *server's own* idle timeout eventually force-closed the
        # connection, well after `SessionController.stop()`'s join had
        # already given up and left the thread orphaned in the meantime
        # (WINDOWS-UI-006's manual report).
        while not stop.is_set():
            try:
                message = await asyncio.wait_for(transport.recv(), timeout=0.05)
            except TimeoutError:
                continue
            self._handle_message(message)

    async def run(self, stop: asyncio.Event) -> None:
        """Reconnect loop: connect, stream and resend until ``stop`` is set."""
        first_attempt = True
        while not stop.is_set():
            self._set_state(
                ConnectionState.CONNECTING if first_attempt else ConnectionState.RECONNECTING
            )
            first_attempt = False
            transport = self._factory()
            try:
                await self._open(transport)
                self._set_state(ConnectionState.CONNECTED)
                await self._serve(transport, stop)
            except TransportClosed:
                _LOG.info("transport closed; will reconnect")
            except (OSError, ConnectionError):
                _LOG.info("connection error; will reconnect")
            finally:
                await transport.close()
                self._set_state(ConnectionState.DISCONNECTED)

            if stop.is_set():
                break
            delay_s = self._backoff.next_delay_ms() / 1000.0
            try:
                await asyncio.wait_for(stop.wait(), timeout=delay_s)
            except TimeoutError:
                pass

    def _set_state(self, state: ConnectionState) -> None:
        if self._on_state_change is not None:
            self._on_state_change(state)

    async def _serve(self, transport: Transport, stop: asyncio.Event) -> None:
        outgoing = asyncio.create_task(self._pump_outgoing(transport, stop))
        incoming = asyncio.create_task(self._pump_incoming(transport, stop))
        tasks = {outgoing, incoming}
        try:
            done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_EXCEPTION)
            for task in done:
                exc = task.exception()
                if exc is not None and not isinstance(exc, TransportClosed):
                    raise exc
                if isinstance(exc, TransportClosed):
                    raise exc
        finally:
            await self._cancel_and_wait(tasks)

    @staticmethod
    async def _cancel_and_wait(tasks: set[asyncio.Task[None]]) -> None:
        """Cancel and await ``tasks``, retrying cancellation until all finish.

        A single ``Task.cancel()`` call can race with a task's currently
        awaited future resolving just beforehand and be silently swallowed
        (the task resumes normally instead of raising ``CancelledError``,
        a documented asyncio subtlety) -- observed to leave a pump task
        running forever on some platforms. Cancelling repeatedly until every
        task is actually done makes shutdown reliable.
        """
        for task in tasks:
            if not task.done():
                task.cancel()
        while True:
            _, pending = await asyncio.wait(tasks, timeout=0.1)
            if not pending:
                break
            for task in pending:
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


class WebSocketClientTransport:
    """Production :class:`Transport` backed by the ``websockets`` library."""

    def __init__(self, url: str) -> None:
        self._url = url
        self._connection: Any = None

    async def connect(self) -> None:
        connection = await _websockets_connect(self._url)
        self._connection = connection

    async def send_text(self, data: str, /) -> None:
        await self._active().send(data)

    async def send_bytes(self, data: bytes, /) -> None:
        await self._active().send(data)

    async def recv(self) -> str | bytes:
        try:
            message = await self._active().recv()
        except Exception as exc:  # noqa: BLE001 - normalized to TransportClosed
            raise TransportClosed(str(exc)) from exc
        if isinstance(message, str):
            return message
        return bytes(message)

    async def close(self) -> None:
        if self._connection is not None:
            await self._active().close()
            self._connection = None

    def _active(self) -> Any:
        if self._connection is None:
            raise TransportClosed("transport is not connected")
        return self._connection


async def _websockets_connect(url: str) -> Any:
    """Lazily import ``websockets`` and open a connection.

    Uses the top-level ``websockets.connect`` entry point rather than
    ``websockets.asyncio.client`` -- the latter is only present starting in
    websockets 13.0 (its rewritten implementation) and does not exist in
    the ``websockets>=12,<13`` range this project pins
    (``pyproject.toml``), which was the root cause of a real
    ``ModuleNotFoundError`` found by WINDOWS-UI-001's manual connect test.
    The top-level ``connect`` function has been the stable public entry
    point since long before 12.x and remains available through 13.x, so
    this works across the pinned range without bumping the dependency.
    """
    import websockets

    return await websockets.connect(url)
