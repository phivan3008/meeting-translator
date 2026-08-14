"""Optional low-priority semantic-completeness classification via vLLM.

Matches docs/TRANSLATION.md's "Completeness request": a strict-timeout,
small-token-limit JSON-only classification asking whether a soft-silence
candidate sentence is semantically complete. This is a distinct request
type from translation (different prompt, schema and priority -- see
``server.translation.queue.TranslationPriority.COMPLETENESS``) but reuses
the same :class:`~server.translation.interface.TranslationClient` protocol
and backend, per docs/ARCHITECTURE.md ("Translation and completeness share
vLLM but use distinct priorities").

Never raises: any failure (timeout, backend error, invalid JSON or schema
mismatch) is reported as an "unknown" outcome so the caller can apply its
own deterministic heuristic fallback, per docs/TRANSLATION.md ("Invalid
JSON, timeout or overload means `unknown`, followed by VAD/heuristic
fallback").
"""

from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass

from server.translation.errors import TranslationError
from server.translation.interface import TranslationClient
from server.translation.prompts import build_completeness_prompt
from shared.protocol.enums import Language

# The completeness prompt template (server.translation.prompts) already
# contains the schema and "Do not explain" instruction as the user content;
# this fixed system prompt reinforces JSON-only output at the message level.
_SYSTEM_PROMPT = (
    "You are a strict JSON-only classifier. Output only valid JSON matching "
    "the requested schema, with no extra text, explanation or markdown."
)

_JSON_OBJECT_RE = re.compile(r"\{.*\}", re.DOTALL)


@dataclass(frozen=True)
class CompletenessOutcome:
    """Result of one completeness classification attempt.

    ``complete`` is ``None`` when the result is unknown (timeout, invalid
    JSON/schema, or backend overload/failure) -- callers must fall back to
    a deterministic heuristic decision in that case.
    """

    complete: bool | None
    confidence: float | None
    issue: str | None = None


def _parse_completeness_json(raw: str) -> tuple[bool, float] | None:
    """Parse the model's response into ``(complete, confidence)``, if valid.

    Tries a direct ``json.loads`` first; if the model wrapped the object in
    extra text or markdown fences despite instructions, falls back to
    extracting the first ``{...}`` substring once. Returns ``None`` for any
    malformed or schema-mismatched payload.
    """
    text = raw.strip()
    payload = None
    try:
        payload = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        match = _JSON_OBJECT_RE.search(text)
        if match is not None:
            try:
                payload = json.loads(match.group(0))
            except (json.JSONDecodeError, ValueError):
                return None
    if not isinstance(payload, dict):
        return None
    complete = payload.get("complete")
    confidence = payload.get("confidence")
    if not isinstance(complete, bool):
        return None
    if isinstance(confidence, bool) or not isinstance(confidence, int | float):
        return None
    return complete, float(confidence)


class CompletenessClassifier:
    """Runs the optional low-priority semantic-completeness check via vLLM.

    Bounded by a strict timeout (``timeout_ms``) and a very small
    ``max_tokens``, per docs/TRANSLATION.md ("Use a very small token limit
    and strict timeout").
    """

    def __init__(self, client: TranslationClient, *, timeout_ms: int, max_tokens: int) -> None:
        if timeout_ms < 1:
            raise ValueError("timeout_ms must be >= 1")
        if max_tokens < 1:
            raise ValueError("max_tokens must be >= 1")
        self._client = client
        self._timeout_s = timeout_ms / 1000.0
        self._max_tokens = max_tokens

    async def classify(self, *, language: Language, sentence: str) -> CompletenessOutcome:
        """Classify whether ``sentence`` is a semantically complete utterance."""
        user_content = build_completeness_prompt(language=language, sentence=sentence)
        try:
            raw = await asyncio.wait_for(
                self._client.complete_chat(
                    system_prompt=_SYSTEM_PROMPT,
                    user_content=user_content,
                    max_tokens=self._max_tokens,
                ),
                timeout=self._timeout_s,
            )
        except TimeoutError:
            return CompletenessOutcome(complete=None, confidence=None, issue="timeout")
        except TranslationError as exc:
            return CompletenessOutcome(complete=None, confidence=None, issue=exc.kind.value)

        parsed = _parse_completeness_json(raw)
        if parsed is None:
            return CompletenessOutcome(complete=None, confidence=None, issue="invalid_json")
        complete, confidence = parsed
        return CompletenessOutcome(complete=complete, confidence=confidence, issue=None)
