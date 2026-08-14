"""Tests for the FastAPI liveness and readiness endpoints."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import server.app as app_module
from server.app import create_app
from shared.settings import Settings


def _client(settings: Settings | None = None) -> TestClient:
    resolved = settings or Settings(_env_file=None)  # type: ignore[call-arg]
    return TestClient(create_app(resolved))


def test_liveness_ok() -> None:
    client = _client()
    response = client.get("/health/live")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "alive"
    assert body["app_env"] == "development"


def test_readiness_ok() -> None:
    client = _client()
    response = client.get("/health/ready")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ready"
    assert body["checks"]["settings"] is True
    assert body["checks"]["not_shutting_down"] is True
    # Disabled by default -- no real vLLM reachable in this environment.
    assert "translation_backend" not in body["checks"]


def test_readiness_reflects_shutdown_state() -> None:
    settings = Settings(_env_file=None)  # type: ignore[call-arg]
    app = create_app(settings)
    client = TestClient(app)

    app.state.shutdown.begin_shutdown()
    response = client.get("/health/ready")

    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "not_ready"
    assert body["checks"]["not_shutting_down"] is False


def test_readiness_translation_backend_check_enabled_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(_env_file=None, readiness_check_translation_backend=True)  # type: ignore[call-arg]

    async def _fake_check(*args: object, **kwargs: object) -> bool:
        return True

    monkeypatch.setattr(app_module, "_check_translation_backend", _fake_check)
    client = _client(settings)

    response = client.get("/health/ready")

    assert response.status_code == 200
    body = response.json()
    assert body["checks"]["translation_backend"] is True


def test_readiness_translation_backend_check_enabled_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(_env_file=None, readiness_check_translation_backend=True)  # type: ignore[call-arg]

    async def _fake_check(*args: object, **kwargs: object) -> bool:
        return False

    monkeypatch.setattr(app_module, "_check_translation_backend", _fake_check)
    client = _client(settings)

    response = client.get("/health/ready")

    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "not_ready"
    assert body["checks"]["translation_backend"] is False
    # No raw error/hostname detail leaked -- only the boolean.
    assert "vllm" not in str(body).lower()
    assert "http" not in str(body).lower()
