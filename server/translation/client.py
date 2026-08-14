"""Async OpenAI-compatible vLLM chat-completions client.

``httpx`` is a plain CPU-only HTTP client (already part of the ``server``/
``dev`` extras, unlike GPU inference libraries), so unlike the ASR/VAD GPU
adapters this module is imported directly (not lazily) and is fully
unit-testable against a local mock transport -- no real vLLM server needed.
"""

from __future__ import annotations

from typing import Any

import httpx

from server.translation.errors import (
    TranslationFailedError,
    TranslationOverloadedError,
    classify_backend_error,
)
from server.translation.types import TranslationConfig

_CHAT_COMPLETIONS_PATH = "/chat/completions"
_OVERLOADED_STATUS_CODES = frozenset({429, 503})


class VllmTranslationClient:
    """Adapter exposing :class:`~server.translation.interface.TranslationClient` over vLLM.

    Non-thinking mode, no output streaming, temperature/top-p from
    ``config`` (fixed at 0/1 per the documented baseline). Timeout and
    cancellation are the caller's responsibility (see
    ``server.translation.worker.FinalTranslator``), matching the pattern
    used for the ASR final transcriber.
    """

    def __init__(
        self, config: TranslationConfig, *, http_client: httpx.AsyncClient | None = None
    ) -> None:
        self._config = config
        self._owns_client = http_client is None
        self._client = http_client or httpx.AsyncClient(base_url=config.base_url)

    async def complete_chat(self, *, system_prompt: str, user_content: str, max_tokens: int) -> str:
        payload: dict[str, Any] = {
            "model": self._config.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
            "temperature": self._config.temperature,
            "top_p": self._config.top_p,
            "max_tokens": max_tokens,
            "stream": False,
            # Non-thinking mode (docs/ARCHITECTURE.md translation baseline).
            "chat_template_kwargs": {"enable_thinking": False},
        }
        headers = {"Authorization": f"Bearer {self._config.api_key}"}

        try:
            response = await self._client.post(
                _CHAT_COMPLETIONS_PATH, json=payload, headers=headers
            )
        except httpx.HTTPError as exc:
            raise classify_backend_error(exc) from exc

        if response.status_code in _OVERLOADED_STATUS_CODES:
            raise TranslationOverloadedError(f"vLLM overloaded (status {response.status_code})")
        if response.is_error:
            raise TranslationFailedError(f"vLLM returned status {response.status_code}")

        try:
            data = response.json()
            return str(data["choices"][0]["message"]["content"])
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise TranslationFailedError("malformed vLLM response") from exc

    async def aclose(self) -> None:
        """Close the owned HTTP client, if any (injected clients are the caller's)."""
        if self._owns_client:
            await self._client.aclose()
