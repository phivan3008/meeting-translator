"""Session and per-stream context management.

A :class:`Session` owns one :class:`StreamContext` per declared stream. Each
context wraps the jitter buffer and ack batcher for that stream. The
:class:`SessionManager` creates sessions from a validated ``session.start``
message, enforces uniqueness, and provides lookup/removal. This module is
framework-independent and unit-testable without FastAPI.
"""

from __future__ import annotations

from server.transport.acks import AckBatcher
from server.transport.jitter_buffer import JitterBuffer
from shared.protocol.messages import SessionStart, StreamConfig


class SessionError(Exception):
    """Raised for invalid session lifecycle operations."""


class StreamContext:
    """Per-stream server state: jitter buffer, ack batcher and counters."""

    def __init__(
        self,
        *,
        config: StreamConfig,
        jitter_capacity: int,
        ack_every_packets: int,
        ack_every_ms: int,
    ) -> None:
        self._config = config
        self._jitter = JitterBuffer(start=0, capacity=jitter_capacity)
        self._acks = AckBatcher(every_packets=ack_every_packets, every_ms=ack_every_ms)
        self.packets_received = 0
        self.frames_released = 0
        self.duplicates = 0
        self.stale = 0
        self.lost = 0

    @property
    def config(self) -> StreamConfig:
        return self._config

    @property
    def stream_id(self) -> str:
        return self._config.stream_id

    @property
    def stream_number(self) -> int:
        return self._config.stream_number

    @property
    def jitter(self) -> JitterBuffer:
        return self._jitter

    @property
    def acks(self) -> AckBatcher:
        return self._acks


class Session:
    """A live client session with one context per stream."""

    def __init__(self, *, session_id: str, client_id: str) -> None:
        self.session_id = session_id
        self.client_id = client_id
        self._by_number: dict[int, StreamContext] = {}
        self._by_id: dict[str, StreamContext] = {}

    def add_stream(self, context: StreamContext) -> None:
        if context.stream_number in self._by_number:
            raise SessionError(f"duplicate stream_number {context.stream_number}")
        if context.stream_id in self._by_id:
            raise SessionError(f"duplicate stream_id {context.stream_id}")
        self._by_number[context.stream_number] = context
        self._by_id[context.stream_id] = context

    def stream_by_number(self, stream_number: int) -> StreamContext | None:
        return self._by_number.get(stream_number)

    def stream_by_id(self, stream_id: str) -> StreamContext | None:
        return self._by_id.get(stream_id)

    @property
    def stream_numbers(self) -> tuple[int, ...]:
        return tuple(sorted(self._by_number))

    @property
    def streams(self) -> tuple[StreamContext, ...]:
        return tuple(self._by_number[n] for n in sorted(self._by_number))


class SessionManager:
    """Create, look up and remove sessions. Enforces unique session ids."""

    def __init__(
        self,
        *,
        max_streams_per_session: int,
        jitter_capacity: int,
        ack_every_packets: int,
        ack_every_ms: int,
        max_sessions: int = 500,
    ) -> None:
        if max_sessions < 1:
            raise ValueError("max_sessions must be >= 1")
        self._max_streams = max_streams_per_session
        self._jitter_capacity = jitter_capacity
        self._ack_every_packets = ack_every_packets
        self._ack_every_ms = ack_every_ms
        self._max_sessions = max_sessions
        self._sessions: dict[str, Session] = {}

    @property
    def max_sessions(self) -> int:
        return self._max_sessions

    def create_session(self, start: SessionStart) -> Session:
        """Create a session from a validated ``session.start`` message."""
        if start.session_id in self._sessions:
            raise SessionError(f"session {start.session_id} already exists")
        if len(self._sessions) >= self._max_sessions:
            raise SessionError(f"server at capacity: {self._max_sessions} active sessions")
        if len(start.streams) > self._max_streams:
            raise SessionError(f"too many streams: {len(start.streams)} > {self._max_streams}")
        session = Session(session_id=start.session_id, client_id=start.client_id)
        for stream_config in start.streams:
            session.add_stream(
                StreamContext(
                    config=stream_config,
                    jitter_capacity=self._jitter_capacity,
                    ack_every_packets=self._ack_every_packets,
                    ack_every_ms=self._ack_every_ms,
                )
            )
        self._sessions[start.session_id] = session
        return session

    def get(self, session_id: str) -> Session | None:
        return self._sessions.get(session_id)

    def remove(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)

    @property
    def active_count(self) -> int:
        return len(self._sessions)
