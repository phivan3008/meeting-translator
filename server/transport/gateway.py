"""FastAPI WebSocket gateway.

Handles the ``session.start`` handshake, authentication, binary audio ingest for
independent streams, batched acknowledgements, heartbeats/idle handling, payload
and rate limits, and typed error events. Heavy downstream processing (VAD, ASR,
translation) is added in later phases; here released frames are validated,
ordered and acknowledged only.

Privacy: audio payloads and transcript/translation text are never logged. Only
sizes, sequence numbers and counts are recorded.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import ValidationError

from server.observability.correlation import bind
from server.observability.metrics import Metrics, get_default_metrics
from server.reliability.shutdown import ShutdownCoordinator
from server.transport.auth import Authenticator, AuthError
from server.transport.limits import TokenBucket
from server.transport.session import Session, SessionError, SessionManager
from shared.protocol.binary import (
    HEADER_SIZE,
    AudioFlags,
    PacketValidationError,
    decode_packet,
)
from shared.protocol.enums import ErrorCode
from shared.protocol.messages import AudioAck, ErrorEvent, SessionStart
from shared.settings import Settings

_LOG = logging.getLogger("server.transport.gateway")

# WebSocket application close code for policy violations / terminal handshake
# failures.
_CLOSE_POLICY_VIOLATION = 1008
# Standard WebSocket close code for "try again later" (RFC 6455 does not
# define 1013, but it is the widely-used convention, mirroring HTTP 503).
_CLOSE_SERVER_SHUTTING_DOWN = 1013


def _now() -> datetime:
    return datetime.now(UTC)


def create_gateway_router(
    *,
    settings: Settings,
    authenticator: Authenticator,
    session_manager: SessionManager,
    metrics: Metrics | None = None,
    shutdown: ShutdownCoordinator | None = None,
) -> APIRouter:
    """Create the WebSocket router bound to the given dependencies."""
    router = APIRouter()
    resolved_metrics = metrics if metrics is not None else get_default_metrics()

    @router.websocket("/ws/stream")
    async def stream(websocket: WebSocket) -> None:
        await _handle_connection(
            websocket,
            settings=settings,
            authenticator=authenticator,
            session_manager=session_manager,
            metrics=resolved_metrics,
            shutdown=shutdown,
        )

    return router


async def _handle_connection(
    websocket: WebSocket,
    *,
    settings: Settings,
    authenticator: Authenticator,
    session_manager: SessionManager,
    metrics: Metrics,
    shutdown: ShutdownCoordinator | None,
) -> None:
    await websocket.accept()
    if shutdown is not None and shutdown.is_shutting_down:
        # Reject new work during a graceful shutdown drain; existing
        # sessions already in the ingest loop are left to finish/disconnect
        # on their own (see server/app.py's shutdown handler).
        await websocket.close(code=_CLOSE_SERVER_SHUTTING_DOWN)
        return
    session: Session | None = None
    try:
        session = await _handshake(
            websocket,
            authenticator=authenticator,
            session_manager=session_manager,
        )
        if session is None:
            return
        metrics.sessions_active.inc()
        with bind(session_id=session.session_id):
            await _ingest_loop(websocket, settings=settings, session=session, metrics=metrics)
    except WebSocketDisconnect:
        _LOG.info("client disconnected")
    finally:
        if session is not None:
            session_manager.remove(session.session_id)
            metrics.sessions_active.dec()


async def _handshake(
    websocket: WebSocket,
    *,
    authenticator: Authenticator,
    session_manager: SessionManager,
) -> Session | None:
    """Receive and validate ``session.start``; authenticate; create session.

    Returns the created session, or ``None`` if the handshake failed (an error
    event has already been sent and the socket closed).
    """
    message = await websocket.receive()
    if message.get("type") == "websocket.disconnect":
        raise WebSocketDisconnect(code=message.get("code", 1000))

    text = message.get("text")
    if text is None:
        await _fail(
            websocket,
            session_id="",
            code=ErrorCode.MALFORMED_MESSAGE,
            message="first frame must be a session.start text message",
        )
        return None

    try:
        start = SessionStart.model_validate_json(text)
    except ValidationError:
        await _fail(
            websocket,
            session_id="",
            code=ErrorCode.MALFORMED_MESSAGE,
            message="invalid session.start message",
        )
        return None

    token = websocket.query_params.get("token")
    if token is None:
        token = _bearer_token(websocket.headers.get("authorization"))
    try:
        authenticator.authenticate(token=token, client_id=start.client_id)
    except AuthError:
        await _fail(
            websocket,
            session_id=start.session_id,
            code=ErrorCode.AUTH_FAILED,
            message="authentication failed",
        )
        return None

    if session_manager.active_count >= session_manager.max_sessions:
        await _fail(
            websocket,
            session_id=start.session_id,
            code=ErrorCode.OVERLOADED,
            message="server at capacity",
            retryable=True,
        )
        return None

    try:
        return session_manager.create_session(start)
    except SessionError:
        await _fail(
            websocket,
            session_id=start.session_id,
            code=ErrorCode.INVALID_STREAM,
            message="session could not be created",
        )
        return None


async def _ingest_loop(
    websocket: WebSocket,
    *,
    settings: Settings,
    session: Session,
    metrics: Metrics,
) -> None:
    bucket = TokenBucket(
        rate_per_sec=settings.ws_rate_limit_packets_per_sec,
        burst=settings.ws_rate_limit_burst,
    )
    idle_timeout_s = settings.ws_idle_timeout_ms / 1000.0
    max_payload = settings.ws_max_packet_bytes

    while True:
        try:
            message = await asyncio.wait_for(websocket.receive(), timeout=idle_timeout_s)
        except TimeoutError:
            _LOG.info("session %s idle timeout", session.session_id)
            await websocket.close(code=_CLOSE_POLICY_VIOLATION)
            return

        if message.get("type") == "websocket.disconnect":
            raise WebSocketDisconnect(code=message.get("code", 1000))

        data = message.get("bytes")
        if data is None:
            # Text frames after the handshake are not part of the ingest path.
            continue

        await _handle_packet(
            websocket,
            session=session,
            data=data,
            bucket=bucket,
            max_payload=max_payload,
            metrics=metrics,
        )


async def _handle_packet(
    websocket: WebSocket,
    *,
    session: Session,
    data: bytes,
    bucket: TokenBucket,
    max_payload: int,
    metrics: Metrics,
) -> None:
    if not bucket.try_consume(1, now=asyncio.get_event_loop().time()):
        await _send_error(
            websocket,
            session_id=session.session_id,
            code=ErrorCode.OVERLOADED,
            message="packet rate limit exceeded",
            retryable=True,
        )
        return

    if len(data) > HEADER_SIZE + max_payload:
        await _send_error(
            websocket,
            session_id=session.session_id,
            code=ErrorCode.PAYLOAD_TOO_LARGE,
            message="audio packet exceeds size limit",
        )
        return

    try:
        header, payload = decode_packet(data, max_payload_bytes=max_payload)
    except PacketValidationError:
        await _send_error(
            websocket,
            session_id=session.session_id,
            code=ErrorCode.MALFORMED_PACKET,
            message="audio packet failed validation",
        )
        return

    context = session.stream_by_number(header.stream_number)
    if context is None:
        await _send_error(
            websocket,
            session_id=session.session_id,
            code=ErrorCode.INVALID_STREAM,
            message=f"unknown stream_number {header.stream_number}",
        )
        return

    with bind(stream_id=context.stream_id):
        source = context.config.source.value
        context.packets_received += 1
        metrics.packets_received_total.labels(source=source).inc()

        # Keepalive frames are heartbeats: they carry no audio to order or
        # release.
        if header.flags & int(AudioFlags.KEEPALIVE):
            return

        result = context.jitter.offer(header, payload)
        if result.duplicate:
            if result.stale:
                context.stale += 1
            else:
                context.duplicates += 1
            metrics.packets_duplicate_total.labels(source=source).inc()
            return

        context.frames_released += len(result.released)
        if result.overflow_skipped:
            context.lost += result.overflow_skipped
            metrics.packets_lost_total.labels(source=source).inc(result.overflow_skipped)
            _LOG.warning(
                "session %s stream %d lost %d packets (jitter overflow)",
                session.session_id,
                context.stream_number,
                result.overflow_skipped,
            )
        # Released frames are consumed by VAD/ASR in later phases.

        now_ms = int(asyncio.get_event_loop().time() * 1000)
        ack_sequence = context.acks.record(result.last_contiguous, now_ms=now_ms)
        if ack_sequence is not None:
            await _send_event(
                websocket,
                AudioAck(
                    session_id=session.session_id,
                    stream_id=context.stream_id,
                    last_contiguous_sequence=ack_sequence,
                    timestamp=_now(),
                ),
            )


def _bearer_token(authorization: str | None) -> str | None:
    if not authorization:
        return None
    parts = authorization.split(" ", 1)
    if len(parts) == 2 and parts[0].lower() == "bearer":
        return parts[1].strip()
    return None


async def _send_event(websocket: WebSocket, event: AudioAck | ErrorEvent) -> None:
    payload: dict[str, Any] = event.model_dump(mode="json")
    await websocket.send_json(payload)


async def _send_error(
    websocket: WebSocket,
    *,
    session_id: str,
    code: ErrorCode,
    message: str,
    retryable: bool = False,
) -> None:
    await _send_event(
        websocket,
        ErrorEvent(
            session_id=session_id,
            code=code,
            message=message,
            retryable=retryable,
            timestamp=_now(),
        ),
    )


async def _fail(
    websocket: WebSocket,
    *,
    session_id: str,
    code: ErrorCode,
    message: str,
    retryable: bool = False,
) -> None:
    """Send a terminal error event and close the connection."""
    try:
        await _send_error(
            websocket,
            session_id=session_id,
            code=code,
            message=message,
            retryable=retryable,
        )
    finally:
        await websocket.close(code=_CLOSE_POLICY_VIOLATION)
