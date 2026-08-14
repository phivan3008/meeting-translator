"""Windows-only audio integration tests.

These are marked ``windows_audio`` and are skipped unless run on Windows with
``pyaudiowpatch`` installed and audio hardware present. Run manually:

    pytest -m windows_audio

They are excluded from the default local CPU suite.
"""

from __future__ import annotations

import sys
from importlib.util import find_spec

import pytest

pytestmark = pytest.mark.windows_audio

_ON_WINDOWS = sys.platform.startswith("win")
_HAS_PYAUDIO = find_spec("pyaudiowpatch") is not None

skip_reason = "requires Windows and pyaudiowpatch"
requires_windows_audio = pytest.mark.skipif(not (_ON_WINDOWS and _HAS_PYAUDIO), reason=skip_reason)


@requires_windows_audio
def test_enumerate_devices() -> None:
    from client.audio.windows_backend import PyAudioWPatchBackend

    backend = PyAudioWPatchBackend()
    try:
        inputs = backend.list_input_devices()
        loopbacks = backend.list_loopback_devices()
        # At least one input device is expected on a real machine.
        assert isinstance(inputs, list)
        assert isinstance(loopbacks, list)
        for dev in inputs:
            assert dev.is_loopback is False
        for dev in loopbacks:
            assert dev.is_loopback is True
    finally:
        backend.terminate()


@requires_windows_audio
def test_short_microphone_capture_produces_normalized_frames() -> None:
    import time

    from client.audio.capture import CaptureContext
    from client.audio.types import FRAME_BYTES, DropPolicy
    from client.audio.windows_backend import PyAudioWPatchBackend
    from shared.protocol.enums import StreamSource

    backend = PyAudioWPatchBackend()
    try:
        devices = backend.list_input_devices()
        if not devices:
            pytest.skip("no input devices available")

        context: CaptureContext | None = None

        def on_chunk(data: bytes, ts_ms: int) -> None:
            assert context is not None
            context.on_raw_chunk(data, ts_ms)

        stream = backend.open_stream(
            device_index=devices[0].index,
            source=StreamSource.MICROPHONE,
            on_chunk=on_chunk,
            frames_per_buffer=1024,
        )
        context = CaptureContext(
            stream_number=1,
            source=StreamSource.MICROPHONE,
            source_format=stream.audio_format,
            drop_policy=DropPolicy.DROP_OLDEST,
        )

        collected = bytearray()
        stream.start()
        deadline = time.monotonic() + 1.0
        while time.monotonic() < deadline:
            for frame in context.process_available():
                collected.extend(frame.pcm)
            time.sleep(0.02)
        stream.stop()
        stream.close()

        assert len(collected) % FRAME_BYTES == 0
        assert context.frames_produced > 0
    finally:
        backend.terminate()
