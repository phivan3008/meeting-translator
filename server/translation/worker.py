"""Final translation service: bounded concurrency, timeout, validation, retry.

Composes the prompt builders and validator around a
:class:`~server.translation.interface.TranslationClient`. Deliberately does
not modify ``server.asr.worker.FinalTranscriber`` -- ``apply_translation``
returns a *new* ``UtteranceFinal`` with the translation outcome attached, so
final ASR reconciliation stays authoritative and untouched.

Two-phase retry, matching docs/TRANSLATION.md ("never block final
transcription indefinitely" + "translation.updated after retry"):
``translate_once`` is a single bounded attempt suitable for the
``utterance.final`` publish path; a caller that does not block on the retry
can invoke ``retry`` afterward (using a corrective prompt if the failure was
a validation issue) and publish the result via ``translation.updated`` with
:func:`build_translation_updated` if it succeeds. Scheduling *when* the
retry runs (immediately, after a delay, or skipped under load) is
finalization-orchestration work for a later phase.
"""

from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime

from server.observability.metrics import Metrics
from server.reliability.circuit_breaker import CircuitBreaker, circuit_state_value
from server.translation.errors import TranslationError
from server.translation.interface import TranslationClient
from server.translation.prompts import build_system_prompt, build_user_content
from server.translation.types import TranslationConfig, TranslationOutcome, TranslationRequest
from server.translation.validator import validate_translation
from shared.protocol.enums import TranslationStatus
from shared.protocol.messages import TranslationUpdated, UtteranceFinal

# Validation failure reasons (server.translation.validator) that a corrective
# prompt can plausibly fix. Backend failures (timeout/overload/malformed
# response) are retried with the original prompt instead.
_CORRECTABLE_VALIDATION_ISSUES = frozenset(
    {
        "empty_output",
        "forbidden_prefix",
        "repetition",
        "wrong_language",
        "identifiers_not_preserved",
        "length_ratio",
    }
)


def _now() -> datetime:
    return datetime.now(UTC)


