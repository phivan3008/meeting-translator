"""Load-test tool: many concurrent WebSocket sessions against a running server.

Usage:

    python scripts/load_test.py --url ws://localhost:8080/ws/stream \\
        --sessions 20 --duration-s 10 [--token TOKEN] [--json]

Exercises the REAL transport/gateway layer (server/transport/gateway.py) --
handshake, per-stream binary audio ingest, batched acks, payload/rate
limits, the server-wide session cap -- against an already-running server
process (a local dev server, or a real deployment; point ``--url`` at
whichever). This does **not** exercise VAD/ASR/translation:
``UtteranceOrchestrator`` is not yet wired into the live gateway (see
``IMPLEMENTATION_STATUS.md``'s "Known limitations"), so it cannot generate
real transcription/translation load -- only real transport-layer load
(connection handling, packet ordering/acking, rate limiting, overload
rejection). A real end-to-end pipeline latency measurement under
processing load is ``scripts/latency_report.py``'s job instead, via a
direct (non-network) ``UtteranceOrchestrator``, until that gateway wiring
lands.

Reports real counts/timings for this run only -- packets sent per session,
acks received, ack round-trip-time percentiles, connection/handshake
failures, and any typed ``error`` events received (e.g. ``OVERLOADED`` once
the server's session cap is exceeded) -- never a hard-coded pass/fail. A
non-zero count of connection failures or unexpected errors is not
automatically "the load test failed"; read the printed detail.

Requires the ``websockets`` package (the ``server``/``client`` extras).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from shared.protocol.binary import encode_packet  # noqa: E402
from shared.protocol.enums import EventType, Language, StreamSource  # noqa: E402
from shared.protocol.messages import AudioAck, ErrorEvent, SessionStart, StreamConfig  # noqa: E402

FRAME_MS = 20
FRAME_BYTES = FRAME_MS * 32  # mono 16 kHz S16LE
SILENCE_FRAME = bytes(FRAME_BYTES)


@dataclass
class _SessionResult:
    session_id: str
    connected: bool = False
    handshake_error: str | None = None
    packets_sent: int = 0
    acks_received: int = 0
    errors_received: list[str] = field(default_factory=list)
    ack_round_trip_ms: list[float] = field(default_factory=list)


def _percentile(sorted_values: list[float], pct: float) -> float:
    if not sorted_values:
        return float("nan")
    if len(sorted_values) == 1:
        return sorted_values[0]
    rank = (pct / 100.0) * (len(sorted_values) - 1)
    lower = int(rank)
    upper = min(lower + 1, len(sorted_values) - 1)
    fraction = rank - lower
    return sorted_values[lower] + (sorted_values[upper] - sorted_values[lower]) * fraction


async def _run_one_session(
    *, url: str, duration_s: float, token: str | None, index: int
) -> _SessionResult:
    import websockets

    session_id = f"load-{index}-{uuid.uuid4().hex[:8]}"
    result = _SessionResult(session_id=session_id)
    stream_id = f"mic-{index}"
    connect_url = url if not token else f"{url}?token={token}"

    try:
        async with websockets.connect(connect_url) as ws:
            result.connected = True
            start = SessionStart(
                session_id=session_id,
                client_id=f"load-client-{index}",
                timestamp=datetime.now(UTC),
                streams=[
                    StreamConfig(
                        stream_number=1,
                        stream_id=stream_id,
                        source=StreamSource.MICROPHONE,
                        source_language=Language.VIETNAMESE,
                        target_language=Language.JAPANESE,
                    )
                ],
            )
            await ws.send(start.model_dump_json())

            send_times: dict[int, float] = {}
            stop_sending = asyncio.Event()

            async def sender() -> None:
                seq = 0
                deadline = time.monotonic() + duration_s
                while time.monotonic() < deadline:
                    packet = encode_packet(
                        stream_number=1,
                        sequence_number=seq,
                        client_timestamp_ms=int(time.monotonic() * 1000),
                        payload=SILENCE_FRAME,
                    )
                    send_times[seq] = time.monotonic()
                    await ws.send(packet)
                    result.packets_sent += 1
                    seq += 1
                    await asyncio.sleep(FRAME_MS / 1000.0)
                stop_sending.set()

            async def receiver() -> None:
                # After the sender finishes, keep draining for a short grace
                # period so trailing/batched acks are not missed, then stop.
                grace_deadline: float | None = None
                while True:
                    timeout = 1.0
                    if grace_deadline is not None:
                        timeout = max(0.0, grace_deadline - time.monotonic())
                        if timeout <= 0:
                            return
                    try:
                        message = await asyncio.wait_for(ws.recv(), timeout=timeout)
                    except TimeoutError:
                        if stop_sending.is_set() and grace_deadline is None:
                            return
                        continue
                    except websockets.exceptions.ConnectionClosed:
                        return
                    if not isinstance(message, bytes):
                        try:
                            data = json.loads(message)
                        except (ValueError, TypeError):
                            data = None
                        if isinstance(data, dict):
                            if data.get("type") == EventType.AUDIO_ACK.value:
                                ack = AudioAck.model_validate(data)
                                result.acks_received += 1
                                sent_at = send_times.get(ack.last_contiguous_sequence)
                                if sent_at is not None:
                                    result.ack_round_trip_ms.append(
                                        (time.monotonic() - sent_at) * 1000.0
                                    )
                            elif data.get("type") == EventType.ERROR.value:
                                error = ErrorEvent.model_validate(data)
                                result.errors_received.append(
                                    f"{error.code.value}: {error.message}"
                                )
                    if stop_sending.is_set() and grace_deadline is None:
                        grace_deadline = time.monotonic() + 0.5

            await asyncio.gather(sender(), receiver())
    except Exception as exc:  # noqa: BLE001 - report, don't crash the whole load run
        result.handshake_error = f"{type(exc).__name__}: {exc}"

    return result


async def _run(
    *, url: str, sessions: int, duration_s: float, token: str | None
) -> list[_SessionResult]:
    return await asyncio.gather(
        *(
            _run_one_session(url=url, duration_s=duration_s, token=token, index=i)
            for i in range(sessions)
        )
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--url", default="ws://localhost:8080/ws/stream", help="Gateway WS URL.")
    parser.add_argument("--sessions", type=int, default=10, help="Concurrent simulated sessions.")
    parser.add_argument(
        "--duration-s", type=float, default=10.0, help="Seconds each session streams."
    )
    parser.add_argument("--token", default=None, help="Auth token, if the server requires one.")
    parser.add_argument("--json", action="store_true", help="Print JSON instead of a summary.")
    args = parser.parse_args(argv)

    try:
        import websockets  # noqa: F401
    except ImportError:
        print(
            "error: the 'websockets' package is required (pip install -e '.[server]' "
            "or '.[client]')",
            file=sys.stderr,
        )
        return 2

    if args.sessions < 1:
        parser.error("--sessions must be >= 1")

    results = asyncio.run(
        _run(url=args.url, sessions=args.sessions, duration_s=args.duration_s, token=args.token)
    )

    connected = [r for r in results if r.connected]
    failed = [r for r in results if not r.connected]
    total_sent = sum(r.packets_sent for r in results)
    total_acked = sum(r.acks_received for r in results)
    all_rtts = sorted(rtt for r in results for rtt in r.ack_round_trip_ms)
    all_errors = [e for r in results for e in r.errors_received]

    if args.json:
        print(
            json.dumps(
                {
                    "sessions_requested": args.sessions,
                    "sessions_connected": len(connected),
                    "sessions_failed": len(failed),
                    "total_packets_sent": total_sent,
                    "total_acks_received": total_acked,
                    "ack_rtt_p50_ms": round(_percentile(all_rtts, 50), 1) if all_rtts else None,
                    "ack_rtt_p95_ms": round(_percentile(all_rtts, 95), 1) if all_rtts else None,
                    "ack_rtt_p99_ms": round(_percentile(all_rtts, 99), 1) if all_rtts else None,
                    "errors": all_errors,
                    "handshake_errors": [r.handshake_error for r in failed],
                },
                indent=2,
            )
        )
        return 0

    print(f"Load test -- {args.url}, {args.sessions} sessions x {args.duration_s}s\n")
    print(f"connected:            {len(connected)}/{args.sessions}")
    print(f"failed:               {len(failed)}")
    print(f"total packets sent:   {total_sent}")
    print(f"total acks received:  {total_acked}")
    if all_rtts:
        print(
            f"ack round-trip:       p50={_percentile(all_rtts, 50):.1f}ms  "
            f"p95={_percentile(all_rtts, 95):.1f}ms  p99={_percentile(all_rtts, 99):.1f}ms"
        )
    if all_errors:
        print(f"\ntyped error events received ({len(all_errors)}):")
        for message in all_errors[:20]:
            print(f"  - {message}")
        if len(all_errors) > 20:
            print(f"  ... and {len(all_errors) - 20} more")
    if failed:
        print(f"\nhandshake/connection failures ({len(failed)}):")
        for r in failed[:20]:
            print(f"  - {r.session_id}: {r.handshake_error}")
    print("\nThis is a report of what actually happened this run, not a pass/fail verdict.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
