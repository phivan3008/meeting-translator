"""FastAPI WebSocket gateway.

Handles the ``session.start`` handshake, authentication, binary audio ingest for
independent streams, batched acknowledgements, heartbeats/idle handling, payload
and rate limits, and typed error events. Released frames are fed through a
per-session :class:`~server.orchestration.pipeline.UtteranceOrchestrator`
(VAD -> partial ASR -> final ASR -> translation), and the events it publishes
are sent back to the client as protocol JSON messages -- see
``OrchestrationDeps`` and ``_build_orchestrator`` below.

Privacy: audio payloads and transcript/translation text are never logged. Only
sizes, sequence numbers and counts are recorded.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from concurrent.futures import Executor
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import ValidationError

from server.asr.interface import AsrModel
from server.asr.types import AsrConfig
from server.observability.correlation import bind
from server.observability.metrics import Metrics, get_default_metrics
from server.orchestration.heuristics import HeuristicConfig
from server.orchestration.pipeline import UtteranceOrchestrator
from server.orchestration.types import CompletenessConfig, OrchestratorEvent
from server.reliability.circuit_breaker import CircuitBreaker
from server.reliability.shutdown import ShutdownCoordinator
from server.translation.interface import TranslationClient
from server.translation.types import TranslationConfig
from server.transport.auth import Authenticator, AuthError
from server.transport.limits import TokenBucket
from server.transport.session import Session, SessionError, SessionManager
from server.vad.interface import VadModel
from server.vad.types import VadConfig
from shared.protocol.binary import (
    HEADER_SIZE,
    AudioFlags,
    PacketValidationError,
    decode_packet,
)
from shared.protocol.enums import ErrorCode, FinalReason
from shared.protocol.messages import AudioAck, ErrorEvent, SessionStart
from shared.settings import Settings

_LOG = logging.getLogger("server.transport.gateway")

VadModelFactory = Callable[[], VadModel]

# WebSocket application close code for policy violations / terminal handshake
# failures.
_CLOSE_POLICY_VIOLATION = 1008
# Standard WebSocket close code for "try again later" (RFC 6455 does not
# define 1013, but it is the widely-used convention, mirroring HTTP 503).
_CLOSE_SERVER_SHUTTING_DOWN = 1013


def _now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class OrchestrationDeps:
    """Session-independent dependencies for building one session's
    :class:`~server.orchestration.pipeline.UtteranceOrchestrator`.

    ``asr_model``/``translation_client`` are shared singletons (safe across
    concurrent sessions -- see ``server/app.py``); ``vad_model_factory``
    builds one fresh :class:`~server.vad.interface.VadModel` per stream,
    since Silero's loaded model holds real recurrent state and must never
    be shared across streams. ``vad_executor`` offloads VAD probability
    calls off the event loop (they must never block it, per
    ``VadModel``'s own contract). Constructed once in ``server/app.py``.
    """

    asr_model: AsrModel
    asr_config: AsrConfig
    translation_client: TranslationClient
    translation_config: TranslationConfig
    vad_config: VadConfig
    heuristic_config: HeuristicConfig
    completeness_config: CompletenessConfig
    vad_model_factory: VadModelFactory
    vad_executor: Executor
    asr_circuit_breaker: CircuitBreaker
    translation_circuit_breaker: CircuitBreaker
    frame_ms: int = 20
    partial_interval_ms: int = 500
    partial_overlap_ms: int = 1500
    asr_final_timeout_ms: int = 8000
    translation_queue_capacity_per_priority: int = 16


def create_gateway_router(
    *,
    settings: Settings,
    authenticator: Authenticator,
    session_manager: SessionManager,
    orchestration: OrchestrationDeps,
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
            orchestration=orchestration,
            metrics=resolved_metrics,
            shutdown=shutdown,
        )

    return router


def _build_orchestrator(
    websocket: WebSocket,
    *,
    session: Session,
    orchestration: OrchestrationDeps,
    metrics: Metrics,
) -> tuple[UtteranceOrchestrator, dict[str, VadModel]]:
    """Construct one session's orchestrator plus one VAD model per stream.

    The ``publish`` callback swallows send failures rather than raising --
    background finalize/retry/completeness tasks may still be in flight
    after the client disconnects (see ``_flush_all_streams``/cleanup in
    ``_handle_connection``), and a failed send into an already-closing
    socket is expected there, not an error.
    """

    async def publish(event: OrchestratorEvent) -> None:
        try:
            await _send_event(websocket, event)
        except Exception:  # noqa: BLE001 - a disconnected socket must never crash a background task
            _LOG.debug("session %s: dropping event, socket already closed", session.session_id)

    orchestrator = UtteranceOrchestrator(
        session_id=session.session_id,
        vad_config=orchestration.vad_config,
        frame_ms=orchestration.frame_ms,
        asr_config=orchestration.asr_config,
        asr_model=orchestration.asr_model,
        translation_config=orchestration.translation_config,
        translation_client=orchestration.translation_client,
        publish=publish,
        heuristic_config=orchestration.heuristic_config,
        completeness_config=orchestration.completeness_config,
        partial_interval_ms=orchestration.partial_interval_ms,
        partial_overlap_ms=orchestration.partial_overlap_ms,
        asr_final_timeout_ms=orchestration.asr_final_timeout_ms,
        translation_queue_capacity_per_priority=orchestration.translation_queue_capacity_per_priority,
        metrics=metrics,
        asr_circuit_breaker=orchestration.asr_circuit_breaker,
        translation_circuit_breaker=orchestration.translation_circuit_breaker,
    )
    vad_models: dict[str, VadModel] = {}
    for context in session.streams:
        orchestrator.add_stream(
            context.stream_id,
            source=context.config.source,
            source_language=context.config.source_language,
            target_language=context.config.target_language,
        )
        vad_models[context.stream_id] = orchestration.vad_model_factory()
    return orchestrator, vad_models


async def _flush_all_streams(orchestrator: UtteranceOrchestrator, session: Session) -> None:
    """Best-effort final flush of every stream on session teardown.

    Never raises: one stream's flush failing must not prevent the rest of
    cleanup (session removal, metrics) from completing, matching the
    "must never raise" precedent already used for readiness checks in
    ``server/app.py``'s ``_check_translation_backend``.
    """
    for context in session.streams:
        try:
            await orchestrator.flush_stream(context.stream_id, FinalReason.SESSION_END)
        except Exception:  # noqa: BLE001 - cleanup must not block on a single stream's failure
            _LOG.warning(
                "session %s stream %s: flush on disconnect failed",
                session.session_id,
                context.stream_id,
            )


async def _handle_connection(
    websocket: WebSocket,
    *,
    settings: Settings,
    authenticator: Authenticator,
    session_manager: SessionManager,
    orchestration: OrchestrationDeps,
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
    orchestrator: UtteranceOrchestrator | None = None
    try:
        session = await _handshake(
            websocket,
            authenticator=authenticator,
            session_manager=session_manager,
        )
        if session is None:
            return
        metrics.sessions_active.inc()
        orchestrator, vad_models = _build_orchestrator(
            websocket, session=session, orchestration=orchestration, metrics=metrics
        )
        with bind(session_id=session.session_id):
            await _ingest_loop(
                websocket,
                settings=settings,
                session=session,
                metrics=metrics,
                orchestrator=orchestrator,
                vad_models=vad_models,
                vad_executor=orchestration.vad_executor,
                frame_ms=orchestration.frame_ms,
            )
    except WebSocketDisconnect:
        _LOG.info("client disconnected")
    finally:
        if orchestrator is not None and session is not None:
            await _flush_all_streams(orchestrator, session)
            orchestrator.close()
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
    orchestrator: UtteranceOrchestrator,
    vad_models: dict[str, VadModel],
    vad_executor: Executor,
    frame_ms: int,
) -> None:
    bucket = TokenBucket(
        rate_per_sec=settings.ws_rate_limit_packets_per_sec,
        burst=settings.ws_rate_limit_burst,
    )
    idle_timeout_s = settings.ws_idle_timeout_ms / 1000.0
    max_payload = settings.ws_max_packet_bytes
    # Audio-timeline clock fed to orchestrator.run_due_partial_decodes,
    # advanced by frame_ms per frame actually ingested (across however
    # many streams this session has) -- NOT wall-clock time. This must
    # stay in the same domain as each stream's UtteranceSegmenter.now_ms
    # (which PartialDecodeScheduler.start() is seeded from internally):
    # both are frame-count-driven. Wall-clock elapsed time was tried and
    # rejected -- it can lag far behind the frame-domain clock whenever
    # frames are processed faster than real-time (e.g. a test sending a
    # burst of frames with no pacing), which starves partial decodes of
    # ever becoming "due" before an utterance finalizes.
    audio_now_ms = 0

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

        audio_now_ms = await _handle_packet(
            websocket,
            session=session,
            data=data,
            bucket=bucket,
            max_payload=max_payload,
            metrics=metrics,
            orchestrator=orchestrator,
            vad_models=vad_models,
            vad_executor=vad_executor,
            frame_ms=frame_ms,
            audio_now_ms=audio_now_ms,
        )


async def _handle_packet(
    websocket: WebSocket,
    *,
    session: Session,
    data: bytes,
    bucket: TokenBucket,
    max_payload: int,
    metrics: Metrics,
    orchestrator: UtteranceOrchestrator,
    vad_models: dict[str, VadModel],
    vad_executor: Executor,
    frame_ms: int,
    audio_now_ms: int,
) -> int:
    """Handle one incoming packet; returns the (possibly advanced) audio-timeline clock."""
    if not bucket.try_consume(1, now=asyncio.get_event_loop().time()):
        await _send_error(
            websocket,
            session_id=session.session_id,
            code=ErrorCode.OVERLOADED,
            message="packet rate limit exceeded",
            retryable=True,
        )
        return audio_now_ms

    if len(data) > HEADER_SIZE + max_payload:
        await _send_error(
            websocket,
            session_id=session.session_id,
            code=ErrorCode.PAYLOAD_TOO_LARGE,
            message="audio packet exceeds size limit",
        )
        return audio_now_ms

    try:
        header, payload = decode_packet(data, max_payload_bytes=max_payload)
    except PacketValidationError:
        await _send_error(
            websocket,
            session_id=session.session_id,
            code=ErrorCode.MALFORMED_PACKET,
            message="audio packet failed validation",
        )
        return audio_now_ms

    context = session.stream_by_number(header.stream_number)
    if context is None:
        await _send_error(
            websocket,
            session_id=session.session_id,
            code=ErrorCode.INVALID_STREAM,
            message=f"unknown stream_number {header.stream_number}",
        )
        return audio_now_ms

    with bind(stream_id=context.stream_id):
        source = context.config.source.value
        context.packets_received += 1
        metrics.packets_received_total.labels(source=source).inc()

        # Keepalive frames are heartbeats: they carry no audio to order or
        # release.
        if header.flags & int(AudioFlags.KEEPALIVE):
            return audio_now_ms

        result = context.jitter.offer(header, payload)
        if result.duplicate:
            if result.stale:
                context.stale += 1
            else:
                context.duplicates += 1
            metrics.packets_duplicate_total.labels(source=source).inc()
            return audio_now_ms

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
        if result.released:
            loop = asyncio.get_event_loop()
            vad_model = vad_models[context.stream_id]
            for released_frame in result.released:
                frame_pcm = released_frame.payload
                probability = await loop.run_in_executor(
                    vad_executor, vad_model.probability, frame_pcm
                )
                await orchestrator.ingest_frame(context.stream_id, frame_pcm, probability)
                audio_now_ms += frame_ms
            await orchestrator.run_due_partial_decodes(now_ms=audio_now_ms)

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

    return audio_now_ms


def _bearer_token(authorization: str | None) -> str | None:
    if not authorization:
        return None
    parts = authorization.split(" ", 1)
    if len(parts) == 2 and parts[0].lower() == "bearer":
        return parts[1].strip()
    return None


async def _send_event(websocket: WebSocket, event: AudioAck | OrchestratorEvent) -> None:
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
