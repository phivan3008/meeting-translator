"""Deterministic translation test double.

``ScriptedTranslationClient`` returns pre-programmed text (or raises
pre-programmed errors) in sequence, records the requests it received, and is
fully async-compatible without any real HTTP call. Used for CPU tests of the
final translation service.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from server.translation.errors import TranslationError


@dataclass(frozen=True)
class RecordedChatCall:
    """One recorded call to :meth:`ScriptedTranslationClient.complete_chat`."""

    system_prompt: str
    user_content: str
    max_tokens: int


class ScriptedTranslationClient:
    """Return scripted text/errors per :meth:`complete_chat` call."""

    def __init__(self, outcomes: Sequence[str | TranslationError]) -> None:
        if not outcomes:
            raise ValueError("outcomes must be non-empty")
        self._outcomes: list[str | TranslationError] = list(outcomes)
        self._index = 0
        self.calls: list[RecordedChatCall] = []

    async def complete_chat(self, *, system_prompt: str, user_content: str, max_tokens: int) -> str:
        self.calls.append(
            RecordedChatCall(
                system_prompt=system_prompt, user_content=user_content, max_tokens=max_tokens
            )
        )
        outcome = self._outcomes[min(self._index, len(self._outcomes) - 1)]
        self._index += 1
        if isinstance(outcome, TranslationError):
            raise outcome
        return outcome

    @property
    def call_count(self) -> int:
        return len(self.calls)
