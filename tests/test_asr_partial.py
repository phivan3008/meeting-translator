"""Tests for streaming partial ASR orchestration and event publication."""

from __future__ import annotations

import asyncio
import time
from concurrent.futures import ThreadPoolExecutor

from server.asr.fake import ScriptedAsrModel
from server.asr.partial import PartialTranscriber
from server.asr.types import (
    BYTES_PER_MS,
    AsrConfig,
    AsrRequest,
    TranscriptionResult,
    TranscriptionSegment,
)
from shared.protocol.enums import Language

CONFIG = AsrConfig(
    model="large-v3",
    device="cpu",
    compute_type="int8",
    final_beam_size=3,
    partial_beam_size=1,
    temperature=0.0,
    condition_on_previous_text=True,
)


def _pcm(ms: int) -> bytes:
    return bytes(ms * BYTES_PER_MS)


def _seg(text: str, start_ms: int, end_ms: int) -> TranscriptionSegment:
    return TranscriptionSegment(text=text, start_ms=start_ms, end_ms=end_ms)


def _result(
    *segments: TranscriptionSegment, language: Language = Language.VIETNAMESE
) -> TranscriptionResult:
    text = "".join(s.text for s in segments)
    return TranscriptionResult(
        text=text, language=language, duration_ms=0, segments=tuple(segments)
    )


async def test_decode_returns_none_for_unknown_utterance() -> None:
    model = ScriptedAsrModel([_result(_seg("x", 0, 100))])
    transcriber = PartialTranscriber(model, CONFIG, overlap_ms=200)
    try:
        assert await transcriber.decode("nope") is None
    finally:
        transcriber.close()


async def test_decode_returns_none_without_audio() -> None:
    model = ScriptedAsrModel([_result(_seg("x", 0, 100))])
    transcriber = PartialTranscriber(model, CONFIG, overlap_ms=200)
    try:
        transcriber.start_utterance(
            "u1", session_id="s1", stream_id="mic-01", source_language=Language.VIETNAMESE
        )
        assert await transcriber.decode("u1") is None
    finally:
        transcriber.close()


async def test_decode_publishes_first_partial_event() -> None:
    model = ScriptedAsrModel([_result(_seg("Xin", 0, 400))])
    transcriber = PartialTranscriber(model, CONFIG, overlap_ms=200)
    try:
        transcriber.start_utterance(
            "u1",
            session_id="s1",
            stream_id="mic-01",
            source_language=Language.VIETNAMESE,
            start_ms=1000,
        )
        transcriber.append_audio("u1", _pcm(100))
        event = await transcriber.decode("u1")
    finally:
        transcriber.close()

    assert event is not None
    assert event.stable_text == ""
    assert event.unstable_text == "Xin"
    assert event.display_text == "Xin"
    assert event.revision == 1
    assert event.utterance_id == "u1"
    assert event.session_id == "s1"
    assert event.stream_id == "mic-01"
    assert event.source_language is Language.VIETNAMESE
    assert event.start_ms == 1000
    assert event.end_ms == 1100
    # The event must serialize cleanly to the JSON wire form.
    assert '"type":"transcription.partial"' in event.model_dump_json()


async def test_decode_suppresses_duplicate_publication() -> None:
    same = _result(_seg("Xin", 0, 400))
    model = ScriptedAsrModel([same, same, same])
    transcriber = PartialTranscriber(model, CONFIG, overlap_ms=200)
    try:
        transcriber.start_utterance(
            "u1", session_id="s1", stream_id="mic-01", source_language=Language.VIETNAMESE
        )
        # Enough real audio that a window trim never exceeds what is buffered.
        transcriber.append_audio("u1", _pcm(1000))

        first = await transcriber.decode("u1")
        second = await transcriber.decode("u1")
        third = await transcriber.decode("u1")
    finally:
        transcriber.close()

    assert first is not None
    assert (first.stable_text, first.unstable_text) == ("", "Xin")

    assert second is not None
    assert (second.stable_text, second.unstable_text) == ("Xin", "")
    assert second.revision == 2

    # Third decode agrees with the second (already-committed) state exactly:
    # no new content, so no new event is published.
    assert third is None


async def test_revision_strictly_increases_only_on_real_change() -> None:
    model = ScriptedAsrModel(
        [
            _result(_seg("Xin", 0, 400)),
            _result(_seg("Xin", 0, 400), _seg(" chào", 400, 800)),
        ]
    )
    transcriber = PartialTranscriber(model, CONFIG, overlap_ms=200)
    try:
        transcriber.start_utterance(
            "u1", session_id="s1", stream_id="mic-01", source_language=Language.VIETNAMESE
        )
        transcriber.append_audio("u1", _pcm(1000))
        first = await transcriber.decode("u1")
        second = await transcriber.decode("u1")
    finally:
        transcriber.close()

    assert first is not None and first.revision == 1
    assert second is not None and second.revision == 2
    assert second.revision > first.revision


