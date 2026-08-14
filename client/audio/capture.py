"""Per-source capture context.

One :class:`CaptureContext` owns a bounded queue, the conversion worker state
and counters for exactly one source (microphone OR loopback). Microphone and
loopback each use a separate context; they are never mixed.

Threading model:
- ``on_raw_chunk`` runs in the audio callback context. It only assigns a
  sequence number and enqueues (non-blocking). No conversion happens here.
- ``process_available`` runs in the worker. It drains the queue, normalizes to
  mono 16 kHz PCM S16LE and packetizes into 20 ms frames.
"""

from __future__ import annotations

from client.audio.conversion import FrameAssembler, convert_to_mono_16k_s16le
from client.audio.interface import OnEventCallable
from client.audio.queue import BoundedAudioQueue
from client.audio.types import (
    AudioFormat,
    AudioFrame,
    CaptureEvent,
    CaptureEventType,
    DropPolicy,
    RawChunk,
)
from shared.protocol.enums import StreamSource


class CaptureContext:
    """Owns the conversion pipeline and counters for a single source."""

    def __init__(
        self,
        *,
        stream_number: int,
        source: StreamSource,
        source_format: AudioFormat,
        queue_maxsize: int = 256,
        drop_policy: DropPolicy = DropPolicy.DROP_OLDEST,
        on_event: OnEventCallable | None = None,
    ) -> None:
        self._stream_number = stream_number
        self._source = source
        self._source_format = source_format
        self._queue: BoundedAudioQueue[RawChunk] = BoundedAudioQueue(
            maxsize=queue_maxsize, policy=drop_policy
        )
        self._assembler = FrameAssembler()
        self._on_event = on_event
        self._raw_sequence = 0
        self._frame_sequence = 0
        self._frames_produced = 0

    # --- Introspection -------------------------------------------------------
    @property
    def stream_number(self) -> int:
        return self._stream_number

    @property
    def source(self) -> StreamSource:
        return self._source

    @property
    def source_format(self) -> AudioFormat:
        return self._source_format

    @property
    def queue_depth(self) -> int:
        return self._queue.depth

    @property
    def chunks_enqueued(self) -> int:
        return self._queue.accepted

    @property
    def chunks_dropped(self) -> int:
        return self._queue.dropped

    @property
    def overflow_events(self) -> int:
        return self._queue.overflow_events

    @property
    def frames_produced(self) -> int:
        return self._frames_produced

    # --- Producer side (callback context) ------------------------------------
    def on_raw_chunk(self, data: bytes, capture_timestamp_ms: int) -> None:
        """Enqueue a raw chunk. Safe to call from an audio callback.

        Performs only sequence assignment and a bounded, non-blocking enqueue.
        """
        chunk = RawChunk(
            sequence=self._raw_sequence,
            capture_timestamp_ms=capture_timestamp_ms,
            data=data,
            audio_format=self._source_format,
        )
        self._raw_sequence += 1
        accepted = self._queue.put(chunk)
        if not accepted:
            self._emit(CaptureEventType.OVERFLOW, "raw chunk dropped (queue full)")

    # --- Consumer side (worker context) --------------------------------------
    def process_available(self) -> list[AudioFrame]:
        """Drain the queue and return normalized 20 ms frames."""
        frames: list[AudioFrame] = []
        while True:
            chunk = self._queue.get()
            if chunk is None:
                break
            mono = convert_to_mono_16k_s16le(chunk.data, chunk.audio_format)
            for pcm in self._assembler.push(mono):
                frames.append(
                    AudioFrame(
                        stream_number=self._stream_number,
                        sequence_number=self._frame_sequence,
                        capture_timestamp_ms=chunk.capture_timestamp_ms,
                        pcm=pcm,
                    )
                )
                self._frame_sequence += 1
                self._frames_produced += 1
        return frames

    # --- Events --------------------------------------------------------------
    def signal_device_lost(self, detail: str = "") -> None:
        self._emit(CaptureEventType.DEVICE_LOST, detail)

    def signal_device_reconfigured(self, detail: str = "") -> None:
        self._emit(CaptureEventType.DEVICE_RECONFIGURED, detail)

    def signal_started(self) -> None:
        self._emit(CaptureEventType.STARTED, "")

    def signal_stopped(self) -> None:
        self._emit(CaptureEventType.STOPPED, "")

    def _emit(self, event_type: CaptureEventType, detail: str) -> None:
        if self._on_event is not None:
            self._on_event(CaptureEvent(type=event_type, source=self._source, detail=detail))
