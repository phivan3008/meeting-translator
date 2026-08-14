"""Unit tests for the readiness translation-backend reachability probe.

Uses ``httpx.MockTransport`` (no real network) to exercise
``server.app._check_translation_backend`` directly, independent of the
FastAPI endpoint wiring (covered separately in ``tests/test_health.py``).
"""

from __future__ import annotations

import httpx

from server.app import _check_translation_backend
from shared.settings import Settings


def _settings(**overrides: object) -> Settings:
    return Settings(_env_file=None, **overrides)  # type: ignore[call-arg, arg-type]


async def test_returns_true_on_200() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/models"
        return httpx.Response(200, json={"data": []})

    settings = _settings()
    result = await _check_translation_backend(settings, transport=httpx.MockTransport(handler))
    assert result is True


async def test_returns_false_on_non_200() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503)

    settings = _settings()
    result = await _check_translation_backend(settings, transport=httpx.MockTransport(handler))
    assert result is False


async def test_returns_false_on_connection_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    settings = _settings()
    result = await _check_translation_backend(settings, transport=httpx.MockTransport(handler))
    assert result is False


async def test_returns_false_on_timeout() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("timed out", request=request)

    settings = _settings()
    result = await _check_translation_backend(settings, transport=httpx.MockTransport(handler))
    assert result is False


async def test_uses_configured_base_url() -> None:
    seen_urls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_urls.append(str(request.url))
        return httpx.Response(200)

    settings = _settings(vllm_base_url="http://translation-gpu.internal:8000/v1")
    await _check_translation_backend(settings, transport=httpx.MockTransport(handler))

    assert seen_urls == ["http://translation-gpu.internal:8000/v1/models"]