async def test_previous_text_conditioning_uses_committed_text() -> None:
    model = ScriptedAsrModel(
        [
            _result(_seg("Xin", 0, 400)),
            _result(_seg("Xin", 0, 400)),
            _result(_seg("chào", 0, 400)),
        ]
    )
    transcriber = PartialTranscriber(model, CONFIG, overlap_ms=200)
    try:
        transcriber.start_utterance(
            "u1", session_id="s1", stream_id="mic-01", source_language=Language.VIETNAMESE
        )
        # Enough real audio to cover the scripted segments' end_ms (400ms),
        # so a window trim never exceeds what is actually buffered.
        transcriber.append_audio("u1", _pcm(400))
        await transcriber.decode("u1")  # no agreement yet
        await transcriber.decode("u1")  # commits "Xin"
        await transcriber.decode("u1")  # should condition on committed "Xin"
    finally:
        transcriber.close()

    last_request: AsrRequest = model.requests[-1]
    assert last_request.previous_text == "Xin"
    assert last_request.beam_size == CONFIG.partial_beam_size


async def test_stale_decode_discarded_when_utterance_stopped_mid_flight() -> None:
    class SlowModel:
        def transcribe(self, request: AsrRequest, /) -> TranscriptionResult:
            time.sleep(0.2)
            return _result(_seg("late", 0, 400))

    transcriber = PartialTranscriber(SlowModel(), CONFIG, overlap_ms=200)
    try:
        transcriber.start_utterance(
            "u1", session_id="s1", stream_id="mic-01", source_language=Language.VIETNAMESE
        )
        transcriber.append_audio("u1", _pcm(100))
        decode_task = asyncio.create_task(transcriber.decode("u1"))
        await asyncio.sleep(0.05)
        transcriber.stop_utterance("u1")
        result = await decode_task
    finally:
        transcriber.close()

    assert result is None


async def test_stale_decode_discarded_when_superseded_by_newer_decode() -> None:
    class OnceSlowModel:
        def __init__(self) -> None:
            self.calls = 0

        def transcribe(self, request: AsrRequest, /) -> TranscriptionResult:
            self.calls += 1
            if self.calls == 1:
                time.sleep(0.2)
                return _result(_seg("stale", 0, 400))
            return _result(_seg("fresh", 0, 400))

    model = OnceSlowModel()
    transcriber = PartialTranscriber(
        model, CONFIG, overlap_ms=200, executor=ThreadPoolExecutor(max_workers=2)
    )
    try:
        transcriber.start_utterance(
            "u1", session_id="s1", stream_id="mic-01", source_language=Language.VIETNAMESE
        )
        transcriber.append_audio("u1", _pcm(100))

        first_task = asyncio.create_task(transcriber.decode("u1"))
        await asyncio.sleep(0.05)
        second = await transcriber.decode("u1")
        first = await first_task
    finally:
        transcriber.close()

    assert model.calls == 2
    assert first is None  # the slow, now-superseded decode is discarded
    assert second is not None
    assert second.unstable_text == "fresh"


async def test_current_text_reflects_last_published_and_resets_on_stop() -> None:
    model = ScriptedAsrModel([_result(_seg("Xin", 0, 400))])
    transcriber = PartialTranscriber(model, CONFIG, overlap_ms=200)
    try:
        assert transcriber.current_text("unknown") == ("", "")

        transcriber.start_utterance(
            "u1", session_id="s1", stream_id="mic-01", source_language=Language.VIETNAMESE
        )
        assert transcriber.current_text("u1") == ("", "")  # no decode yet

        transcriber.append_audio("u1", _pcm(100))
        await transcriber.decode("u1")
        assert transcriber.current_text("u1") == ("", "Xin")

        transcriber.stop_utterance("u1")
        assert transcriber.current_text("u1") == ("", "")
    finally:
        transcriber.close()


async def test_lifecycle_current_revision_and_stop() -> None:
    model = ScriptedAsrModel([_result(_seg("Xin", 0, 400))])
    transcriber = PartialTranscriber(model, CONFIG, overlap_ms=200)
    try:
        transcriber.start_utterance(
            "u1", session_id="s1", stream_id="mic-01", source_language=Language.VIETNAMESE
        )
        assert transcriber.is_active("u1") is True
        assert transcriber.current_revision("u1") == 0

        transcriber.append_audio("u1", _pcm(100))
        await transcriber.decode("u1")
        assert transcriber.current_revision("u1") == 1

        transcriber.stop_utterance("u1")
        assert transcriber.is_active("u1") is False
        assert transcriber.current_revision("u1") == 0
    finally:
        transcriber.close()
