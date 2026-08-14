"""Translation backend client interface.

The final translation service depends only on :class:`TranslationClient`.
Concrete implementations (the vLLM OpenAI-compatible client, or a
deterministic scripted client for tests) implement this Protocol.

Implementations are async and perform network I/O; unlike the ASR/VAD model
protocols they run directly on the event loop (no executor needed), matching
a plain async HTTP client.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class TranslationClient(Protocol):
    """Completes a single chat-style translation request."""

    async def complete_chat(self, *, system_prompt: str, user_content: str, max_tokens: int) -> str:
        """Return the assistant's text content for the given prompt.

        Implementations should raise a
        :class:`server.translation.errors.TranslationError` (or a subclass)
        for timeout, overload or other backend failures.
        """
        ...
