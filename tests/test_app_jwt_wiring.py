"""Integration tests for JWT authenticator selection in create_app().

Confirms `server.app.create_app` actually wires `JwtAuthenticator` in when
`jwt_public_key_path` is configured (instead of the anonymous-friendly dev
`StaticTokenAuthenticator`), using a real, locally-generated RSA keypair --
no network access.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime
from pathlib import Path

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from server.app import create_app
from shared.protocol.binary import encode_packet
from shared.protocol.enums import ErrorCode, Language, StreamSource
from shared.protocol.messages import SessionStart, StreamConfig
from shared.settings import Settings

ISSUER = "meeting-translator"
AUDIENCE = "meeting-translator-client"


@pytest.fixture(scope="module")
def keypair() -> tuple[str, str]:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("utf-8")
    public_pem = (
        private_key.public_key()
        .public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode("utf-8")
    )
    return private_pem, public_pem


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
        ],
    )


def test_jwt_authenticator_rejects_connection_without_token(
    tmp_path: Path, keypair: tuple[str, str]
) -> None:
    _, public_pem = keypair
    key_path = tmp_path / "public.pem"
    key_path.write_text(public_pem, encoding="utf-8")

    settings = Settings(  # type: ignore[call-arg]
        _env_file=None,
        jwt_public_key_path=str(key_path),
        jwt_issuer=ISSUER,
        jwt_audience=AUDIENCE,
        # Development anonymous access would normally be allowed here
        # (app_env defaults to "development"); configuring a JWT key must
        # override that and require a real token regardless.
        app_env="development",
    )
    client = TestClient(create_app(settings))

    with client.websocket_connect("/ws/stream") as ws:
        ws.send_text(_session_start().model_dump_json())
        error = ws.receive_json()
        assert error["code"] == ErrorCode.AUTH_FAILED.value


def test_jwt_authenticator_accepts_valid_token(tmp_path: Path, keypair: tuple[str, str]) -> None:
    private_pem, public_pem = keypair
    key_path = tmp_path / "public.pem"
    key_path.write_text(public_pem, encoding="utf-8")

    settings = Settings(  # type: ignore[call-arg]
        _env_file=None,
        jwt_public_key_path=str(key_path),
        jwt_issuer=ISSUER,
        jwt_audience=AUDIENCE,
        ws_ack_every_packets=1,  # ack deterministically after one packet
        ws_ack_every_ms=999_999,
    )
    client = TestClient(create_app(settings))

    now = time.time()
    token = jwt.encode(
        {
            "sub": "user-1",
            "iss": ISSUER,
            "aud": AUDIENCE,
            "iat": now,
            "exp": now + 300,
        },
        private_pem,
        algorithm="RS256",
    )

    with client.websocket_connect(f"/ws/stream?token={token}") as ws:
        ws.send_text(_session_start().model_dump_json())
        ws.send_bytes(
            encode_packet(
                stream_number=1, sequence_number=0, client_timestamp_ms=1, payload=b"\x00\x00"
            )
        )
        ack = ws.receive_json()
        assert ack["type"] == "audio.ack"


def test_create_app_fails_fast_when_key_file_missing(tmp_path: Path) -> None:
    settings = Settings(  # type: ignore[call-arg]
        _env_file=None,
        jwt_public_key_path=str(tmp_path / "does-not-exist.pem"),
        jwt_issuer=ISSUER,
        jwt_audience=AUDIENCE,
    )
    with pytest.raises(RuntimeError):
        create_app(settings)


def test_no_jwt_key_configured_uses_dev_authenticator_and_allows_anonymous() -> None:
    settings = Settings(  # type: ignore[call-arg]
        _env_file=None,
        app_env="development",
        ws_ack_every_packets=1,
        ws_ack_every_ms=999_999,
    )
    client = TestClient(create_app(settings))

    with client.websocket_connect("/ws/stream") as ws:
        ws.send_text(_session_start().model_dump_json())
        ws.send_bytes(
            encode_packet(
                stream_number=1, sequence_number=0, client_timestamp_ms=1, payload=b"\x00\x00"
            )
        )
        ack = ws.receive_json()
        assert ack["type"] == "audio.ack"
