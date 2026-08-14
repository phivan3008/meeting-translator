"""Diagnostic CLI for manual Windows audio verification.

Enumerate devices, or capture a short normalized (mono 16 kHz PCM S16LE) WAV
from a microphone or loopback device. Intended to be run manually on Windows.

Examples (run on Windows after ``pip install -e ".[windows-audio]"``):

    python -m client.audio.wav_cli list
    python -m client.audio.wav_cli capture --source microphone --seconds 5 --out mic.wav
    python -m client.audio.wav_cli capture --source loopback --device 7 --seconds 5 --out loop.wav

Microphone and loopback are captured independently; this tool never mixes them.
"""

from __future__ import annotations

import argparse
import time
import wave

from client.audio.capture import CaptureContext
from client.audio.types import (
    TARGET_CHANNELS,
    TARGET_SAMPLE_RATE,
    CaptureEvent,
    DropPolicy,
)
from shared.protocol.enums import StreamSource


def _make_backend() -> object:
    from client.audio.windows_backend import PyAudioWPatchBackend  # noqa: PLC0415

    return PyAudioWPatchBackend()


def _cmd_list(_: argparse.Namespace) -> int:
    backend = _make_backend()
    print("Input (microphone) devices:")
    for dev in backend.list_input_devices():  # type: ignore[attr-defined]
        print(
            f"  [{dev.index}] {dev.name} ch={dev.max_input_channels} sr={dev.default_sample_rate}"
        )
    print("Loopback devices:")
    for dev in backend.list_loopback_devices():  # type: ignore[attr-defined]
        print(
            f"  [{dev.index}] {dev.name} ch={dev.max_input_channels} sr={dev.default_sample_rate}"
        )
    return 0


def _cmd_capture(args: argparse.Namespace) -> int:
    backend = _make_backend()
    source = StreamSource(args.source)

    if args.device is not None:
        device_index = int(args.device)
    else:
        devices = (
            backend.list_loopback_devices()  # type: ignore[attr-defined]
            if source is StreamSource.LOOPBACK
            else backend.list_input_devices()  # type: ignore[attr-defined]
        )
        if not devices:
            print(f"No {source.value} devices found.")
            return 2
        device_index = devices[0].index

    events: list[CaptureEvent] = []

    context: CaptureContext | None = None

    def on_chunk(data: bytes, ts_ms: int) -> None:
        assert context is not None
        context.on_raw_chunk(data, ts_ms)

    stream = backend.open_stream(  # type: ignore[attr-defined]
        device_index=device_index,
        source=source,
        on_chunk=on_chunk,
        on_event=events.append,
        frames_per_buffer=1024,
    )
    context = CaptureContext(
        stream_number=1 if source is StreamSource.MICROPHONE else 2,
        source=source,
        source_format=stream.audio_format,
        drop_policy=DropPolicy.DROP_OLDEST,
        on_event=events.append,
    )

    collected = bytearray()
    stream.start()
    print(f"Capturing {args.seconds}s from {source.value} device {device_index} ...")
    deadline = time.monotonic() + float(args.seconds)
    try:
        while time.monotonic() < deadline:
            for frame in context.process_available():
                collected.extend(frame.pcm)
            time.sleep(0.02)
        for frame in context.process_available():
            collected.extend(frame.pcm)
    finally:
        stream.stop()
        stream.close()

    with wave.open(args.out, "wb") as wav:
        wav.setnchannels(TARGET_CHANNELS)
        wav.setsampwidth(2)
        wav.setframerate(TARGET_SAMPLE_RATE)
        wav.writeframes(bytes(collected))

    print(
        f"Wrote {args.out}: {len(collected)} bytes, "
        f"{context.frames_produced} frames, dropped={context.chunks_dropped}"
    )
    if events:
        print(f"Events: {[(e.type.value, e.detail) for e in events]}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Windows audio diagnostic CLI.")
    sub = parser.add_subparsers(dest="command", required=True)

    list_parser = sub.add_parser("list", help="Enumerate microphone and loopback devices.")
    list_parser.set_defaults(func=_cmd_list)

    cap = sub.add_parser("capture", help="Capture a short normalized WAV.")
    cap.add_argument("--source", choices=["microphone", "loopback"], required=True)
    cap.add_argument("--device", default=None, help="Device index (defaults to first).")
    cap.add_argument("--seconds", type=float, default=5.0)
    cap.add_argument("--out", default="capture.wav")
    cap.set_defaults(func=_cmd_capture)

    args = parser.parse_args(argv)
    result: int = args.func(args)
    return result


if __name__ == "__main__":
    raise SystemExit(main())
