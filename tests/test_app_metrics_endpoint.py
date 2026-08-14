"""Tests for the /metrics endpoint."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi.testclient import TestClient

from server.app import create_app
from server.observability.metrics import create_metrics
from shared.protocol.binary import encode_packet
from shared.protocol.enums import Language, StreamSource
from shared.protocol.messages import SessionStart, StreamConfig
from shared.settings import Settings


def test_metrics_endpoint_exposes_prometheus_text_format() -> None:
    metrics = create_metrics()
    metrics.sessions_active.set(2)
    metrics.packets_received_total.labels(source="microphone").inc()

    settings = Settings(_env_file=None)  # type: ignore[call-arg]
    client = TestClient(create_app(settings, metrics=metrics))

    response = client.get("/metrics")

    assert response.status_code == 200
    assert "text/plain" in response.headers["content-type"]
    body = response.text
    assert "meeting_translator_sessions_active 2.0" in body
    assert 'meeting_translator_packets_received_total{source="microphone"} 1.0' in body


def test_metrics_endpoint_reflects_gateway_activity() -> None:
    metrics = create_metrics()
    settings = Settings(_env_file=None)  # type: ignore[call-arg]
    client = TestClient(create_app(settings, metrics=metrics))

    session_start = SessionStart(
        session_id="sess-metrics-1",
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

    with client.websocket_connect("/ws/stream") as ws:
        ws.send_text(session_start.model_dump_json())
        ws.send_bytes(
            encode_packet(
                stream_number=1, sequence_number=0, client_timestamp_ms=1, payload=b"\x00\x00"
            )
        )

    body = client.get("/metrics").text
    assert 'meeting_translator_packets_received_total{source="microphone"} 1.0' in body
