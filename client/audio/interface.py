"""Backend-agnostic audio capture interfaces.

These Protocols let the capture pipeline run against either the real Windows
``pyaudiowpatch`` backend or a deterministic fake backend on Linux. The
callback signature intentionally carries only raw bytes and a capture
timestamp; sequence assignment and enqueue happen in the capture context.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from client.audio.types import AudioFormat, CaptureEvent, DeviceInfo
from shared.protocol.enums import StreamSource


class OnChunkCallable(Protocol):
    def __call__(self, data: bytes, capture_timestamp_ms: int, /) -> None: ...


class OnEventCallable(Protocol):
    def __call__(self, event: CaptureEvent, /) -> None: ...


@runtime_checkable
class BackendStream(Protocol):
    """A single, source-specific capture stream."""

    @property
    def audio_format(self) -> AudioFormat: ...

    def start(self) -> None: ...

    def stop(self) -> None: ...

    def close(self) -> None: ...


@runtime_checkable
class AudioBackend(Protocol):
    """Enumerates devices and opens independent capture streams."""

    def list_input_devices(self) -> list[DeviceInfo]: ...

    def list_loopback_devices(self) -> list[DeviceInfo]: ...

    def open_stream(
        self,
        *,
        device_index: int,
        source: StreamSource,
        on_chunk: OnChunkCallable,
        on_event: OnEventCallable | None = None,
        frames_per_buffer: int = 1024,
    ) -> BackendStream: ...
