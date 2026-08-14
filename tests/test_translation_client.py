"""Tests for the vLLM OpenAI-compatible client against a local mock transport.

No real vLLM server is used or required: ``httpx.MockTransport`` intercepts
requests entirely in-process.
"""

from __future__ import annotations

import json
from collections.abc import Callable

import httpx
import pytest

from server.translation.client import VllmTranslationClient
from server.translation.errors import (
    TranslationFailedError,
    TranslationOverloadedError,
    TranslationTimeoutError,
)
from server.translation.types import TranslationConfig

CONFIG = TranslationConfig(
    base_url="http://vllm.local/v1",
    api_key="EMPTY",
    model="qwen3.6-27b-translate",
    max_input_tokens=768,
    max_output_tokens=256,
    timeout_ms=3000,
    max_concurrency=8,
)

Handler = Callable[[httpx.Request], httpx.Response]


def _client_with_handler(handler: Handler) -> VllmTranslationClient:
    transport = httpx.MockTransport(handler)
    http_client = httpx.AsyncClient(transport=transport, base_url=CONFIG.base_url)
    return VllmTranslationClient(CONFIG, http_client=http_client)


async def test_successful_completion_returns_content_and_correct_payload() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/chat/completions"
        body = json.loads(request.content)
        captured.update(body)
        return httpx.Response(200, json={"choices": [{"message": {"content": "Xin chào"}}]})

    client = _client_with_handler(handler)
    try:
        text = await client.complete_chat(system_prompt="sys", user_content="user", max_tokens=100)
    finally:
        await client.aclose()

    assert text == "Xin chào"
    assert captured["model"] == "qwen3.6-27b-translate"
    assert captured["temperature"] == 0.0
    assert captured["top_p"] == 1.0
    assert captured["stream"] is False
    assert captured["max_tokens"] == 100
    assert captured["chat_template_kwargs"] == {"enable_thinking": False}
    assert captured["messages"] == [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "user"},
    ]


async def test_authorization_header_sent() -> None:
    seen: dict[str, str | None] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers.get("authorization")
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

    client = _client_with_handler(handler)
    try:
        await client.complete_chat(system_prompt="s", user_content="u", max_tokens=10)
    finally:
        await client.aclose()
    assert seen["auth"] == "Bearer EMPTY"


async def test_429_maps_to_overloaded() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, text="busy")

    client = _client_with_handler(handler)
    try:
        with pytest.raises(TranslationOverloadedError):
            await client.complete_chat(system_prompt="s", user_content="u", max_tokens=10)
    finally:
        await client.aclose()


async def test_503_maps_to_overloaded() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="unavailable")

    client = _client_with_handler(handler)
    try:
        with pytest.raises(TranslationOverloadedError):
            await client.complete_chat(system_prompt="s", user_content="u", max_tokens=10)
    finally:
        await client.aclose()


async def test_500_maps_to_failed() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    client = _client_with_handler(handler)
    try:
        with pytest.raises(TranslationFailedError):
            await client.complete_chat(system_prompt="s", user_content="u", max_tokens=10)
    finally:
        await client.aclose()


async def test_timeout_maps_to_timeout_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("timed out", request=request)

    client = _client_with_handler(handler)
    try:
        with pytest.raises(TranslationTimeoutError):
            await client.complete_chat(system_prompt="s", user_content="u", max_tokens=10)
    finally:
        await client.aclose()


async def test_malformed_json_response_maps_to_failed() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="not json")

    client = _client_with_handler(handler)
    try:
        with pytest.raises(TranslationFailedError):
            await client.complete_chat(system_prompt="s", user_content="u", max_tokens=10)
    finally:
        await client.aclose()


async def test_missing_choices_maps_to_failed() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"unexpected": True})

    client = _client_with_handler(handler)
    try:
        with pytest.raises(TranslationFailedError):
            await client.complete_chat(system_prompt="s", user_content="u", max_tokens=10)
    finally:
        await client.aclose()


async def test_injected_client_is_not_closed_by_aclose() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

    transport = httpx.MockTransport(handler)
    http_client = httpx.AsyncClient(transport=transport, base_url=CONFIG.base_url)
    client = VllmTranslationClient(CONFIG, http_client=http_client)
    await client.complete_chat(system_prompt="s", user_content="u", max_tokens=10)
    await client.aclose()
    assert http_client.is_closed is False
    await http_client.aclose()
