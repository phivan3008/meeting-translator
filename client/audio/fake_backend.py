"""Deterministic fake audio backend for Linux tests and local smoke runs.

Produces reproducible PCM S16LE data without any audio hardware. Tests drive
chunk delivery explicitly via :meth:`FakeBackendStream.emit_chunk` /
:meth:`FakeBackendStream.emit_sine`, and can simulate device loss and
reconfiguration through :meth:`FakeBackendStream.simulate_device_lost` /
:meth:`FakeBackendStream.simulate_device_reconfigured`.
"""

from __future__ import annotations

import math

import numpy as np

from client.audio.interface import OnChunkCallable, OnEventCallable
from client.audio.types import (
    AudioFormat,
    CaptureEvent,
    CaptureEventType,
    DeviceInfo,
)
from shared.protocol.enums import StreamSource

_S16LE = np.dtype("<i2")
_INT16_MAX = 32767


class FakeBackendStream:
    """A single fake capture stream that emits data only when asked."""

    def __init__(
        self,
        *,
        source: StreamSource,
        audio_format: AudioFormat,
        on_chunk: OnChunkCallable,
        on_event: OnEventCallable | None,
    ) -> None:
        self._source = source
        self._audio_format = audio_format
        self._on_chunk = on_chunk
        self._on_event = on_event
        self._started = False
        self._timestamp_ms = 0

    @property
    def audio_format(self) -> AudioFormat:
        return self._audio_format

    @property
    def started(self) -> bool:
        return self._started

    def start(self) -> None:
        self._started = True
        self._emit_event(CaptureEventType.STARTED)

    def stop(self) -> None:
        self._started = False
        self._emit_event(CaptureEventType.STOPPED)

    def close(self) -> None:
        self._started = False

    def emit_chunk(self, data: bytes, capture_timestamp_ms: int | None = None) -> None:
        """Deliver a raw interleaved S16LE chunk to the registered callback."""
        ts = self._timestamp_ms if capture_timestamp_ms is None else capture_timestamp_ms
        self._on_chunk(data, ts)

    def emit_sine(self, *, num_samples: int, frequency_hz: float = 440.0) -> bytes:
        """Generate and deliver a deterministic interleaved sine chunk.

        Returns the raw bytes delivered so tests can assert on them.
        """
        fmt = self._audio_format
        t = np.arange(num_samples, dtype=np.float64) / fmt.sample_rate
        wave = np.sin(2.0 * math.pi * frequency_hz * t) * (_INT16_MAX * 0.5)
        mono = wave.astype(_S16LE)
        interleaved = np.repeat(mono, fmt.channels)
        data = bytes(interleaved.astype(_S16LE).tobytes())
        duration_ms = int(round(num_samples * 1000 / fmt.sample_rate))
        ts = self._timestamp_ms
        self._timestamp_ms += duration_ms
        self.emit_chunk(data, ts)
        return data

    def simulate_device_lost(self, detail: str = "device removed") -> None:
        self._emit_event(CaptureEventType.DEVICE_LOST, detail)

    def simulate_device_reconfigured(self, detail: str = "format changed") -> None:
        self._emit_event(CaptureEventType.DEVICE_RECONFIGURED, detail)

    def _emit_event(self, event_type: CaptureEventType, detail: str = "") -> None:
        if self._on_event is not None:
            self._on_event(CaptureEvent(type=event_type, source=self._source, detail=detail))


class FakeAudioBackend:
    """A fake :class:`AudioBackend` with configurable devices."""

    def __init__(
        self,
        *,
        input_devices: list[DeviceInfo] | None = None,
        loopback_devices: list[DeviceInfo] | None = None,
        input_format: AudioFormat | None = None,
        loopback_format: AudioFormat | None = None,
    ) -> None:
        self._input_devices = input_devices or [
            DeviceInfo(
                index=0,
                name="Fake Microphone",
                max_input_channels=1,
                default_sample_rate=48000,
                is_loopback=False,
                host_api="fake",
            )
        ]
        self._loopback_devices = loopback_devices or [
            DeviceInfo(
                index=1,
                name="Fake Loopback",
                max_input_channels=2,
                default_sample_rate=48000,
                is_loopback=True,
                host_api="fake-wasapi",
            )
        ]
        self._input_format = input_format or AudioFormat(sample_rate=48000, channels=1)
        self._loopback_format = loopback_format or AudioFormat(sample_rate=48000, channels=2)
        self.opened_streams: list[FakeBackendStream] = []

    def list_input_devices(self) -> list[DeviceInfo]:
        return list(self._input_devices)

    def list_loopback_devices(self) -> list[DeviceInfo]:
        return list(self._loopback_devices)

    def open_stream(
        self,
        *,
        device_index: int,
        source: StreamSource,
        on_chunk: OnChunkCallable,
        on_event: OnEventCallable | None = None,
        frames_per_buffer: int = 1024,
    ) -> FakeBackendStream:
        audio_format = (
            self._loopback_format if source is StreamSource.LOOPBACK else self._input_format
        )
        stream = FakeBackendStream(
            source=source,
            audio_format=audio_format,
            on_chunk=on_chunk,
            on_event=on_event,
        )
        self.opened_streams.append(stream)
        return stream