class FinalTranslator:
    """Runs one bounded, validated translation attempt per call.

    Concurrency across all in-flight attempts is bounded by a semaphore
    (``config.max_concurrency``); each individual attempt is bounded by
    ``config.timeout_ms`` via ``wait_for``. Cancellation of the caller's own
    task propagates normally (no exception is swallowed here beyond the
    typed ``TranslationError``/timeout handled below).
    """

    def __init__(
        self,
        client: TranslationClient,
        config: TranslationConfig,
        *,
        circuit_breaker: CircuitBreaker | None = None,
        metrics: Metrics | None = None,
        backend_name: str = "translation",
    ) -> None:
        self._client = client
        self._config = config
        self._semaphore = asyncio.Semaphore(config.max_concurrency)
        self._timeout_s = config.timeout_ms / 1000.0
        self._circuit_breaker = circuit_breaker
        self._metrics = metrics
        self._backend_name = backend_name

    async def translate_once(self, request: TranslationRequest) -> TranslationOutcome:
        """First, non-retried translation attempt."""
        return await self._attempt(request, corrective=False, priority="final")

    async def retry(
        self, request: TranslationRequest, *, previous_issue: str | None
    ) -> TranslationOutcome:
        """The single allowed retry.

        Uses a stricter corrective prompt when ``previous_issue`` was a
        validation failure that a corrective prompt can plausibly fix;
        otherwise retries with the original prompt (e.g. after a timeout).
        """
        corrective = previous_issue in _CORRECTABLE_VALIDATION_ISSUES
        return await self._attempt(request, corrective=corrective, priority="retry")

    async def _attempt(
        self, request: TranslationRequest, *, corrective: bool, priority: str
    ) -> TranslationOutcome:
        if self._circuit_breaker is not None:
            self._record_circuit_state()
            if not self._circuit_breaker.allow_request():
                outcome = TranslationOutcome(
                    text=None, status=TranslationStatus.FAILED, issue="circuit_open"
                )
                self._record_outcome(outcome, priority=priority, elapsed_s=None)
                return outcome

        system_prompt = build_system_prompt(
            source_language=request.source_language,
            target_language=request.target_language,
            glossary=request.glossary,
            corrective=corrective,
        )
        user_content = build_user_content(request.text, context_sentences=request.context_sentences)

        started = time.monotonic()
        async with self._semaphore:
            try:
                raw_text = await asyncio.wait_for(
                    self._client.complete_chat(
                        system_prompt=system_prompt,
                        user_content=user_content,
                        max_tokens=self._config.max_output_tokens,
                    ),
                    timeout=self._timeout_s,
                )
            except TimeoutError:
                elapsed_s = time.monotonic() - started
                if self._circuit_breaker is not None:
                    self._circuit_breaker.record_failure()
                    self._record_circuit_state()
                outcome = TranslationOutcome(
                    text=None, status=TranslationStatus.FAILED, issue="timeout"
                )
                self._record_outcome(outcome, priority=priority, elapsed_s=elapsed_s)
                return outcome
            except TranslationError as exc:
                elapsed_s = time.monotonic() - started
                if self._circuit_breaker is not None:
                    self._circuit_breaker.record_failure()
                    self._record_circuit_state()
                outcome = TranslationOutcome(
                    text=None, status=TranslationStatus.FAILED, issue=exc.kind.value
                )
                self._record_outcome(outcome, priority=priority, elapsed_s=elapsed_s)
                return outcome

        elapsed_s = time.monotonic() - started
        if self._circuit_breaker is not None:
            self._circuit_breaker.record_success()
            self._record_circuit_state()

        result = validate_translation(
            source_text=request.text,
            translated_text=raw_text,
            target_language=request.target_language,
        )
        if result.ok:
            outcome = TranslationOutcome(
                text=raw_text.strip(), status=TranslationStatus.COMPLETED, issue=None
            )
        else:
            outcome = TranslationOutcome(
                text=None, status=TranslationStatus.FAILED, issue=result.reason
            )
        self._record_outcome(outcome, priority=priority, elapsed_s=elapsed_s)
        return outcome

    def _record_circuit_state(self) -> None:
        if self._metrics is not None and self._circuit_breaker is not None:
            self._metrics.circuit_breaker_state.labels(backend=self._backend_name).set(
                circuit_state_value(self._circuit_breaker.state)
            )

    def _record_outcome(
        self, outcome: TranslationOutcome, *, priority: str, elapsed_s: float | None
    ) -> None:
        if self._metrics is None:
            return
        self._metrics.translation_requests_total.labels(
            priority=priority, status=outcome.status.value
        ).inc()
        if elapsed_s is not None:
            self._metrics.translation_latency_seconds.labels(priority=priority).observe(elapsed_s)


def apply_translation(final_event: UtteranceFinal, outcome: TranslationOutcome) -> UtteranceFinal:
    """Return a copy of ``final_event`` with the translation outcome applied.

    Does not mutate ``final_event`` or touch ``FinalTranscriber``.
    """
    return final_event.model_copy(
        update={"translation": outcome.text, "translation_status": outcome.status}
    )


def build_translation_updated(
    *, session_id: str, stream_id: str, utterance_id: str, outcome: TranslationOutcome
) -> TranslationUpdated:
    """Build a ``translation.updated`` event from a later successful retry.

    Only meaningful for a completed outcome -- a still-failed retry has
    nothing new to publish, so the caller should not emit an update.
    """
    if outcome.status is not TranslationStatus.COMPLETED or outcome.text is None:
        raise ValueError("translation.updated requires a COMPLETED outcome")
    return TranslationUpdated(
        session_id=session_id,
        stream_id=stream_id,
        utterance_id=utterance_id,
        translation=outcome.text,
        translation_status=outcome.status,
        timestamp=_now(),
    )
