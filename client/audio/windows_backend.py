"""Windows WASAPI capture backend using PyAudioWPatch.

``pyaudiowpatch`` is imported lazily inside methods so this module can be
imported on Linux (for tooling/type-checking) without the package installed.
It is only exercised on Windows under the ``windows_audio`` test marker and via
the diagnostic CLI.

The audio callback does the minimum required work: it computes a capture
timestamp and forwards the raw bytes. Sequence assignment, bounded enqueue and
all conversion happen in :class:`client.audio.capture.CaptureContext`.

Microphone and loopback are always opened as separate streams and never mixed.
sounddevice is intentionally not used.
"""

from __future__ import annotations

import time
from typing import Any

from client.audio.interface import OnChunkCallable, OnEventCallable
from client.audio.types import AudioFormat, DeviceInfo
from shared.protocol.enums import StreamSource


def _import_pyaudio() -> Any:
    """Import ``pyaudiowpatch`` lazily, raising a clear error if missing."""
    try:
        import pyaudiowpatch as pyaudio  # noqa: PLC0415
    except ImportError as exc:  # pragma: no cover - environment dependent
        raise RuntimeError(
            "pyaudiowpatch is required for Windows audio capture. "
            'Install it with: pip install -e ".[windows-audio]"'
        ) from exc
    return pyaudio


class PyAudioWPatchStream:
    """A single PyAudioWPatch input stream (microphone or loopback)."""

    def __init__(
        self,
        *,
        pyaudio_module: Any,
        pyaudio_instance: Any,
        source: StreamSource,
        device_info: dict[str, Any],
        on_chunk: OnChunkCallable,
        on_event: OnEventCallable | None,
        frames_per_buffer: int,
    ) -> None:
        self._pa = pyaudio_module
        self._instance = pyaudio_instance
        self._source = source
        self._on_chunk = on_chunk
        self._on_event = on_event
        channels = int(device_info["maxInputChannels"]) or 1
        sample_rate = int(device_info["defaultSampleRate"])
        self._audio_format = AudioFormat(sample_rate=sample_rate, channels=channels)
        self._stream = pyaudio_instance.open(
            format=pyaudio_module.paInt16,
            channels=channels,
            rate=sample_rate,
            frames_per_buffer=frames_per_buffer,
            input=True,
            input_device_index=int(device_info["index"]),
            stream_callback=self._callback,
            start=False,
        )

    @property
    def audio_format(self) -> AudioFormat:
        return self._audio_format

    def _callback(
        self,
        in_data: bytes | None,
        frame_count: int,
        time_info: dict[str, float],
        status: int,
    ) -> tuple[bytes | None, int]:
        # Real-time context: timestamp + forward only. No heavy work here.
        if in_data:
            self._on_chunk(in_data, time.monotonic_ns() // 1_000_000)
        return (None, self._pa.paContinue)

    def start(self) -> None:
        self._stream.start_stream()

    def stop(self) -> None:
        if self._stream.is_active():
            self._stream.stop_stream()

    def close(self) -> None:
        self.stop()
        self._stream.close()


class PyAudioWPatchBackend:
    """Enumerates WASAPI devices and opens independent capture streams."""

    def __init__(self) -> None:
        self._pa = _import_pyaudio()
        self._instance = self._pa.PyAudio()

    def list_input_devices(self) -> list[DeviceInfo]:
        """List non-loopback input (microphone) devices."""
        devices: list[DeviceInfo] = []
        for index in range(self._instance.get_device_count()):
            info = self._instance.get_device_info_by_index(index)
            if int(info.get("maxInputChannels", 0)) < 1:
                continue
            if bool(info.get("isLoopbackDevice", False)):
                continue
            devices.append(self._to_device_info(info, is_loopback=False))
        return devices

    def list_loopback_devices(self) -> list[DeviceInfo]:
        """List WASAPI loopback devices (system output captured as input)."""
        devices: list[DeviceInfo] = []
        for info in self._instance.get_loopback_device_info_generator():
            devices.append(self._to_device_info(info, is_loopback=True))
        return devices

    def open_stream(
        self,
        *,
        device_index: int,
        source: StreamSource,
        on_chunk: OnChunkCallable,
        on_event: OnEventCallable | None = None,
        frames_per_buffer: int = 1024,
    ) -> PyAudioWPatchStream:
        device_info = self._instance.get_device_info_by_index(device_index)
        return PyAudioWPatchStream(
            pyaudio_module=self._pa,
            pyaudio_instance=self._instance,
            source=source,
            device_info=device_info,
            on_chunk=on_chunk,
            on_event=on_event,
            frames_per_buffer=frames_per_buffer,
        )

    def terminate(self) -> None:
        self._instance.terminate()

    @staticmethod
    def _to_device_info(info: dict[str, Any], *, is_loopback: bool) -> DeviceInfo:
        return DeviceInfo(
            index=int(info["index"]),
            name=str(info.get("name", "")),
            max_input_channels=int(info.get("maxInputChannels", 0)),
            default_sample_rate=int(info.get("defaultSampleRate", 0)),
            is_loopback=is_loopback,
            host_api=str(info.get("hostApi", "")),
        )
