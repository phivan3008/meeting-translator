"""End-to-end capture tests using the deterministic fake backend (Linux-safe)."""

from __future__ import annotations

import numpy as np

from client.audio.capture import CaptureContext
from client.audio.fake_backend import FakeAudioBackend
from client.audio.types import (
    FRAME_BYTES,
    AudioFormat,
    CaptureEvent,
    CaptureEventType,
    DropPolicy,
)
from shared.protocol.enums import StreamSource

_S16LE = np.dtype("<i2")


def _make_context(source: StreamSource, fmt: AudioFormat, **kwargs: object) -> CaptureContext:
    return CaptureContext(
        stream_number=1 if source is StreamSource.MICROPHONE else 2,
        source=source,
        source_format=fmt,
        **kwargs,  # type: ignore[arg-type]
    )


def test_callback_only_enqueues_no_frames_until_processed() -> None:
    fmt = AudioFormat(sample_rate=16000, channels=1)
    ctx = _make_context(StreamSource.MICROPHONE, fmt)
    data = np.zeros(320, dtype=_S16LE).tobytes()  # one 20 ms frame at 16k mono
    ctx.on_raw_chunk(data, capture_timestamp_ms=100)
    # No conversion happened in the callback.
    assert ctx.frames_produced == 0
    assert ctx.queue_depth == 1
    frames = ctx.process_available()
    assert len(frames) == 1
    assert len(frames[0].pcm) == FRAME_BYTES
    assert frames[0].sequence_number == 0
    assert frames[0].stream_number == 1
    assert ctx.queue_depth == 0


def test_frame_sequence_numbers_increment() -> None:
    fmt = AudioFormat(sample_rate=16000, channels=1)
    ctx = _make_context(StreamSource.MICROPHONE, fmt)
    # Three 20 ms frames worth of samples in one chunk.
    data = np.zeros(320 * 3, dtype=_S16LE).tobytes()
    ctx.on_raw_chunk(data, 0)
    frames = ctx.process_available()
    assert [f.sequence_number for f in frames] == [0, 1, 2]


def test_mic_and_loopback_contexts_are_independent() -> None:
    backend = FakeAudioBackend()
    mic_events: list[CaptureEvent] = []
    loop_events: list[CaptureEvent] = []

    mic_ctx = _make_context(
        StreamSource.MICROPHONE,
        AudioFormat(sample_rate=48000, channels=1),
        on_event=mic_events.append,
    )
    loop_ctx = _make_context(
        StreamSource.LOOPBACK,
        AudioFormat(sample_rate=48000, channels=2),
        on_event=loop_events.append,
    )

    mic_stream = backend.open_stream(
        device_index=0,
        source=StreamSource.MICROPHONE,
        on_chunk=mic_ctx.on_raw_chunk,
        on_event=mic_events.append,
    )
    loop_stream = backend.open_stream(
        device_index=1,
        source=StreamSource.LOOPBACK,
        on_chunk=loop_ctx.on_raw_chunk,
        on_event=loop_events.append,
    )

    # Only microphone receives data; loopback must remain empty (no mixing).
    mic_stream.emit_sine(num_samples=4800)  # 100 ms at 48k
    mic_frames = mic_ctx.process_available()
    loop_frames = loop_ctx.process_available()

    assert len(mic_frames) > 0
    assert all(f.stream_number == 1 for f in mic_frames)
    assert len(loop_frames) == 0
    assert loop_ctx.frames_produced == 0

    # Now drive loopback independently.
    loop_stream.emit_sine(num_samples=4800)
    loop_frames2 = loop_ctx.process_available()
    assert len(loop_frames2) > 0
    assert all(f.stream_number == 2 for f in loop_frames2)


def test_overflow_emits_event_and_counts_drops() -> None:
    fmt = AudioFormat(sample_rate=16000, channels=1)
    events: list[CaptureEvent] = []
    ctx = _make_context(
        StreamSource.MICROPHONE,
        fmt,
        queue_maxsize=2,
        drop_policy=DropPolicy.DROP_NEWEST,
        on_event=events.append,
    )
    chunk = np.zeros(320, dtype=_S16LE).tobytes()
    for i in range(5):
        ctx.on_raw_chunk(chunk, i)
    assert ctx.chunks_dropped == 3
    assert ctx.overflow_events == 3
    assert any(e.type is CaptureEventType.OVERFLOW for e in events)


def test_device_loss_and_reconfigure_signals_propagate() -> None:
    backend = FakeAudioBackend()
    events: list[CaptureEvent] = []
    stream = backend.open_stream(
        device_index=0,
        source=StreamSource.MICROPHONE,
        on_chunk=lambda data, ts: None,
        on_event=events.append,
    )
    stream.start()
    stream.simulate_device_lost()
    stream.simulate_device_reconfigured()
    stream.stop()

    types = [e.type for e in events]
    assert CaptureEventType.STARTED in types
    assert CaptureEventType.DEVICE_LOST in types
    assert CaptureEventType.DEVICE_RECONFIGURED in types
    assert CaptureEventType.STOPPED in types
    assert all(e.source is StreamSource.MICROPHONE for e in events)


def test_backend_lists_distinct_device_sets() -> None:
    backend = FakeAudioBackend()
    inputs = backend.list_input_devices()
    loopbacks = backend.list_loopback_devices()
    assert all(not d.is_loopback for d in inputs)
    assert all(d.is_loopback for d in loopbacks)
    assert {d.index for d in inputs}.isdisjoint({d.index for d in loopbacks})
