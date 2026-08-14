"""Final transcription service.

Runs ASR inference on completed utterance audio off the asyncio event loop using
a dedicated executor, enforces a time budget, maps failures to typed errors, and
reconciles the result into a protocol ``utterance.final`` event.

Translation is intentionally out of scope for this phase: the produced event
carries the transcription with ``translation=None`` and a ``pending`` status.
"""

from __future__ import annotations

import asyncio
import time
from concurrent.futures import Executor, ThreadPoolExecutor
from datetime import UTC, datetime

from server.asr.errors import (
    AsrCircuitOpenError,
    AsrError,
    AsrTimeoutError,
    classify_backend_error,
)
from server.asr.interface import AsrModel
from server.asr.types import AsrConfig, AsrRequest, TranscriptionResult
from server.observability.metrics import Metrics
from server.reliability.circuit_breaker import CircuitBreaker, circuit_state_value
from server.vad.types import Utterance
from shared.protocol.enums import Language, TranslationStatus
from shared.protocol.messages import ErrorEvent, LatencyInfo, UtteranceFinal


def _now() -> datetime:
    return datetime.now(UTC)


class FinalTranscriber:
    """Orchestrates final ASR for completed utterances.

    Inference runs in a dedicated single-worker executor so decoding never
    blocks the event loop and final requests are serialized (final ASR has
    priority per ``docs/ARCHITECTURE.md``).
    """

    def __init__(
        self,
        model: AsrModel,
        config: AsrConfig,
        *,
        timeout_ms: int,
        executor: Executor | None = None,
        circuit_breaker: CircuitBreaker | None = None,
        metrics: Metrics | None = None,
        backend_name: str = "asr",
    ) -> None:
        if timeout_ms < 1:
            raise ValueError("timeout_ms must be >= 1")
        self._model = model
        self._config = config
        self._timeout_s = timeout_ms / 1000.0
        self._owns_executor = executor is None
        self._executor: Executor = executor or ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="asr-final"
        )
        self._circuit_breaker = circuit_breaker
        self._metrics = metrics
        self._backend_name = backend_name

    async def transcribe(self, request: AsrRequest) -> TranscriptionResult:
        """Run a single decode request with the configured timeout."""
        if self._circuit_breaker is not None:
            self._record_circuit_state()
            if not self._circuit_breaker.allow_request():
                raise AsrCircuitOpenError("ASR circuit breaker open; request skipped")

        loop = asyncio.get_running_loop()
        started = time.monotonic()
        future = loop.run_in_executor(self._executor, self._model.transcribe, request)
        try:
            result = await asyncio.wait_for(future, timeout=self._timeout_s)
        except TimeoutError as exc:
            self._record_failure()
            raise AsrTimeoutError("final ASR timed out") from exc
        except AsrError:
            self._record_failure()
            raise
        except Exception as exc:
            self._record_failure()
            raise classify_backend_error(exc) from exc
        else:
            self._record_success(elapsed_s=time.monotonic() - started)
            return result

    def _record_success(self, *, elapsed_s: float) -> None:
        if self._circuit_breaker is not None:
            self._circuit_breaker.record_success()
            self._record_circuit_state()
        if self._metrics is not None:
            self._metrics.asr_latency_seconds.labels(stage="final").observe(elapsed_s)

    def _record_failure(self) -> None:
        if self._circuit_breaker is not None:
            self._circuit_breaker.record_failure()
            self._record_circuit_state()

    def _record_circuit_state(self) -> None:
        if self._metrics is not None and self._circuit_breaker is not None:
            self._metrics.circuit_breaker_state.labels(backend=self._backend_name).set(
                circuit_state_value(self._circuit_breaker.state)
            )

    async def transcribe_utterance(
        self,
        utterance: Utterance,
        *,
        source_language: Language,
        previous_text: str | None = None,
    ) -> TranscriptionResult:
        """Decode a completed utterance's audio (final reconciliation)."""
        request = AsrRequest(
            audio=utterance.audio,
            language=source_language,
            beam_size=self._config.final_beam_size,
            temperature=self._config.temperature,
            condition_on_previous_text=self._config.condition_on_previous_text,
            previous_text=previous_text,
        )
        return await self.transcribe(request)

    async def finalize(
        self,
        utterance: Utterance,
        *,
        session_id: str,
        stream_id: str,
        source_language: Language,
        target_language: Language,
        previous_text: str | None = None,
        revision: int = 0,
    ) -> UtteranceFinal:
        """Transcribe an utterance and build its ``utterance.final`` event.

        The event contains no translation yet: ``translation`` is ``None`` and
        ``translation_status`` is ``pending`` (translation is added in a later
        phase).
        """
        started = time.monotonic()
        result = await self.transcribe_utterance(
            utterance, source_language=source_language, previous_text=previous_text
        )
        asr_final_ms = int((time.monotonic() - started) * 1000)
        return UtteranceFinal(
            session_id=session_id,
            stream_id=stream_id,
            utterance_id=utterance.utterance_id,
            revision=revision,
            source=utterance.source,
            source_language=source_language,
            target_language=target_language,
            transcription=result.text,
            translation=None,
            translation_status=TranslationStatus.PENDING,
            start_ms=utterance.start_ms,
            end_ms=utterance.end_ms,
            final_reason=utterance.final_reason,
            latency=LatencyInfo(asr_final_ms=asr_final_ms),
            timestamp=_now(),
        )

    def close(self) -> None:
        """Shut down the owned executor, if any."""
        if self._owns_executor:
            self._executor.shutdown(wait=False)


def build_asr_error_event(
    error: AsrError, *, session_id: str, utterance_id: str | None
) -> ErrorEvent:
    """Map a typed :class:`AsrError` to a protocol ``error`` event."""
    return ErrorEvent(
        session_id=session_id,
        code=error.error_code,
        message=error.message,
        retryable=error.retryable,
        utterance_id=utterance_id,
        timestamp=_now(),
    )
