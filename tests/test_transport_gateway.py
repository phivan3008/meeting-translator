"""Integration tests for the FastAPI WebSocket gateway.

These exercise the handshake, binary streaming for two independent streams,
batched acknowledgements, duplicate/keepalive handling and typed error paths
using Starlette's in-process WebSocket test client. No real audio hardware is
involved.
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi.testclient import TestClient

from server.app import create_app
from shared.protocol.binary import AudioFlags, AudioFrameHeader, encode_packet
from shared.protocol.enums import PROTOCOL_VERSION, ErrorCode, EventType, Language, StreamSource
from shared.protocol.messages import SessionStart, StreamConfig
from shared.settings import Settings


def _settings() -> Settings:
    return Settings(
        _env_file=None,  # type: ignore[call-arg]
        ws_ack_every_packets=2,
        ws_ack_every_ms=999_999,
        ws_max_packet_bytes=1024,
    )


def _client() -> TestClient:
    return TestClient(create_app(_settings()))


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
            StreamConfig(
                stream_number=2,
                stream_id="loopback-01",
                source=StreamSource.LOOPBACK,
                source_language=Language.JAPANESE,
                target_language=Language.VIETNAMESE,
            ),
        ],
    )


def _frame(stream_number: int, seq: int, *, payload: bytes = b"\x00\x00") -> bytes:
    return encode_packet(
        stream_number=stream_number,
        sequence_number=seq,
        client_timestamp_ms=1000 + seq,
        payload=payload,
    )


def test_handshake_and_batched_acks_for_two_streams() -> None:
    client = _client()
    with client.websocket_connect("/ws/stream") as ws:
        ws.send_text(_session_start().model_dump_json())

        # Two mic frames -> one batched ack at last_contiguous 1.
        ws.send_bytes(_frame(1, 0))
        ws.send_bytes(_frame(1, 1))
        ack = ws.receive_json()
        assert ack["type"] == EventType.AUDIO_ACK.value
        assert ack["stream_id"] == "mic-01"
        assert ack["last_contiguous_sequence"] == 1

        # The loopback stream is independent with its own sequence space.
        ws.send_bytes(_frame(2, 0))
        ws.send_bytes(_frame(2, 1))
        ack2 = ws.receive_json()
        assert ack2["stream_id"] == "loopback-01"
        assert ack2["last_contiguous_sequence"] == 1


def test_duplicate_packet_is_idempotent() -> None:
    client = _client()
    with client.websocket_connect("/ws/stream") as ws:
        ws.send_text(_session_start().model_dump_json())
        ws.send_bytes(_frame(1, 0))
        ws.send_bytes(_frame(1, 0))  # duplicate, ignored
        ws.send_bytes(_frame(1, 1))
        ack = ws.receive_json()
        assert ack["last_contiguous_sequence"] == 1


def test_keepalive_frame_does_not_ack() -> None:
    client = _client()
    with client.websocket_connect("/ws/stream") as ws:
        ws.send_text(_session_start().model_dump_json())
        # Keepalive heartbeat carries no audio to order/ack.
        ws.send_bytes(
            encode_packet(
                stream_number=1,
                sequence_number=0,
                client_timestamp_ms=1,
                payload=b"",
                flags=AudioFlags.KEEPALIVE,
            )
        )
        ws.send_bytes(_frame(1, 0))
        ws.send_bytes(_frame(1, 1))
        ack = ws.receive_json()
        assert ack["last_contiguous_sequence"] == 1


def test_binary_first_frame_is_rejected() -> None:
    client = _client()
    with client.websocket_connect("/ws/stream") as ws:
        ws.send_bytes(_frame(1, 0))
        error = ws.receive_json()
        assert error["type"] == EventType.ERROR.value
        assert error["code"] == ErrorCode.MALFORMED_MESSAGE.value


def test_invalid_session_start_is_rejected() -> None:
    client = _client()
    with client.websocket_connect("/ws/stream") as ws:
        ws.send_text("{ not valid json")
        error = ws.receive_json()
        assert error["code"] == ErrorCode.MALFORMED_MESSAGE.value


def test_payload_too_large_is_rejected() -> None:
    client = _client()
    with client.websocket_connect("/ws/stream") as ws:
        ws.send_text(_session_start().model_dump_json())
        oversized = _frame(1, 0, payload=b"\x00" * 2048)
        ws.send_bytes(oversized)
        error = ws.receive_json()
        assert error["code"] == ErrorCode.PAYLOAD_TOO_LARGE.value


def test_malformed_packet_is_rejected() -> None:
    client = _client()
    with client.websocket_connect("/ws/stream") as ws:
        ws.send_text(_session_start().model_dump_json())
        bad = (
            AudioFrameHeader(
                protocol_version=PROTOCOL_VERSION + 1,
                stream_number=1,
                flags=0,
                sequence_number=0,
                client_timestamp_ms=1,
                payload_length=2,
            ).encode()
            + b"\x00\x00"
        )
        ws.send_bytes(bad)
        error = ws.receive_json()
        assert error["code"] == ErrorCode.MALFORMED_PACKET.value


def test_unknown_stream_number_is_rejected() -> None:
    client = _client()
    with client.websocket_connect("/ws/stream") as ws:
        ws.send_text(_session_start().model_dump_json())
        ws.send_bytes(_frame(9, 0))
        error = ws.receive_json()
        assert error["code"] == ErrorCode.INVALID_STREAM.value


def test_reconnect_after_connection_drop_gets_a_clean_session() -> None:
    """Models a server restart from the client's perspective.

    A dropped connection (real client disconnect, or the server process
    itself restarting) leaves no session state behind: a fresh connection --
    even one that resends the same session/stream ids and starts its
    sequence numbers over, exactly what ``AudioSender``'s reconnect/resend
    does (see ``tests/test_transport_sender.py``'s
    ``test_run_reconnect_after_server_restart_resends_only_unacked_frames``)
    -- must be accepted as an ordinary new session, with no stale
    cross-connection state and no crash.
    """
    client = _client()
    with client.websocket_connect("/ws/stream") as ws:
        ws.send_text(_session_start().model_dump_json())
        ws.send_bytes(_frame(1, 0))
        ws.send_bytes(_frame(1, 1))
        ack = ws.receive_json()
        assert ack["last_contiguous_sequence"] == 1
    # `with` exit closes the connection -- simulates the drop.

    # A fresh connection to the same running app, resending the client's
    # still-buffered frames (idempotent resend) from sequence 0 again, must
    # be handled as a brand-new session -- not rejected, not confused with
    # the previous (now-gone) one.
    with client.websocket_connect("/ws/stream") as ws:
        ws.send_text(_session_start().model_dump_json())
        ws.send_bytes(_frame(1, 0))
        ws.send_bytes(_frame(1, 1))
        ack = ws.receive_json()
        assert ack["type"] == EventType.AUDIO_ACK.value
        assert ack["stream_id"] == "mic-01"
        assert ack["last_contiguous_sequence"] == 1
