"""Measure real pipeline latency and report p50/p95/p99.

Usage:

    python scripts/latency_report.py [--count N] [--real-backends]
        [--fake-asr-delay-ms MS] [--fake-translation-delay-ms MS] [--json]

Feeds ``--count`` synthetic utterances through a real
``UtteranceOrchestrator`` (server.orchestration.pipeline) with frames paced
at real 20ms intervals -- matching how a live meeting actually streams
audio -- and reports the ACTUAL measured p50/p95/p99 latency for three of
the five objectives in ``docs/PRODUCT_REQUIREMENTS.md`` section 5:

- ``first_partial_ms``: wall time from the first speech frame of an
  utterance to its first published ``transcription.partial`` event
  (-> "First partial p95").
- ``asr_final_ms``: taken directly from ``UtteranceFinal.latency.asr_final_ms``,
  which ``server.asr.worker.FinalTranscriber.finalize`` already computes
  precisely around the real decode call (-> "Final ASR p95").
- ``end_to_end_ms``: wall time from the first speech frame to the published
  ``utterance.final`` event (-> "End-to-end final p95").
- ``translation_ms_approx``: ``end_to_end_ms - asr_final_ms``, an
  approximation (not a separately isolated measurement -- it also includes
  the VAD/heuristic finalization-decision gap) reported for visibility
  against "Translation p95", labeled ``_approx`` so it is not mistaken for
  a precise figure.

Numbers are always real measurements of this specific run -- this tool
never hard-codes or asserts a pass/fail verdict against the documented
objectives; comparing the printed numbers to them is left to the reader,
per this phase's own required outcome ("without hard-coded success").

By default this runs against ``ScriptedAsrModel``/``ScriptedTranslationClient``
(no GPU required), so the tool itself can be smoke-tested locally. Against
fakes, ASR/translation compute time is near-zero unless
``--fake-asr-delay-ms``/``--fake-translation-delay-ms`` inject an artificial
delay -- so a default local run characterizes orchestration/VAD-pacing
overhead only, **not** real model inference latency. "VAD speech-start
p95" is deliberately not reported: isolating it precisely needs deeper
pipeline instrumentation than this tool's black-box event-timestamping
approach provides (see the module docstring in
``server/orchestration/pipeline.py`` for the VAD event flow).

Pass ``--real-backends`` to measure genuine GPU-backed latency (requires
the ``gpu`` extra installed and a reachable vLLM server). Run this manually
on/near the GPU host -- see the staged action for this in
``MANUAL_ACTIONS.md`` -- never run automatically and never claim these are
real hardware numbers unless ``--real-backends`` was actually used on real
hardware.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server.asr.fake import ScriptedAsrModel  # noqa: E402
from server.asr.types import AsrConfig, TranscriptionResult  # noqa: E402
from server.orchestration.heuristics import HeuristicConfig  # noqa: E402
from server.orchestration.pipeline import UtteranceOrchestrator  # noqa: E402
from server.orchestration.types import CompletenessConfig  # noqa: E402
from server.translation.fake import ScriptedTranslationClient  # noqa: E402
from server.translation.types import TranslationConfig  # noqa: E402
from server.vad.types import VadConfig  # noqa: E402
from shared.protocol.enums import Language, StreamSource  # noqa: E402
from shared.protocol.messages import TranscriptionPartial, UtteranceFinal  # noqa: E402
from shared.settings import Settings  # noqa: E402

FRAME_MS = 20
FRAME_BYTES = FRAME_MS * 32
SPEECH = bytes([1]) * FRAME_BYTES
SILENCE = bytes([0]) * FRAME_BYTES

VAD_CONFIG = VadConfig(
    threshold=0.5,
    speech_start_ms=160,
    min_speech_ms=250,
    soft_silence_ms=450,
    hard_silence_ms=900,
    speech_pad_before_ms=200,
    speech_pad_after_ms=250,
    max_utterance_ms=15000,
)


class _DelayedFakeAsrModel:
    """Wraps ``ScriptedAsrModel`` with an artificial per-call delay.

    Runs the (fast, synchronous) scripted decode inside the same
    thread-pool-executor path a real model would use
    (``FinalTranscriber``/``PartialTranscriber`` both run decoding via
    ``loop.run_in_executor``), then sleeps -- so this exercises the same
    executor plumbing a real GPU adapter would, not just a bare
    ``time.sleep`` inline on the calling thread.
    """

    def __init__(self, inner: ScriptedAsrModel, *, delay_s: float) -> None:
        self._inner = inner
        self._delay_s = delay_s

    def transcribe(self, request: object) -> TranscriptionResult:
        if self._delay_s > 0:
            time.sleep(self._delay_s)
        return self._inner.transcribe(request)  # type: ignore[arg-type]


class _DelayedFakeTranslationClient:
    """Wraps ``ScriptedTranslationClient`` with an artificial async delay."""

    def __init__(self, inner: ScriptedTranslationClient, *, delay_s: float) -> None:
        self._inner = inner
        self._delay_s = delay_s

    async def complete_chat(self, *, system_prompt: str, user_content: str, max_tokens: int) -> str:
        if self._delay_s > 0:
            await asyncio.sleep(self._delay_s)
        return await self._inner.complete_chat(
            system_prompt=system_prompt, user_content=user_content, max_tokens=max_tokens
        )


def _percentile(sorted_values: list[float], pct: float) -> float:
    """Linear-interpolation percentile (pct in [0, 100]) of an already-sorted list."""
    if not sorted_values:
        return float("nan")
    if len(sorted_values) == 1:
        return sorted_values[0]
    rank = (pct / 100.0) * (len(sorted_values) - 1)
    lower = int(rank)
    upper = min(lower + 1, len(sorted_values) - 1)
    fraction = rank - lower
    return sorted_values[lower] + (sorted_values[upper] - sorted_values[lower]) * fraction


def _summarize(name: str, samples: list[float]) -> dict[str, object]:
    ordered = sorted(samples)
    return {
        "metric": name,
        "count": len(ordered),
        "p50_ms": round(_percentile(ordered, 50), 1),
        "p95_ms": round(_percentile(ordered, 95), 1),
        "p99_ms": round(_percentile(ordered, 99), 1),
        "min_ms": round(ordered[0], 1) if ordered else None,
        "max_ms": round(ordered[-1], 1) if ordered else None,
    }


async def _run(
    *, count: int, real_backends: bool, fake_asr_delay_ms: float, fake_translation_delay_ms: float
) -> dict[str, list[float]]:
    if real_backends:
        from server.asr.whisper import WhisperAsrModel
        from server.translation.client import VllmTranslationClient

        settings = Settings()
        asr_config = AsrConfig.from_settings(settings)
        translation_config = TranslationConfig.from_settings(settings)
        asr_model: object = WhisperAsrModel(asr_config)
        translation_client: object = VllmTranslationClient(translation_config)
    else:
        asr_config = AsrConfig(model="large-v3", device="cpu", compute_type="int8")
        translation_config = TranslationConfig(
            base_url="http://vllm.local/v1", model="qwen3.6-27b-translate", timeout_ms=3000
        )
        scripted_asr = ScriptedAsrModel(
            [
                TranscriptionResult(
                    text="テストです。", language=Language.JAPANESE, duration_ms=400
                )
                for _ in range(count)
            ]
        )
        scripted_translation = ScriptedTranslationClient(
            ["Đây là một bài kiểm tra." for _ in range(count)]
        )
        asr_model = _DelayedFakeAsrModel(scripted_asr, delay_s=fake_asr_delay_ms / 1000.0)
        translation_client = _DelayedFakeTranslationClient(
            scripted_translation, delay_s=fake_translation_delay_ms / 1000.0
        )

    speech_begin_by_utterance: dict[str, float] = {}
    first_partial_ms: list[float] = []
    asr_final_ms: list[float] = []
    end_to_end_ms: list[float] = []
    seen_first_partial: set[str] = set()

    async def publish(event: object) -> None:
        now = time.monotonic()
        if isinstance(event, TranscriptionPartial):
            if event.utterance_id in seen_first_partial:
                return
            begin = speech_begin_by_utterance.get(event.utterance_id)
            if begin is not None:
                seen_first_partial.add(event.utterance_id)
                first_partial_ms.append((now - begin) * 1000.0)
        elif isinstance(event, UtteranceFinal):
            begin = speech_begin_by_utterance.get(event.utterance_id)
            if begin is not None:
                end_to_end_ms.append((now - begin) * 1000.0)
            if event.latency is not None and event.latency.asr_final_ms is not None:
                asr_final_ms.append(float(event.latency.asr_final_ms))

    orchestrator = UtteranceOrchestrator(
        session_id="latency-report",
        vad_config=VAD_CONFIG,
        frame_ms=FRAME_MS,
        asr_config=asr_config,
        asr_model=asr_model,  # type: ignore[arg-type]
        translation_config=translation_config,
        translation_client=translation_client,  # type: ignore[arg-type]
        publish=publish,
        heuristic_config=HeuristicConfig(),
        completeness_config=CompletenessConfig(enabled=False),
        partial_interval_ms=500,
    )
    orchestrator.add_stream(
        "mic-01",
        source=StreamSource.MICROPHONE,
        source_language=Language.JAPANESE,
        target_language=Language.VIETNAMESE,
    )

    try:
        now_ms = 0
        for utterance_index in range(count):
            speech_frames = 20  # 400ms of speech, comfortably above min_speech_ms
            silence_frames = 50  # 1000ms silence, comfortably above hard_silence_ms
            for frame_index in range(speech_frames):
                if frame_index == 0:
                    utterance_key = f"mic-01-{utterance_index + 1:05d}"
                    speech_begin_by_utterance[utterance_key] = time.monotonic()
                await orchestrator.ingest_frame("mic-01", SPEECH, 0.9)
                await asyncio.sleep(FRAME_MS / 1000.0)
                now_ms += FRAME_MS
                await orchestrator.run_due_partial_decodes(now_ms=now_ms)
            for _ in range(silence_frames):
                await orchestrator.ingest_frame("mic-01", SILENCE, 0.05)
                await asyncio.sleep(FRAME_MS / 1000.0)
                now_ms += FRAME_MS
                await orchestrator.run_due_partial_decodes(now_ms=now_ms)
        await orchestrator.wait_idle()
    finally:
        orchestrator.close()
        if real_backends:
            await translation_client.aclose()  # type: ignore[attr-defined]

    translation_ms_approx = [
        e2e - asr for e2e, asr in zip(end_to_end_ms, asr_final_ms, strict=False) if e2e >= asr
    ]

    return {
        "first_partial_ms": first_partial_ms,
        "asr_final_ms": asr_final_ms,
        "end_to_end_ms": end_to_end_ms,
        "translation_ms_approx": translation_ms_approx,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--count", type=int, default=20, help="Number of synthetic utterances.")
    parser.add_argument(
        "--real-backends",
        action="store_true",
        help="Use real WhisperAsrModel + VllmTranslationClient (requires GPU host/vLLM).",
    )
    parser.add_argument(
        "--fake-asr-delay-ms", type=float, default=0.0, help="Artificial delay per fake ASR call."
    )
    parser.add_argument(
        "--fake-translation-delay-ms",
        type=float,
        default=0.0,
        help="Artificial delay per fake translation call.",
    )
    parser.add_argument("--json", action="store_true", help="Print JSON instead of a table.")
    args = parser.parse_args(argv)

    if args.count < 1:
        parser.error("--count must be >= 1")

    samples = asyncio.run(
        _run(
            count=args.count,
            real_backends=args.real_backends,
            fake_asr_delay_ms=args.fake_asr_delay_ms,
            fake_translation_delay_ms=args.fake_translation_delay_ms,
        )
    )
    summaries = [_summarize(name, values) for name, values in samples.items()]

    if args.json:
        print(json.dumps({"real_backends": args.real_backends, "metrics": summaries}, indent=2))
        return 0

    mode = "REAL backends (GPU/vLLM)" if args.real_backends else "fake backends (local smoke test)"
    print(f"Latency report -- {args.count} synthetic utterances, {mode}\n")
    header = (
        f"{'metric':<24}{'count':>7}{'p50_ms':>10}{'p95_ms':>10}"
        f"{'p99_ms':>10}{'min_ms':>10}{'max_ms':>10}"
    )
    print(header)
    print("-" * len(header))
    for row in summaries:
        print(
            f"{row['metric']:<24}{row['count']:>7}{row['p50_ms']:>10}{row['p95_ms']:>10}"
            f"{row['p99_ms']:>10}{row['min_ms']:>10}{row['max_ms']:>10}"
        )
    print(
        "\nCompare against docs/PRODUCT_REQUIREMENTS.md section 5's objectives "
        "manually -- this tool does not assert pass/fail."
    )
    if not args.real_backends:
        print(
            "NOTE: fake-backend run -- these numbers characterize orchestration/VAD-pacing "
            "overhead only, not real model inference latency. Use --real-backends on the "
            "GPU host for genuine numbers."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
