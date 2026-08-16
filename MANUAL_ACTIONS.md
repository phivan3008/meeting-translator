# Manual Actions

Claude ghi các thao tác mà người dùng cần thực hiện tại đây.

## Pending actions

`GATEWAY-E2E-001` is **root-caused and fixed locally** as of
2026-08-16, after a seven-attempt diagnostic trail
(`GATEWAY-E2E-002`..`007`, see `GATEWAY-E2E-007`'s entry for the full
root-cause writeup). The bug: `UtteranceSegmenter`'s intentional
"too short utterance" discard path emitted no event at all, so
`UtteranceOrchestrator` never released the partial-decode scheduler
entry for it, permanently orphaning that utterance_id for the rest of
the session. Fixed via a new `UtteranceAbandoned` event plus cleanup
handling; locally verified with a new regression test. The user chose
to try a louder, more speech-like synthetic tone next (rather than
switching to a real microphone) -- `GATEWAY-E2E-008` retries with an
amplitude-modulated multi-formant waveform instead of a flat sine tone,
to try to get real Silero VAD to sustain "speech" classification long
enough for a genuine `utterance.final`.

### Action ID: GATEWAY-E2E-001

- Status: WAITING_FOR_USER (**on hold** -- two attempts done, a real
  unresolved stall found on attempt 2; see `GATEWAY-E2E-002` below,
  which should run first)
- Attempt 1 result (2026-08-15): Real success -- three real
  `transcription.partial` events arrived with real content from real
  Silero VAD + real faster-whisper over the real live gateway (the exact
  known Whisper hallucination on synthetic-tone input already seen in
  `GPU-E2E-001`/`GPU-E2E-003`, with the stable-prefix promotion logic
  visibly correct across revisions). No `utterance.final` arrived --the
  connection was closed by the *server's own idle timeout* (WS close
  code 1008) while real final ASR + real translation were still running
  as a background task. Root cause: the test client stopped sending
  anything after its test frames and just waited for a reply, unlike a
  real client (`AudioSender`), which never stops streaming
  frames/keepalives -- so the server had nothing to reset its idle timer
  with while the background finalize work was in flight. This is a test
  -script fidelity gap, not a wiring defect; see
  `USER_RESULTS.md`'s `GATEWAY-E2E-001 (attempt 1)` for full detail.
  Fixed below: the client now sends periodic `AudioFlags.KEEPALIVE`
  frames while waiting for the final event, matching real client
  behavior. Also note: port 8080 was already in use on this host last
  time (unrelated process) -- the commands below default to 3000
- Attempt 1 result (2026-08-15): Real success -- three real
  `transcription.partial` events arrived with real content from real
  Silero VAD + real faster-whisper over the real live gateway (the exact
  known Whisper hallucination on synthetic-tone input already seen in
  `GPU-E2E-001`/`GPU-E2E-003`, with the stable-prefix promotion logic
  visibly correct across revisions). No `utterance.final` arrived --the
  connection was closed by the *server's own idle timeout* (WS close
  code 1008) while real final ASR + real translation were still running
  as a background task. Root cause: the test client stopped sending
  anything after its test frames and just waited for a reply, unlike a
  real client (`AudioSender`), which never stops streaming
  frames/keepalives -- so the server had nothing to reset its idle timer
  with while the background finalize work was in flight. This is a test
  -script fidelity gap, not a wiring defect; see
  `USER_RESULTS.md`'s `GATEWAY-E2E-001 (attempt 1)` for full detail.
  Fixed below: the client now sends periodic `AudioFlags.KEEPALIVE`
  frames while waiting for the final event, matching real client
  behavior. Also note: port 8080 was already in use on this host last
  time (unrelated process) -- the commands below default to 3000
  instead; adjust if that's also taken.
- Attempt 2 result (2026-08-15): The keepalive fix worked as intended --
  no more premature idle-timeout disconnect (`ConnectionClosedError`).
  But `utterance.final` still never arrived: the client's full 180s
  receive loop ran to completion and printed `TIMED OUT waiting for
  utterance.final`, not an exception this time. The server log shows
  exactly the same 3 partial-decode lines as attempt 1, then **no
  further activity of any kind** for the full ~2m33s until the client's
  own loop gave up and disconnected. No error event, no traceback. This
  is a real, unresolved finding -- the background finalize task (a real
  full-utterance faster-whisper decode, sharing the GPU with the
  already-running vLLM server at ~76 of 81.5 GiB VRAM used) appears to
  stall rather than crash, since `FinalTranscriber.finalize()` would
  otherwise have logged its own "Processing audio" line unconditionally.
  Full reasoning in `USER_RESULTS.md`'s `GATEWAY-E2E-001 (attempt 2)`
  entry. Do not attempt a third blind retry -- `GATEWAY-E2E-002` gets a
  live look at exactly where the server is stuck first.
- Purpose: `UtteranceOrchestrator` is now wired into
  `server/transport/gateway.py`, proven with scripted ASR/translation/VAD
  doubles over the real websocket transport
  (`tests/test_transport_gateway_orchestration.py`). This action is the
  first check with **real** Silero VAD + real faster-whisper + real vLLM,
  driven through the **actual live gateway** by a **real WebSocket
  client** -- not `tests/test_e2e_gpu.py`, which calls
  `UtteranceOrchestrator` directly and bypasses the gateway entirely.
  Confirms real audio-in actually produces real
  `transcription.partial`/`utterance.final` events over the wire.
- Run on: The ASR GPU host (`WhisperAsrModel`/`SileroVadModel` run
  in-process inside the server, not as a remote service, so the server
  itself must run where `faster-whisper` and GPU access are available --
  same host as `GPU-E2E-003`/`LATENCY-001`), with network reachability to
  the running vLLM server from `GPU-TRANSLATE-008` (confirmed healthy in
  `GPU-E2E-003`).
- Prerequisites: `.venv-asr` (already has `faster-whisper`, `dev` extra).
  Additionally needs:
  - `pip install "silero-vad>=5,<6"` (real VAD -- pulls in `torch`, not
    otherwise present in this venv per `GPU-ASR-002`'s finding).
  - `pip install "uvicorn[standard]>=0.29,<1" "websockets>=12,<13"` (to
    run the real server and to drive a WebSocket client against it --
    neither is in the `dev` extra, only `server`; installing just these
    two avoids pulling in `redis`, which this test doesn't need).
  - A `.env` (or exported vars) with `VLLM_BASE_URL` pointing at the
    running vLLM server (confirm with the same `/health` check
    `GPU-E2E-002` used first) and `APP_ENV` left as `development` (or
    unset) so the dev anonymous authenticator applies -- no JWT token
    needed for this check.
- Safety notes: Starts a real server process holding a real `large-v3`
  model in GPU memory (~2.88 GiB, per `GPU-ASR-004`) alongside the
  already-running vLLM server (~75.9 GiB used of 81.5 GiB total per
  `GPU-TRANSLATE-008`'s verification) -- headroom is tight (~5.6 GiB
  free); an OOM here is a real possible outcome and itself useful signal
  (see `docs/OPERATOR_RUNBOOK_SEED.md`'s "Whisper or vLLM OOM response"),
  not necessarily a bug. Uses a synthesized sine tone as input, matching
  `GPU-ASR-004`/`GPU-E2E-001`'s precedent -- no personal or bundled
  audio. Read-only against vLLM (a few chat-completion requests).
- Commands:
  ```bash
  cd /workspace/meeting-translator   # adjust to the real path on this host -- verify with pwd/ls
  source .venv-asr/bin/activate
  # silero-vad/uvicorn/websockets are already installed from attempt 1;
  # re-running these is harmless if not.
  pip install "silero-vad>=5,<6"
  pip install "uvicorn[standard]>=0.29,<1" "websockets>=12,<13"

  # 1. Start the real server in the background, keeping its log.
  #    Port 8080 was busy last time (unrelated process) -- using 3000;
  #    adjust if that's taken too (check with `ss -ltn` or similar).
  nohup uvicorn server.app:app --host 127.0.0.1 --port 3000 > gateway_e2e_server.log 2>&1 &
  disown
  sleep 5
  curl -s http://127.0.0.1:3000/health/live
  tail -n 40 gateway_e2e_server.log   # confirm clean startup, no traceback

  # 2. Real WebSocket client: real protocol packets, a synthesized sine
  #    tone (no personal/bundled audio), real events read back. Sends
  #    periodic KEEPALIVE frames while waiting for utterance.final --
  #    matching real client behavior -- so the server's idle timeout
  #    doesn't fire while real final ASR/translation are still running.
  cat > /tmp/gateway_e2e_client.py << 'EOF'
  import asyncio
  import json
  import math
  import struct
  from datetime import UTC, datetime

  import websockets

  from shared.protocol.binary import AudioFlags, encode_packet
  from shared.protocol.enums import Language, StreamSource
  from shared.protocol.messages import SessionStart, StreamConfig

  FRAME_MS = 20
  SAMPLE_RATE = 16000
  FRAME_SAMPLES = SAMPLE_RATE * FRAME_MS // 1000

  def sine_frame(frame_index: int, frequency_hz: float = 220.0, amplitude: float = 0.2) -> bytes:
      samples = []
      for i in range(FRAME_SAMPLES):
          t = (frame_index * FRAME_SAMPLES + i) / SAMPLE_RATE
          value = amplitude * math.sin(2 * math.pi * frequency_hz * t)
          samples.append(int(value * 32767))
      return struct.pack(f"<{FRAME_SAMPLES}h", *samples)

  def silence_frame() -> bytes:
      return b"\x00\x00" * FRAME_SAMPLES

  async def main() -> None:
      session_start = SessionStart(
          session_id="sess-gateway-e2e-001b",
          client_id="gateway-e2e-client",
          timestamp=datetime.now(UTC),
          streams=[
              StreamConfig(
                  stream_number=1,
                  stream_id="mic-01",
                  source=StreamSource.MICROPHONE,
                  source_language=Language.JAPANESE,
                  target_language=Language.VIETNAMESE,
              )
          ],
      )
      async with websockets.connect("ws://127.0.0.1:3000/ws/stream") as ws:
          await ws.send(session_start.model_dump_json())

          seq = 0
          # ~1.5s tone (past min_speech_ms), then enough silence to force
          # hard-silence finalization deterministically.
          for i in range(75):
              packet = encode_packet(
                  stream_number=1, sequence_number=seq, client_timestamp_ms=seq * FRAME_MS,
                  payload=sine_frame(i),
              )
              await ws.send(packet)
              seq += 1
          for _ in range(60):
              packet = encode_packet(
                  stream_number=1, sequence_number=seq, client_timestamp_ms=seq * FRAME_MS,
                  payload=silence_frame(),
              )
              await ws.send(packet)
              seq += 1

          final_seen = False
          for _ in range(60):
              try:
                  raw = await asyncio.wait_for(ws.recv(), timeout=3)
              except asyncio.TimeoutError:
                  # Nothing arrived in 3s -- send a keepalive so the
                  # server's idle timer doesn't fire while real final
                  # ASR/translation are still running in the background.
                  seq += 1
                  await ws.send(
                      encode_packet(
                          stream_number=1, sequence_number=seq,
                          client_timestamp_ms=seq * FRAME_MS, payload=b"",
                          flags=AudioFlags.KEEPALIVE,
                      )
                  )
                  continue
              event = json.loads(raw)
              if event["type"] in ("transcription.partial", "utterance.final", "error"):
                  print(f"{event['type']}: {event}")
              if event["type"] == "utterance.final":
                  final_seen = True
                  break
          if not final_seen:
              print("TIMED OUT waiting for utterance.final")

  asyncio.run(main())
  EOF
  PYTHONPATH=/workspace/meeting-translator python /tmp/gateway_e2e_client.py

  # 3. Cleanup.
  pkill -f "uvicorn server.app:app"
  ```
- Expected success indicators: Step 1's `/health/live` returns
  `{"status":"alive",...}` and the log shows a clean uvicorn startup with
  no traceback. Step 2 prints at least one `transcription.partial` (or
  goes straight to `utterance.final` -- either is fine, matching
  `GPU-E2E-001`'s "no partial firing isn't a wiring failure" precedent)
  and exactly one `utterance.final` with real fields
  (`transcription`/`translation`/`translation_status`) -- content
  accuracy on a synthetic tone is not the point (may be empty or a
  hallucinated phrase, as `GPU-E2E-003` already saw), proving the *wire
  path* executed for real is. No `error` events. If an OOM or connection
  error occurs instead, that is itself useful, expected-possible signal
  -- report it rather than treating it as an action failure.
  Expected artifacts: `gateway_e2e_server.log`; `/tmp/gateway_e2e_client.py`
  is temporary.
- Rollback or cleanup: `pkill -f "uvicorn server.app:app"` if still
  running; `rm /tmp/gateway_e2e_client.py`.
- Return to Claude (secrets/hostnames redacted):
  - `gateway_e2e_server.log`'s startup excerpt.
  - The full printed event sequence from the client script.
  - Whether exactly one `utterance.final` arrived, and its
    `transcription`/`translation`/`translation_status` values.
  - Any error, OOM, or connection failure observed.

### Action ID: GATEWAY-E2E-003

- Status: WAITING_FOR_USER (result in -- hypothesis disproved; see below.
  Superseded by `GATEWAY-E2E-004`.)
- Result (2026-08-15): Real Silero VAD probability drops to `0.0001`
  within ~300ms of the tone stopping and stays there consistently across
  all 60 sampled log lines -- clean, confident, unambiguous silence
  detection. Hard-silence finalization should have triggered well within
  the 8s (400-frame) silence budget sent. **This VAD-timing hypothesis
  is disproved.** Client again printed exactly 3 partials then `TIMED
  OUT`; server log again showed only the same 3
  `faster_whisper Processing audio` lines and nothing further. A
  diagnostic mistake was also caught here: the `grep ... UtteranceFinal`
  used in earlier attempts proves nothing either way, since that VAD
  event is never actually logged anywhere in this codebase -- its
  absence from a grep isn't evidence. Full detail in
  `USER_RESULTS.md`'s `GATEWAY-E2E-003` entry. `GATEWAY-E2E-004` adds
  real tracing through the actual finalize code path instead
  (commit `bc5564e`).
- Purpose: `GATEWAY-E2E-002`'s `py-spy dump` failed -- `ptrace` is blocked
  in this host's container even as root ("Permission denied", no `sudo`
  available). But its other two findings are still real evidence:
  `/health/live` responded instantly during the "stall" (the event loop
  itself is not stuck), and `nvidia-smi` showed **0% GPU utilization**
  while ~79.6 GiB was held -- nothing was actually computing. Combined
  with the complete absence of a 4th `faster_whisper Processing audio`
  line, this points away from "a hung decode" and toward a simpler
  explanation: **the utterance may never be finalizing at all.** Real
  Silero VAD's probability for the test's all-zero silence frames may
  not drop convincingly below `vad_threshold` (0.5) within the 60
  frames (1.2s) previously sent -- unlike the scripted VAD used
  everywhere else in this project's tests, which returns a clean, fixed
  0.1 for "silence" -- so `hard_silence_ms` (900ms of consecutive
  below-threshold frames) may simply never be reached, meaning
  `_finalize_utterance` is never spawned in the first place (matching
  0% GPU utilization: there is nothing running because nothing was ever
  asked to run). A new DEBUG-level log line was added to
  `SileroVadModel.probability()` (commit `d78a6af`) to make the real
  probability trend directly observable -- a scalar float per window,
  not audio content, gated by `LOG_LEVEL=DEBUG`. This action tests the
  hypothesis directly: send much more trailing silence (400 frames, 8s
  -- generously past any plausible VAD settling time) and watch the
  probability log.
- Run on: Same host/venv as `GATEWAY-E2E-001`/`002`.
- Prerequisites: `git pull` first, to get the new logging line -- confirm
  with `git log -1 --oneline` showing `d78a6af` or later.
- Safety notes: Same as `GATEWAY-E2E-001`/`002` (real GPU memory, real
  synthetic sine tone, no personal audio). `LOG_LEVEL=DEBUG` will make
  the server log substantially more verbose (every VAD window, plus
  library-internal debug lines) -- expected and fine for this one
  diagnostic run, not meant to be a permanent setting.
- Commands:
  ```bash
  cd /workspace/meeting-translator
  source .venv-asr/bin/activate
  git pull
  git log -1 --oneline   # confirm the new SileroVadModel logging is present

  pkill -f "uvicorn server.app:app" 2>/dev/null
  sleep 1
  LOG_LEVEL=DEBUG nohup uvicorn server.app:app --host 127.0.0.1 --port 3000 > gateway_e2e_server.log 2>&1 &
  disown
  sleep 5
  curl -s http://127.0.0.1:3000/health/live

  # Same client, but with 400 silence frames (8s) instead of 60 (1.2s).
  cat > /tmp/gateway_e2e_client.py << 'EOF'
  import asyncio
  import json
  import math
  import struct
  from datetime import UTC, datetime

  import websockets

  from shared.protocol.binary import AudioFlags, encode_packet
  from shared.protocol.enums import Language, StreamSource
  from shared.protocol.messages import SessionStart, StreamConfig

  FRAME_MS = 20
  SAMPLE_RATE = 16000
  FRAME_SAMPLES = SAMPLE_RATE * FRAME_MS // 1000
  SILENCE_FRAME_COUNT = 400  # 8s -- generously past any plausible VAD settling time

  def sine_frame(frame_index: int, frequency_hz: float = 220.0, amplitude: float = 0.2) -> bytes:
      samples = []
      for i in range(FRAME_SAMPLES):
          t = (frame_index * FRAME_SAMPLES + i) / SAMPLE_RATE
          value = amplitude * math.sin(2 * math.pi * frequency_hz * t)
          samples.append(int(value * 32767))
      return struct.pack(f"<{FRAME_SAMPLES}h", *samples)

  def silence_frame() -> bytes:
      return b"\x00\x00" * FRAME_SAMPLES

  async def main() -> None:
      session_start = SessionStart(
          session_id="sess-gateway-e2e-003",
          client_id="gateway-e2e-client",
          timestamp=datetime.now(UTC),
          streams=[
              StreamConfig(
                  stream_number=1,
                  stream_id="mic-01",
                  source=StreamSource.MICROPHONE,
                  source_language=Language.JAPANESE,
                  target_language=Language.VIETNAMESE,
              )
          ],
      )
      async with websockets.connect("ws://127.0.0.1:3000/ws/stream") as ws:
          await ws.send(session_start.model_dump_json())

          seq = 0
          for i in range(75):
              packet = encode_packet(
                  stream_number=1, sequence_number=seq, client_timestamp_ms=seq * FRAME_MS,
                  payload=sine_frame(i),
              )
              await ws.send(packet)
              seq += 1
          for _ in range(SILENCE_FRAME_COUNT):
              packet = encode_packet(
                  stream_number=1, sequence_number=seq, client_timestamp_ms=seq * FRAME_MS,
                  payload=silence_frame(),
              )
              await ws.send(packet)
              seq += 1

          final_seen = False
          for _ in range(60):
              try:
                  raw = await asyncio.wait_for(ws.recv(), timeout=3)
              except asyncio.TimeoutError:
                  seq += 1
                  await ws.send(
                      encode_packet(
                          stream_number=1, sequence_number=seq,
                          client_timestamp_ms=seq * FRAME_MS, payload=b"",
                          flags=AudioFlags.KEEPALIVE,
                      )
                  )
                  continue
              event = json.loads(raw)
              if event["type"] in ("transcription.partial", "utterance.final", "error"):
                  print(f"{event['type']}: {event}")
              if event["type"] == "utterance.final":
                  final_seen = True
                  break
          if not final_seen:
              print("TIMED OUT waiting for utterance.final")

  asyncio.run(main())
  EOF
  PYTHONPATH=/workspace/meeting-translator python /tmp/gateway_e2e_client.py > /tmp/gateway_e2e_client.log 2>&1
  cat /tmp/gateway_e2e_client.log

  # Pull out just the VAD probability trend for the silence portion, plus
  # anything ASR/finalize-related, so the log excerpt to paste back is
  # manageable rather than the full (very verbose) DEBUG log.
  echo "=== VAD probability trend (last 60 lines) ==="
  grep "silero window probability" gateway_e2e_server.log | tail -60
  echo "=== ASR / finalize activity ==="
  grep -E "faster_whisper|UtteranceFinal|error" gateway_e2e_server.log

  pkill -f "uvicorn server.app:app"
  ```
- Expected success indicators: The probability log shows real numbers --
  ideally a clear drop from high (during the sine tone) to low (during
  silence) within the first several silence frames, in which case
  `utterance.final` should now appear (confirming the hypothesis: the
  test's original 60 silence frames just weren't enough for real VAD,
  not a wiring bug). If probability *never* drops meaningfully below
  0.5 even after 8s of pure digital silence, that is a different, more
  concerning finding worth its own follow-up (real VAD misbehavior on
  this input, or a bug in how frames reach it) -- report the actual
  numbers either way, don't just report pass/fail.
  Expected artifacts: `gateway_e2e_server.log` (large, DEBUG-level --
  the two `grep` excerpts above are what to paste back, not the whole
  file), `/tmp/gateway_e2e_client.log`.
- Rollback or cleanup: `pkill -f "uvicorn server.app:app"` if still
  running.
- Return to Claude (secrets/hostnames redacted):
  - The `git log -1 --oneline` output (confirms the new code was pulled).
  - The full client script output (`transcription.partial`/
    `utterance.final`/`TIMED OUT` lines).
  - The VAD probability trend excerpt (paste as many of the `tail -60`
    lines as came out -- the actual numbers matter here).
  - The ASR/finalize activity excerpt.

### Action ID: GATEWAY-E2E-004

- Status: WAITING_FOR_USER (**result in** -- the finalize-path trace was
  completely empty; `UtteranceFinalized` itself never fired. Superseded
  by `GATEWAY-E2E-005`, not retried.)
- Result (2026-08-16): All three grep outputs came back empty except the
  ASR activity one, which showed the same 3 "Processing audio" lines as
  `GATEWAY-E2E-003` (clustered within ~400ms) and nothing after. No
  `finalize task`/`UtteranceFinalized`/`finalized reason` line ever
  appeared, and no traceback. This rules out the finalize code path
  entirely -- `UtteranceOrchestrator._on_vad_event`'s `UtteranceFinalized`
  branch was never reached, meaning `UtteranceSegmenter.process_frame`
  itself never produced that event.
  - `UtteranceSegmenter`'s hard-silence check (`_check_silence` in
    `server/vad/state_machine.py`) is pure synchronous CPU logic with no
    wall-clock dependency -- it fires once `silence_run_ms` accumulated
    across `process_frame()` calls crosses `hard_silence_ms`, regardless
    of real time elapsed. Given probability sat at 0.0001 for the whole
    silence run (`GATEWAY-E2E-003`), this *should* have fired well within
    the 400 silence frames sent, unless frames simply stopped being fed
    to it.
  - The partial's `end_ms` staying at exactly 900ms across both revision
    2 and 3 confirms this: `end_ms = start_ms + total_ms` in
    `PartialTranscriber`, and `total_ms` only grows via `append_audio`,
    called once per frame from `UtteranceOrchestrator.ingest_frame`. If
    frames kept arriving, `end_ms` would keep climbing across revisions;
    it didn't, so ingestion itself stalled around frame ~45 (900ms /
    20ms), not just decoding.
  - Two prior candidate explanations were checked and ruled out
    analytically (not by re-running hardware, since the code proves it):
    the WebSocket rate limiter (`TokenBucket`, `ws_rate_limit_burst=400`
    by default) starts **full** at 400 tokens, so the first 400 of the
    client's 475 total packets always pass regardless of send timing --
    it cannot explain a stall at frame ~45. The jitter buffer
    (`server/transport/jitter_buffer.py`) releases every packet
    immediately once it arrives in order, with no timing dependency
    either, and the client sends strictly sequential sequence numbers.
  - Conclusion: this is very likely a genuine **hang**, not a silent
    drop or a logic bug -- something inside `_handle_packet`'s
    per-released-frame loop in `server/transport/gateway.py` (the
    `await loop.run_in_executor(vad_executor, vad_model.probability,
    frame_pcm)` call, or `await orchestrator.ingest_frame(...)` itself)
    never returns for one particular frame, which would explain
    everything observed: no exception (nothing raised), no further ASR
    activity (frames never reach it), connection staying open (nothing
    closes it), and the `_ingest_loop`'s `while True` never looping again
    to receive more of the already-sent packets.
  - Since `py-spy` is unusable on this host (`GATEWAY-E2E-002`,
    `ptrace` blocked even for root), added Python's built-in
    `faulthandler` instead (commit pending push) -- it needs no ptrace at
    all since it dumps every thread's live stack from inside the process
    itself, triggered by `SIGUSR1`. `GATEWAY-E2E-005` below uses it to
    catch the hang in the act.
- Original purpose (for history): Three attempts had shown the same
  partials, then nothing -- no 4th ASR log line, no error event, no
  traceback -- with `py-spy` unusable and the VAD-timing hypothesis
  disproved by real probability data (`GATEWAY-E2E-003`). The finalize
  code path itself (`UtteranceOrchestrator._on_vad_event`'s
  `UtteranceFinalized` branch -> `_finalize_utterance` ->
  `_do_finalize_utterance` -> `FinalTranscriber.finalize`) has never
  actually been traced -- the earlier `grep ... UtteranceFinal` checked
  for something that was never logged in the first place, proving
  nothing. New DEBUG logs (commit `bc5564e`) now trace every step: event
  received, finalize task started, about to call
  `FinalTranscriber.finalize`, got a result, or caught `AsrError` --
  plus a catch-and-log for any other exception type (previously any
  non-`AsrError` exception would propagate silently out of the
  un-awaited background task with no visible log line at all). This
  retry will show exactly which of those steps is the last one reached.
- Run on: Same host/venv as prior `GATEWAY-E2E-*` actions.
- Prerequisites: `git pull` first -- confirm with `git log -1 --oneline`
  showing `bc5564e` or later.
- Safety notes: Same as prior attempts (real GPU memory, synthetic sine
  tone only). `LOG_LEVEL=DEBUG` again, for the same reason as
  `GATEWAY-E2E-003`.
- Commands:
  ```bash
  cd /workspace/meeting-translator
  source .venv-asr/bin/activate
  git pull
  git log -1 --oneline   # confirm the new finalize-path tracing is present

  pkill -f "uvicorn server.app:app" 2>/dev/null
  sleep 1
  LOG_LEVEL=DEBUG nohup uvicorn server.app:app --host 127.0.0.1 --port 3000 > gateway_e2e_server.log 2>&1 &
  disown
  sleep 5
  curl -s http://127.0.0.1:3000/health/live

  # Same client as GATEWAY-E2E-003 (400 silence frames) -- recreate
  # /tmp/gateway_e2e_client.py if it's gone, unchanged from that action.
  PYTHONPATH=/workspace/meeting-translator python /tmp/gateway_e2e_client.py > /tmp/gateway_e2e_client.log 2>&1
  cat /tmp/gateway_e2e_client.log

  echo "=== finalize-path trace (pipeline.py's new DEBUG lines) ==="
  grep -E "finalize task|UtteranceFinalized|finalized reason" gateway_e2e_server.log
  echo "=== any traceback ==="
  grep -B2 -A20 "Traceback" gateway_e2e_server.log
  echo "=== ASR activity ==="
  grep "faster_whisper Processing audio" gateway_e2e_server.log

  pkill -f "uvicorn server.app:app"
  ```
- Expected success indicators: The trace grep shows how far things get:
  - Nothing at all -> `UtteranceFinalized` itself never fires (points
    back to the segmenter/orchestrator's hard-silence logic despite the
    clean VAD data -- would need its own follow-up).
  - `"finalized reason=..."` appears but `"finalize task started"`
    doesn't -> the task was spawned but never actually ran (an asyncio
    scheduling question).
  - `"finalize task started"` appears but `"calling
    final_transcriber.finalize"` doesn't -> stuck between task start and
    the call itself (unlikely, almost no code there, but now visible).
  - `"calling final_transcriber.finalize"` appears but nothing after ->
    stuck inside `FinalTranscriber.finalize`/`.transcribe()` itself, most
    likely in the executor-bound real decode call -- back to a genuine
    hang hypothesis, now narrowed to an exact location.
  - A traceback appears -> the new catch-and-log caught something real;
    paste it in full, this would finally be a concrete root cause.
  Whichever of these it is, that is the actual answer -- report exactly
  what appeared, not just "worked" or "didn't work".
  Expected artifacts: `gateway_e2e_server.log`, `/tmp/gateway_e2e_client.log`.
- Rollback or cleanup: `pkill -f "uvicorn server.app:app"` if still
  running.
- Return to Claude (secrets/hostnames redacted):
  - The `git log -1 --oneline` output.
  - The client's full printed output.
  - The full finalize-path trace grep output (even if empty -- that's
    informative too).
  - The traceback grep output, if any.
  - The ASR activity grep output.

### Action ID: GATEWAY-E2E-005

- Status: WAITING_FOR_USER (**result in** -- the thread dump showed
  everything idle, contradicting the "hung in `run_in_executor`"
  hypothesis. Superseded by `GATEWAY-E2E-006`, not retried.)
- Result (2026-08-16): `kill -USR1` successfully dumped every thread's
  stack. All of them were idle: both `tqdm` monitor threads blocked in
  `Event.wait()` (unrelated background threads, always present), the one
  spawned `ThreadPoolExecutor` worker blocked in its own work-queue
  `get()` (i.e. **not** executing a VAD call), the `anyio` backend thread
  blocked in `queue.get()`, and the main/event-loop thread sitting at the
  generic top-level `asyncio.run` entry frame with no task actively
  executing -- the signature of a genuinely idle event loop (blocked in
  epoll/select), not one stuck mid-await on a pending future. Same 3 ASR
  `Processing audio` lines as every prior attempt, nothing further.
  - This rules out `GATEWAY-E2E-004`'s leading hypothesis: nothing is
    hung *inside* a call. The server side is simply not receiving any
    more packets at the application layer after the first ~45 frames'
    worth. The open question shifted from "what's blocking?" to "did the
    remaining ~430 packets ever reach `_handle_packet` at all, and if
    not, why not?" -- `GATEWAY-E2E-006` adds direct per-packet sequence
    logging plus a teardown summary of total counts to answer that with
    real data instead of more inference from indirect signals.
- Original purpose (for history): Catch the suspected hang in the act
  using Python's built-in
  `faulthandler` (commit pushed alongside this entry), since `py-spy` is
  unusable on this host (`GATEWAY-E2E-002`). `faulthandler.register` is
  now called at server startup, listening for `SIGUSR1`; sending that
  signal to the server process dumps every thread's current Python stack
  straight to its stderr (which lands in `gateway_e2e_server.log`, same
  redirect as always) -- no ptrace, no root, no extra tooling. The
  client script sends all 475 packets essentially at once, so the hang
  (if `GATEWAY-E2E-004`'s analysis is right) should already have
  happened within the first second or two; the plan is to let it settle
  for ~10s, then signal the server while the client is still waiting.
- Run on: Same host/venv as prior `GATEWAY-E2E-*` actions.
- Prerequisites: `git pull` first -- confirm with `git log -1 --oneline`
  showing the `faulthandler` commit.
- Safety notes: `SIGUSR1` only dumps stack traces; it does not stop or
  restart the process, so the run can continue normally afterward.
  `LOG_LEVEL=DEBUG` again for continuity with prior attempts, though the
  faulthandler dump does not depend on the log level.
- Commands:
  ```bash
  cd /workspace/meeting-translator
  source .venv-asr/bin/activate
  git pull
  git log -1 --oneline   # confirm the faulthandler commit is present

  pkill -f "uvicorn server.app:app" 2>/dev/null
  sleep 1
  LOG_LEVEL=DEBUG nohup uvicorn server.app:app --host 127.0.0.1 --port 3000 > gateway_e2e_server.log 2>&1 &
  disown
  UVICORN_PID=$!
  sleep 5
  curl -s http://127.0.0.1:3000/health/live

  # Same client as GATEWAY-E2E-003/004 (400 silence frames) -- recreate
  # /tmp/gateway_e2e_client.py if it's gone, unchanged from GATEWAY-E2E-003.
  PYTHONPATH=/workspace/meeting-translator python /tmp/gateway_e2e_client.py > /tmp/gateway_e2e_client.log 2>&1 &
  CLIENT_PID=$!

  # Give the client time to blast all its packets and for the (suspected)
  # hang to actually happen -- the 3 partials typically appear within
  # the first second.
  sleep 10

  echo "=== sending SIGUSR1 to dump all thread stacks ==="
  kill -USR1 $UVICORN_PID
  sleep 2

  # Let the client finish out its own timeout (up to ~180s) or just wait
  # for it directly.
  wait $CLIENT_PID
  cat /tmp/gateway_e2e_client.log

  echo "=== faulthandler thread dump ==="
  grep -A 200 "Thread 0x" gateway_e2e_server.log
  echo "=== ASR activity ==="
  grep "faster_whisper Processing audio" gateway_e2e_server.log

  pkill -f "uvicorn server.app:app"
  ```
- Expected success indicators: The thread dump shows one thread (either
  the main event-loop thread or one of the `vad` `ThreadPoolExecutor`
  workers) sitting inside a specific line of code -- that line is the
  answer. In particular:
  - A `vad` worker thread stuck inside `SileroVadModel.probability`/
    `_score_window`, or inside a torch/silero_vad internal call ->
    points at the real Silero model itself hanging or deadlocking under
    real inference load.
  - The main thread (or the event loop's thread) stuck at the
    `await loop.run_in_executor(...)` line in
    `server/transport/gateway.py`'s `_handle_packet` -> confirms it's
    waiting on that executor call specifically (consistent with a stuck
    `vad` worker above).
  - The main thread stuck inside `UtteranceOrchestrator.ingest_frame` or
    deeper (`state.segmenter.process_frame`, `self._partial.append_audio`)
    -> points away from VAD and at the orchestrator/segmenter/partial
    transcriber path instead.
  - No threads shown, or the dump is empty/missing -> the signal never
    reached the process, or the hang theory itself is wrong and something
    else is going on (report exactly what came back either way).
  Expected artifacts: `gateway_e2e_server.log` (contains the thread
  dump inline), `/tmp/gateway_e2e_client.log`.
- Rollback or cleanup: `pkill -f "uvicorn server.app:app"` if still
  running.
- Return to Claude (secrets/hostnames redacted):
  - The `git log -1 --oneline` output.
  - The full faulthandler thread-dump grep output -- this is the whole
    point of the action, paste it in full even if long.
  - The client's full printed output.
  - The ASR activity grep output.

### Action ID: GATEWAY-E2E-006

- Status: WAITING_FOR_USER (**result in** -- all 475 audio frames were
  released and ingested; the session ended via a clean client-side
  disconnect, not a server idle timeout or a hang. Superseded by
  `GATEWAY-E2E-007`, not retried.)
- Result (2026-08-16): `received=517` (475 audio packets + 42
  `KEEPALIVE` packets, matching the client's own timeout/keepalive
  loop), `released=475` (every single audio frame -- matches the
  client's 75 sine + 400 silence exactly), `lost=0`, `duplicates=0`,
  `stale=0`. The session ended with `"client disconnected"` logged, not
  `"idle timeout"` -- the client's own 60-iteration receive loop simply
  ran its course and closed the connection normally afterward.
  - This rules out every transport-layer explanation: packets were not
    dropped, not lost to jitter-buffer overflow, and the server's own
    idle timeout never fired (the client's keepalives kept it alive
    throughout). All 475 real audio frames genuinely reached
    `_handle_packet`'s released-frame loop and (since the ingest loop
    never crashed, confirmed by clean processing all the way through
    packet 517) were awaited into `orchestrator.ingest_frame` without
    exception.
  - This reopens the question `GATEWAY-E2E-004` seemed to answer: if all
    475 frames really were ingested, `PartialTranscriber.append_audio`
    should have kept growing the utterance's audio window the whole
    time, and `end_ms` should have climbed well past 900ms on later
    decodes -- yet only 3 real ASR calls ever happened. Checked the
    partial-decode scheduler (`server/asr/partial_scheduler.py`) and
    sliding window (`server/asr/sliding_window.py`) against production
    defaults (`whisper_partial_interval_ms=500`,
    `whisper_audio_overlap_ms=1500`): the scheduler has no cap or
    stopping condition other than an explicit `.stop()` call (only
    reachable via `UtteranceFinalized`, already proven never to fire),
    and `overlap_ms=1500` exceeds the ~900ms stable boundary reached at
    decode #3, meaning `SlidingAudioWindow.advance()` should not have
    been draining the window to empty either. Neither explains the
    stoppage by static analysis alone.
  - Added direct tracing at the two remaining decision points instead
    of further inference: whether `PartialDecodeScheduler.due()` keeps
    firing at all as `now_ms` climbs to 9500, and whether
    `PartialTranscriber.decode()`'s window is ever actually empty when
    it's called. Staged as `GATEWAY-E2E-007`.
- Original purpose (for history): `GATEWAY-E2E-005`'s thread dump showed
  the server genuinely
  idle, not stuck inside a call -- ruling out the "hung executor"
  hypothesis. The open question is now: how many of the client's 475
  packets did the server's application layer (`_handle_packet`) actually
  see before things went quiet? New DEBUG logging (commit pending push)
  logs every decoded packet's sequence number/flags/size (never audio
  content) as it's processed, plus an INFO-level per-stream summary of
  total received/released/lost/duplicate/stale counts, logged on session
  teardown (`_flush_all_streams`). This also captures whichever of the
  two already-existing (but never explicitly checked) log lines fires on
  teardown: `"client disconnected"` (client-initiated close) or
  `"session ... idle timeout"` (server-initiated close after
  `ws_idle_timeout_ms`, default 15s, of silence) -- worth grepping for
  both this time, since neither was specifically checked in any prior
  attempt.
- Run on: Same host/venv as prior `GATEWAY-E2E-*` actions.
- Prerequisites: `git pull` first -- confirm with `git log -1 --oneline`
  showing the new per-packet tracing commit.
- Safety notes: Same as prior attempts (real GPU memory, synthetic sine
  tone only). `LOG_LEVEL=DEBUG` again, needed for the per-packet lines
  (the teardown summary is INFO and will show regardless).
- Commands:
  ```bash
  cd /workspace/meeting-translator
  source .venv-asr/bin/activate
  git pull
  git log -1 --oneline   # confirm the per-packet tracing commit is present

  pkill -f "uvicorn server.app:app" 2>/dev/null
  sleep 1
  LOG_LEVEL=DEBUG nohup uvicorn server.app:app --host 127.0.0.1 --port 3000 > gateway_e2e_server.log 2>&1 &
  disown
  sleep 5
  curl -s http://127.0.0.1:3000/health/live

  # Same client as GATEWAY-E2E-003/004/005 (400 silence frames) --
  # recreate /tmp/gateway_e2e_client.py if it's gone, unchanged from
  # GATEWAY-E2E-003. Run it to completion this time (no backgrounding
  # needed -- just let it finish or time out on its own).
  PYTHONPATH=/workspace/meeting-translator python /tmp/gateway_e2e_client.py > /tmp/gateway_e2e_client.log 2>&1
  cat /tmp/gateway_e2e_client.log

  echo "=== last 20 packet-decoded lines ==="
  grep "packet decoded" gateway_e2e_server.log | tail -20
  echo "=== total packet-decoded line count ==="
  grep -c "packet decoded" gateway_e2e_server.log
  echo "=== teardown counts ==="
  grep "teardown counts" gateway_e2e_server.log
  echo "=== disconnect / idle-timeout lines ==="
  grep -E "client disconnected|idle timeout" gateway_e2e_server.log
  echo "=== ASR activity ==="
  grep "faster_whisper Processing audio" gateway_e2e_server.log

  pkill -f "uvicorn server.app:app"
  ```
- Expected success indicators: This should give a direct count instead
  of inference:
  - If the total `packet decoded` count is far below 475 (e.g. ~45-50)
    -> confirms packets genuinely stop arriving at the server's app
    layer partway through, meaning the problem is below `_handle_packet`
    (transport/ASGI/network layer, or the client not actually sending
    what it appears to send) -- worth knowing the exact last sequence
    number logged.
  - If the count is close to 475 -> means packets *did* all arrive, and
    the earlier "stalled at frame ~45" conclusion (from the partial's
    frozen `end_ms`) needs to be revisited -- something else would be
    silently absorbing them without advancing `end_ms` (a new,
    unexpected finding worth its own follow-up).
  - The disconnect/idle-timeout grep tells us how the session eventually
    ended: server-initiated idle timeout vs. client-initiated close vs.
    neither logged (session possibly still technically open when
    `pkill` ended it).
  Report the actual numbers either way, not just pass/fail.
  Expected artifacts: `gateway_e2e_server.log`, `/tmp/gateway_e2e_client.log`.
- Rollback or cleanup: `pkill -f "uvicorn server.app:app"` if still
  running.
- Return to Claude (secrets/hostnames redacted):
  - The `git log -1 --oneline` output.
  - The client's full printed output.
  - The last-20 `packet decoded` lines and the total count.
  - The teardown-counts line(s).
  - The disconnect/idle-timeout grep output (even if empty).
  - The ASR activity grep output.

### Action ID: GATEWAY-E2E-007

- Status: WAITING_FOR_USER (**result in -- root cause found and fixed
  locally.** See "Root cause" below; a real-hardware re-verification
  action will be staged once the user decides how to proceed on test
  audio -- see the note at the end of this entry.)
- Result (2026-08-16): `"partial decode due"` fired exactly on schedule
  every 500ms all the way from `now_ms=680` through `now_ms=9180` (18
  firings, no gaps) -- the scheduler itself was never the problem. The
  decode trace showed why nothing came of them: decode #3 (at
  `total_ms=900`) computed `boundary_ms=29980` -- a faster-whisper
  hallucination artifact (its internal fixed 30-second processing chunk
  size) on the short/silent audio with `previous_text` conditioning --
  which made `SlidingAudioWindow.advance()` drain the *entire* buffer
  (`buffered_ms_after=0`). Every one of the following 15 due() firings
  then hit `"empty window (total_ms=900)"` -- `total_ms` frozen forever,
  proving `PartialTranscriber.append_audio` had stopped being called
  entirely (not just that the window was trimmed), which only happens
  if the segmenter's `current_utterance_id` became `None`.
  - **Root cause**: `UtteranceSegmenter._finalize()` has an existing,
    intentional "too short" path (`server/vad/state_machine.py`,
    already covered by `tests/test_vad_state_machine.py`'s
    `test_short_utterance_discarded_on_hard_silence`): if hard silence
    is reached but confirmed `speech_ms` never crossed
    `vad_min_speech_ms` (default 250ms), the utterance is silently
    discarded -- `_reset_idle()` with **no event emitted at all**. This
    is correct, deliberate filtering (e.g. a brief noise blip
    shouldn't become a fake utterance) -- but nothing told
    `UtteranceOrchestrator` it happened, so `PartialDecodeScheduler`'s
    entry and `PartialTranscriber`'s state for that `utterance_id` were
    orphaned forever: `due()` kept firing on a phantom utterance for
    the rest of the session, and `decode()` kept hitting its
    now-permanently-empty window on every tick.
  - Separately: `tests/test_e2e_gpu.py` (the *other* GPU e2e test,
    which always passes) feeds `orchestrator.ingest_frame(..., 0.9)`
    with a **hardcoded** probability for every sine-tone frame,
    bypassing real Silero entirely -- it only proves ASR/translation
    wiring, not real VAD behavior. The live-gateway tests use real
    `SileroVadModel.probability()`, and real Silero apparently only
    recognizes a brief speech-like blip at the start of the pure
    220Hz/0.2-amplitude tone (just enough to cross `speech_start_ms` and
    open the utterance) before reading the rest as non-speech -- never
    accumulating the confirmed `speech_ms` needed to avoid the
    too-short discard. This means `utterance.final` was never going to
    appear for this specific synthetic test audio against real VAD,
    independent of the orchestration bug above.
  - **Fix implemented and locally verified** (commit pending push): a
    new `UtteranceAbandoned` VAD event (`server/vad/events.py`) is now
    emitted from the too-short discard path instead of nothing;
    `UtteranceOrchestrator._on_vad_event`
    (`server/orchestration/pipeline.py`) handles it by releasing the
    scheduler entry and partial-transcriber state (mirroring
    `UtteranceFinalized`'s cleanup, minus publishing anything -- the
    client still receives no event for a legitimately-too-short blip,
    by design). Updated the existing state-machine test to assert the
    new event, and added a new orchestration-level regression test
    (`test_abandoned_short_utterance_releases_scheduler_and_partial_state`)
    that directly proves `decode()` stops being invoked after
    abandonment. `ruff format --check .`, `ruff check .`, `mypy client
    server shared` clean; full CPU suite passes (423 passed).
  - **What this fix does and does not resolve**: it closes the real
    resource-leak/orphaned-scheduling bug for any too-short utterance in
    production (a real brief noise blip would previously have caused
    the exact same permanent stall this test hit). It does **not**, by
    itself, make the current GATEWAY-E2E-* test client's sine tone
    produce a real `utterance.final` -- that requires audio real Silero
    will sustain as "speech" for over `min_speech_ms`, which the
    existing synthetic tone was never doing. The next action depends on
    how the user wants to get that real confirmation (louder/different
    synthetic tone vs. a real microphone through the packaged Windows
    client) -- see the question posed in chat; the next `GATEWAY-E2E-*`
    action will be staged once that's decided.
- Original purpose (for history): `GATEWAY-E2E-006` proved all 475 audio frames reached
  `orchestrator.ingest_frame` without exception, yet only 3 real ASR
  decode calls ever happened despite production settings
  (`whisper_partial_interval_ms=500`, `whisper_audio_overlap_ms=1500`)
  that should keep the scheduler firing roughly every 500ms out to
  9500ms (~16-19 expected decodes), and an overlap margin that should
  keep the sliding window from ever emptying out this early. New DEBUG
  logs (commit pending push) trace both remaining decision points
  directly: `UtteranceOrchestrator.run_due_partial_decodes` now logs
  every non-empty `due()` result (utterance ids + the frame-domain
  clock), and `PartialTranscriber.decode()` now logs every skip reason
  (no state, empty window with the buffered ms) as well as every
  successful decode's window-advance outcome and buffered size
  afterward, plus the duplicate-text suppression path. This should show
  definitively whether the scheduler keeps firing (and decode() just
  keeps hitting an empty window) or whether the scheduler itself stops
  firing after the third call.
- Run on: Same host/venv as prior `GATEWAY-E2E-*` actions.
- Prerequisites: `git pull` first -- confirm with `git log -1 --oneline`
  showing the new due()/decode() tracing commit.
- Safety notes: Same as prior attempts (real GPU memory, synthetic sine
  tone only). `LOG_LEVEL=DEBUG` required for these new lines.
- Commands:
  ```bash
  cd /workspace/meeting-translator
  source .venv-asr/bin/activate
  git pull
  git log -1 --oneline   # confirm the due()/decode() tracing commit is present

  pkill -f "uvicorn server.app:app" 2>/dev/null
  sleep 1
  LOG_LEVEL=DEBUG nohup uvicorn server.app:app --host 127.0.0.1 --port 3000 > gateway_e2e_server.log 2>&1 &
  disown
  sleep 5
  curl -s http://127.0.0.1:3000/health/live

  PYTHONPATH=/workspace/meeting-translator python /tmp/gateway_e2e_client.py > /tmp/gateway_e2e_client.log 2>&1
  cat /tmp/gateway_e2e_client.log

  echo "=== partial decode due firings ==="
  grep "partial decode due" gateway_e2e_server.log
  echo "=== partial decode skip/advance/duplicate trace ==="
  grep -E "partial decode skipped|partial decode for|partial decode discarded" gateway_e2e_server.log
  echo "=== ASR activity ==="
  grep "faster_whisper Processing audio" gateway_e2e_server.log

  pkill -f "uvicorn server.app:app"
  ```
- Expected success indicators: Two distinct outcomes are possible, and
  each points somewhere different:
  - If `"partial decode due"` keeps appearing periodically all the way
    up to `now_ms` near 9500, but each is immediately followed by
    `"partial decode skipped for ...: empty window"` -> the scheduler is
    fine; the sliding window is somehow emptying out (a real bug in
    `SlidingAudioWindow`/`advance()` or in how `append_audio` interacts
    with it, contradicting the `overlap_ms=1500` analysis -- worth a
    closer look at the actual `buffered_ms` values logged).
  - If `"partial decode due"` simply stops appearing after the 3rd
    firing (around `now_ms` ~900) and never appears again despite later
    packets clearly still being processed -> the scheduler itself is
    the bug, contradicting the static code reading that found no
    stopping condition -- would need to see the exact `now_ms` values
    logged to spot what's really happening.
  Report the actual line counts and a representative sample either way,
  not just which of the two happened.
  Expected artifacts: `gateway_e2e_server.log` (DEBUG-level, can be
  large -- the three grep excerpts above are what to paste back),
  `/tmp/gateway_e2e_client.log`.
- Rollback or cleanup: `pkill -f "uvicorn server.app:app"` if still
  running.
- Return to Claude (secrets/hostnames redacted):
  - The `git log -1 --oneline` output.
  - The client's full printed output.
  - The full `"partial decode due"` grep output.
  - The full skip/advance/duplicate trace grep output.
  - The ASR activity grep output.

### Action ID: GATEWAY-E2E-008

- Status: WAITING_FOR_USER
- Purpose: `GATEWAY-E2E-007` found and fixed a real orphaned-state bug
  (commit `cff90bd`), but also found that every prior attempt's
  synthetic 220Hz/0.2-amplitude sine tone was likely never going to
  sustain real Silero VAD's "speech" classification past
  `vad_min_speech_ms` (250ms) -- it only ever seemed to register a
  brief blip at onset. This retry does two things at once: confirms the
  fix (the new `UtteranceAbandoned` DEBUG log line, if the tone is
  *still* too short, will now show the exact `speech_ms` accumulated
  instead of silence) and tries harder to get real audio that Silero
  will actually sustain as speech, so `utterance.final` can finally be
  confirmed for real. The client's tone generator is replaced with a
  louder (0.8 amplitude, was 0.2), multi-frequency, amplitude-modulated
  waveform (four rough vowel-formant frequencies -- 180/700/1200/2400 Hz
  -- combined and modulated at ~4 Hz to mimic syllable-rate energy
  variation) instead of a single flat tone, and lengthens the "speech"
  portion from 1.5s to 3s (150 frames) to give more chances for
  confirmed speech to accumulate even if classification is intermittent.
  This is a best-effort synthetic improvement, not real speech -- it may
  still not be enough for Silero; if so, the new DEBUG log line will at
  least show real numbers (exact `speech_ms` reached) to guide the next
  adjustment instead of guessing blind again.
- Run on: Same host/venv as prior `GATEWAY-E2E-*` actions.
- Prerequisites: `git pull` first -- confirm with `git log -1 --oneline`
  showing `cff90bd` or later.
- Safety notes: Same as prior attempts (real GPU memory, synthetic audio
  only, no real recorded speech or personal content).
- Commands:
  ```bash
  cd /workspace/meeting-translator
  source .venv-asr/bin/activate
  git pull
  git log -1 --oneline   # confirm cff90bd or later

  pkill -f "uvicorn server.app:app" 2>/dev/null
  sleep 1
  LOG_LEVEL=DEBUG nohup uvicorn server.app:app --host 127.0.0.1 --port 3000 > gateway_e2e_server.log 2>&1 &
  disown
  sleep 5
  curl -s http://127.0.0.1:3000/health/live

  cat > /tmp/gateway_e2e_client.py << 'EOF'
  import asyncio
  import json
  import math
  import struct
  from datetime import UTC, datetime

  import websockets

  from shared.protocol.binary import AudioFlags, encode_packet
  from shared.protocol.enums import Language, StreamSource
  from shared.protocol.messages import SessionStart, StreamConfig

  FRAME_MS = 20
  SAMPLE_RATE = 16000
  FRAME_SAMPLES = SAMPLE_RATE * FRAME_MS // 1000
  SPEECH_FRAME_COUNT = 150  # 3s -- longer than before, more room to accumulate speech_ms
  SILENCE_FRAME_COUNT = 400  # 8s -- generously past any plausible VAD settling time
  FORMANTS_HZ = (180.0, 700.0, 1200.0, 2400.0)  # rough vowel-formant spacing

  def speech_like_frame(frame_index: int, amplitude: float = 0.8) -> bytes:
      samples = []
      for i in range(FRAME_SAMPLES):
          t = (frame_index * FRAME_SAMPLES + i) / SAMPLE_RATE
          envelope = 0.5 + 0.5 * math.sin(2 * math.pi * 4.0 * t)  # ~4 Hz syllable rate
          value = sum(math.sin(2 * math.pi * f * t) for f in FORMANTS_HZ) / len(FORMANTS_HZ)
          value = max(-1.0, min(1.0, value * amplitude * envelope))
          samples.append(int(value * 32767))
      return struct.pack(f"<{FRAME_SAMPLES}h", *samples)

  def silence_frame() -> bytes:
      return b"\x00\x00" * FRAME_SAMPLES

  async def main() -> None:
      session_start = SessionStart(
          session_id="sess-gateway-e2e-008",
          client_id="gateway-e2e-client",
          timestamp=datetime.now(UTC),
          streams=[
              StreamConfig(
                  stream_number=1,
                  stream_id="mic-01",
                  source=StreamSource.MICROPHONE,
                  source_language=Language.JAPANESE,
                  target_language=Language.VIETNAMESE,
              )
          ],
      )
      async with websockets.connect("ws://127.0.0.1:3000/ws/stream") as ws:
          await ws.send(session_start.model_dump_json())

          seq = 0
          for i in range(SPEECH_FRAME_COUNT):
              packet = encode_packet(
                  stream_number=1, sequence_number=seq, client_timestamp_ms=seq * FRAME_MS,
                  payload=speech_like_frame(i),
              )
              await ws.send(packet)
              seq += 1
          for _ in range(SILENCE_FRAME_COUNT):
              packet = encode_packet(
                  stream_number=1, sequence_number=seq, client_timestamp_ms=seq * FRAME_MS,
                  payload=silence_frame(),
              )
              await ws.send(packet)
              seq += 1

          final_seen = False
          for _ in range(60):
              try:
                  raw = await asyncio.wait_for(ws.recv(), timeout=3)
              except asyncio.TimeoutError:
                  seq += 1
                  await ws.send(
                      encode_packet(
                          stream_number=1, sequence_number=seq,
                          client_timestamp_ms=seq * FRAME_MS, payload=b"",
                          flags=AudioFlags.KEEPALIVE,
                      )
                  )
                  continue
              event = json.loads(raw)
              if event["type"] in ("transcription.partial", "utterance.final", "error"):
                  print(f"{event['type']}: {event}")
              if event["type"] == "utterance.final":
                  final_seen = True
                  break
          if not final_seen:
              print("TIMED OUT waiting for utterance.final")

  asyncio.run(main())
  EOF
  PYTHONPATH=/workspace/meeting-translator python /tmp/gateway_e2e_client.py > /tmp/gateway_e2e_client.log 2>&1
  cat /tmp/gateway_e2e_client.log

  echo "=== abandonment trace (if the tone is still too short) ==="
  grep "abandoned" gateway_e2e_server.log
  echo "=== finalize-path trace (if it actually finalized this time) ==="
  grep -E "finalize task|finalized reason" gateway_e2e_server.log
  echo "=== ASR activity ==="
  grep "faster_whisper Processing audio" gateway_e2e_server.log

  pkill -f "uvicorn server.app:app"
  ```
- Expected success indicators: Two possible outcomes:
  - `utterance.final` actually appears in the client output -> this is
    the real confirmation `GATEWAY-E2E-001` has been chasing for eight
    attempts; the finalize-path trace should show the full sequence
    (finalized reason -> finalize task started -> calling
    final_transcriber.finalize -> got a result), and the client should
    print the real transcription/translation.
  - Still no `utterance.final`, but the abandonment grep now shows a
    line like `"utterance ... abandoned (speech_ms=N < min_speech_ms)"`
    -> the fix is confirmed working (this is a clean, logged outcome
    instead of a silent stall), and `N` tells us exactly how much
    confirmed speech the new tone reached, which is real data to tune
    the next attempt with (report the exact number).
  Either way this is real progress -- report the actual outcome, not
  just pass/fail.
  Expected artifacts: `gateway_e2e_server.log`, `/tmp/gateway_e2e_client.log`.
- Rollback or cleanup: `pkill -f "uvicorn server.app:app"` if still
  running.
- Return to Claude (secrets/hostnames redacted):
  - The `git log -1 --oneline` output.
  - The client's full printed output.
  - The abandonment grep output (even if empty).
  - The finalize-path trace grep output (even if empty).
  - The ASR activity grep output.

### Action ID: GATEWAY-E2E-002

- Status: WAITING_FOR_USER (result in -- `py-spy` itself unusable on
  this host; see below. Superseded by `GATEWAY-E2E-003`, not retried.)
- Result (2026-08-15): `py-spy dump` failed even running as root:
  `Error: Failed to copy Py_Version symbol / Permission denied (os error
  13)`, and `sudo` isn't installed in this container to try harder --
  `ptrace` is blocked at the container level, not a user-permission
  issue `py-spy`'s own fallback could work around. Two other findings
  from this action ARE real and useful, though: `curl -m 5
  http://127.0.0.1:3000/health/live` responded instantly during the
  "stalled" window (the event loop itself is not stuck), and `nvidia-smi`
  showed **0% GPU utilization** (`79639 MiB, 81559 MiB, 0 %`) while GPU
  memory stayed high -- nothing was actually computing. Combined with the
  same 3-partials-then-nothing pattern as attempt 2, this shifted the
  leading hypothesis away from "a hung decode" and toward "the utterance
  never finalizes at all" (real Silero VAD's probability may not drop
  below threshold within the test's silence budget, unlike the scripted
  VAD used everywhere else). `GATEWAY-E2E-003` tests that directly.
- Purpose: `GATEWAY-E2E-001`'s two attempts both got real partial
  transcriptions but never a final event, with the second attempt ruling
  out the idle-timeout explanation from the first. The server log shows
  no error and no traceback -- consistent with the background finalize
  task (a real full-utterance faster-whisper decode, competing for GPU
  with the already-running ~76 GiB-used vLLM server) hanging rather than
  crashing, but this is not confirmed. Get a live look at exactly where
  the server process is stuck, instead of guessing further: `py-spy
  dump` captures every Python (and native) thread's stack in a running
  process without modifying or restarting it.
- Run on: Same host/venv as `GATEWAY-E2E-001`.
- Prerequisites: Same as `GATEWAY-E2E-001`, plus `pip install py-spy`.
  `py-spy` needs ptrace permission to attach to another process -- if it
  reports a permission error, retry with `sudo -E py-spy dump ...` (the
  `-E` preserves the venv's `PATH`/environment) rather than giving up.
- Safety notes: `py-spy dump` is read-only -- it does not pause, modify
  or restart the target process. Same GPU-memory/OOM caveat as
  `GATEWAY-E2E-001` (starting the server loads `large-v3` into GPU memory
  alongside vLLM). Uses the same synthetic sine-tone client, no personal
  audio.
- Commands:
  ```bash
  cd /workspace/meeting-translator   # adjust to the real path on this host
  source .venv-asr/bin/activate
  pip install py-spy

  pkill -f "uvicorn server.app:app" 2>/dev/null   # clear any leftover instance from prior attempts
  sleep 1
  nohup uvicorn server.app:app --host 127.0.0.1 --port 3000 > gateway_e2e_server.log 2>&1 &
  disown
  SERVER_PID=$!
  sleep 5
  echo "server_pid=$SERVER_PID"
  curl -s http://127.0.0.1:3000/health/live

  # Reuses the exact same /tmp/gateway_e2e_client.py from GATEWAY-E2E-001's
  # retry (recreate it first if it's gone -- same script, unchanged).
  python /tmp/gateway_e2e_client.py > /tmp/gateway_e2e_client.log 2>&1 &
  CLIENT_PID=$!

  # Prior attempts went quiet within ~3s of connecting; wait generously
  # longer to be certain we catch it mid-stall, then dump.
  sleep 20
  echo "=== /health/live while (presumably) stalled ==="
  curl -s -m 5 http://127.0.0.1:3000/health/live || echo "health check itself timed out"
  echo "=== py-spy dump of the server process while stalled ==="
  py-spy dump --pid $SERVER_PID || sudo -E py-spy dump --pid $SERVER_PID
  echo "=== nvidia-smi snapshot ==="
  nvidia-smi --query-gpu=memory.used,memory.total,utilization.gpu --format=csv

  # Let the client run to its own natural conclusion (up to ~180s more),
  # then show what it saw and clean up.
  wait $CLIENT_PID
  cat /tmp/gateway_e2e_client.log
  pkill -f "uvicorn server.app:app"
  ```
- Expected success indicators: The `/health/live` check during the
  stalled window either responds promptly (confirms the event loop
  itself is fine, isolated stall in this session's background task) or
  itself times out (confirms a broader event-loop-level stall) -- either
  answer is useful, not a pass/fail. The `py-spy dump` output is the main
  deliverable: look for a thread whose stack is inside
  `faster_whisper`/`ctranslate2`/`torch` C extension code (consistent
  with a stuck GPU decode) versus one waiting on a lock/queue/network
  call (a different kind of stall). `nvidia-smi` showing near-zero GPU
  utilization during the stall would support "hung waiting on something,
  not actively computing"; non-zero utilization would support "genuinely
  still computing, just very slowly under contention."
  Expected artifacts: `gateway_e2e_server.log`, `/tmp/gateway_e2e_client.log`
  (both worth keeping this time, given the open question).
- Rollback or cleanup: `pkill -f "uvicorn server.app:app"` if still
  running.
- Return to Claude (secrets/hostnames redacted):
  - The `server_pid` printed and whether `/health/live` responded during
    the stall or itself timed out.
  - The full `py-spy dump` output (or the exact permission error if it
    failed even with `sudo`).
  - The `nvidia-smi` snapshot.
  - Whatever the client script eventually printed/logged.

## Completed actions

### Action ID: WINDOWS-PACKAGE-001

- Status: PASSED (2026-08-14)
- Result summary: Build completed with no error. The `.exe` launched a
  window titled "Meeting Translator v0.1.0". Device dropdowns populated
  with real input/loopback devices. Connect/Disconnect worked against a
  local dev server with no traceback or freeze, with a Vietnamese-speech
  WAV actively playing for the loopback path. No exception observed.
- Purpose: Verify the packaged Windows client (built via
  `scripts/build_windows_client.py`, real PyInstaller build) actually
  launches and works with real audio hardware and a real local dev server
  connection -- a successful build alone (already confirmed earlier this
  session, see `IMPLEMENTATION_STATUS.md`'s "Phase 11 deliverables") is
  not the same as a hardware-verified running application.
- Run on: Windows PC, real microphone/loopback audio hardware.
- Note: This is a UI/connectivity smoke check only, not evidence of live
  captions -- `UtteranceOrchestrator` is still not wired into the live
  gateway (see "The one gap that matters most" in
  `docs/FINAL_IMPLEMENTATION_REPORT.md`), so no transcription/translation
  output was expected or observed here. Closes out `WINDOWS-PACKAGE-001`.

### Action ID: GPU-E2E-001

- Status: PASSED (2026-08-14), by the test's own loose assertions --
  with a real, separately-tracked finding. See `GPU-E2E-002` (Pending
  actions) for the follow-up diagnostic this motivated.
- Result summary: Attempt 1 SKIPPED (`faster_whisper` not installed in a
  freshly created venv -- Claude's own error in the originally prepared
  command set, corrected). Attempt 2 (retry): `1 passed in 11.13s`.
  `transcription: 'ご視聴ありがとうございました'` (a known
  faster-whisper hallucination on non-speech/synthetic-tone input,
  expected and not a defect). `translation_status: FAILED`,
  `translation: None` -- the real translation leg against the real vLLM
  server genuinely failed. The test's own assertion
  (`translation_status is not None`) is satisfied by `FAILED`, so it
  passed technically, but this is not evidence translation actually
  works end-to-end on real hardware.
- Purpose: First run of `tests/test_e2e_gpu.py` -- proves the real
  `WhisperAsrModel` and real `VllmTranslationClient` are wired correctly
  through a real `UtteranceOrchestrator`.
- Run on: The ASR GPU host, `.venv-asr`.
- Note: Full detail (both attempts) in `USER_RESULTS.md`'s `GPU-E2E-001`
  entries. `GPU-E2E-002` is a small, read-only diagnostic to find out why
  translation failed before `LATENCY-001` (which is on hold until this is
  resolved) runs.

### Action ID: GPU-E2E-002

- Status: PASSED (2026-08-14) -- root cause conclusively found.
- Result summary: `vllm_base_url` resolved correctly
  (`http://localhost:8000/v1`) -- not a config bug. `pgrep -fa "vllm
  serve"` found no process. `curl .../health` returned `http_status=000`
  (connection refused, not a timeout or HTTP error). A direct
  `VllmTranslationClient.complete_chat()` call raised
  `TranslationOverloadedError: All connection attempts failed` -- the
  client correctly classified the raw connection failure, working exactly
  as designed (`classify_backend_error`), not a client bug either.
- Purpose: Find out why `GPU-E2E-001`'s real translation leg returned
  `TranslationStatus.FAILED` against the real vLLM server, since the wire
  protocol doesn't carry the internal failure reason.
- Run on: Same host/venv as `GPU-E2E-001`.
- Note: Root cause is simply that the vLLM server from `GPU-TRANSLATE-005`
  is not currently running on this host -- no code defect anywhere in
  this project. `GPU-TRANSLATE-008` (Pending actions) restarts it.

### Action ID: GPU-TRANSLATE-008

- Status: PASSED (2026-08-14) -- on the user's word only, NOT
  independently verified against specific output. See `GPU-E2E-003`
  (Pending actions) for the follow-up that will conclusively confirm or
  refute this.
- Result summary: Attempt 1: steps 1-4 (recreate `.venv-translate`,
  re-download `Qwen3.6-27B-FP8`, install vLLM, confirm no process) all
  reported OK; step 5's launch hit the expected flashinfer
  `array.array[int]` TypeError; step 6's patch script then crashed with
  the same error, because it located the broken file by importing it --
  which is exactly what triggers the bug. Root cause: Claude's own
  mistake in the originally prepared script, not verified before being
  handed out. Attempt 2 (retry, corrected patch script using a filesystem
  glob instead of an import): user reported "All command is OK. Don't
  have any traceback, error or exception," without pasting the
  `/health` status code, `/v1/models` response, `nvidia-smi` memory line,
  or `vllm_serve.log` excerpt that were requested.
- Purpose: Full rebuild of the translation GPU environment after the user
  found `models/` and `.venv-translate` both missing on the host (likely
  accidental deletion) -- redo of `GPU-TRANSLATE-002` through
  `GPU-TRANSLATE-006` from scratch.
- Run on: The translation GPU host, new `.venv-translate`.
- Note: Attempt 2's missing verification detail was re-sent (2026-08-15):
  `/health` returned `http_status=200`; `/v1/models` matched
  `GPU-TRANSLATE-006` exactly (`qwen3.6-27b-translate`,
  `max_model_len=4096`); `nvidia-smi` showed `75909 MiB / 81559 MiB` used,
  consistent with weights + KV cache, no OOM. This is now fully,
  independently verified -- the earlier caveat no longer applies.
  `GPU-E2E-003` (below) then confirmed real translation actually works
  end-to-end.

### Action ID: GPU-E2E-003

- Status: PASSED (2026-08-15) -- real, meaningful pass: translation
  actually succeeded, not just the test's loose assertion being
  technically satisfied.
- Result summary: `1 passed in 11.02s`, no traceback.
  `transcription: 'ご視聴ありがとうございました'` (same expected
  Whisper hallucination on synthetic-tone input as `GPU-E2E-001`).
  `translation_status: <TranslationStatus.COMPLETED: 'completed'>`.
  `translation: 'Cảm ơn quý vị đã theo dõi.'` -- a correct, fluent
  Vietnamese translation of "thank you for watching," matching the
  Japanese source's meaning exactly.
- Purpose: Re-run `tests/test_e2e_gpu.py` (same test as `GPU-E2E-001`)
  after `GPU-TRANSLATE-008`'s rebuild, to independently confirm real
  translation now works end-to-end rather than relying on the user's
  unelaborated confirmation alone.
- Run on: The ASR GPU host, `.venv-asr`.
- Note: This is the first real, hardware-confirmed proof that the full
  pipeline -- real `WhisperAsrModel` decode, real `VllmTranslationClient`
  translation, both through the real `UtteranceOrchestrator` -- works
  end-to-end on real GPU hardware. `GPU-E2E-001`'s original
  translation-failure finding is fully resolved.

### Action ID: LATENCY-001

- Status: PASSED (2026-08-15) -- the tool's own success criterion (real,
  non-zero percentiles obtained); one real, unresolved finding below.
- Result summary: 20 real runs against real backends
  (`python scripts/latency_report.py --count 20 --real-backends --json`):
  `first_partial_ms` p50=766.7/p95=934.3/p99=3249.6ms,
  `asr_final_ms` p50=92.0/p95=94.2/p99=96.4ms,
  `end_to_end_ms` p50=2317.6/p95=2484.0/p99=4593.1ms,
  `translation_ms_approx` p50=2225.5/p95=2392.1/p99=4517.9ms. Against
  `docs/PRODUCT_REQUIREMENTS.md` section 5's objectives: first partial
  p95 (934.3ms < 1.8s) PASSES; final ASR p95 (94.2ms < 1.2s) PASSES
  comfortably; **translation p95 (2392.1ms) FAILS the <1.2s objective**,
  roughly 2x over budget; end-to-end final p95 (2484.0ms < 3.5s) PASSES,
  though p99 (4593.1ms) exceeds 3.5s. VAD speech-start p95 was not
  measured (documented tool limitation).
- Purpose: Get the first-ever real hardware latency numbers for this
  project.
- Run on: GPU server, `.venv-asr`.
- Note: **First real hardware latency data for this project.** The
  translation-latency miss is plausibly explained by `--enforce-eager`
  (required to work around the `flashinfer` `array.array[int]` bug --
  see `GPU-TRANSLATE-003`/`004`), which disables `torch.compile`/CUDA
  graph capture, already flagged at the time as "slower inference, not a
  correctness issue" -- this is the first measurement quantifying that
  cost, though not root-caused with certainty (no A/B measurement against
  a non-eager launch exists). Also: these numbers come from a single
  short, fixed synthetic utterance repeated 20 times, not a realistic
  distribution of meeting utterance lengths or concurrent load -- a first
  data point, not a comprehensive benchmark. Full detail in
  `USER_RESULTS.md`'s `LATENCY-001` entry.

### Action ID: WINDOWS-UI-007

- Status: PASSED (2026-08-13)
- Result summary: "everything is good. OK. No traceback/error or
  exception." Confirms the `_pump_incoming` fix: Disconnect now updates
  the UI promptly with no delayed reconnect attempt and no server-side
  idle timeout afterward. This closes out the Disconnect-timing bug found
  by `WINDOWS-UI-006`.
- Purpose: Re-verify the `_pump_incoming`/Disconnect-timing fix from
  `WINDOWS-UI-006`.
- Run on: Windows, PC Local.
- Note: This is the last of Phase 09's staged manual-verification
  actions. Across `WINDOWS-UI-001`-`WINDOWS-UI-007`, four real bugs were
  found (via real hardware use, none caught by local checks) and fixed:
  a `websockets` import incompatible with the pinned dependency range; a
  background-thread-crash cleanup gap; a capture-send timer starting
  before the WebSocket handshake completed (causing spurious `jitter
  overflow` warnings); and `_pump_incoming` never noticing `stop` against
  a real, idle transport (causing a Disconnect-time UI freeze and an
  orphaned background thread). All four are now hardware-confirmed fixed.
  The audio capture/enqueue/send pipeline itself was also confirmed
  working correctly for both microphone and loopback, together or
  independently (`WINDOWS-UI-003`/`WINDOWS-UI-004`).

### Action ID: WINDOWS-UI-006

- Status: PASSED (2026-08-13) for its own purpose, with a new finding
  (root-caused and fixed same-turn; see `WINDOWS-UI-007`).
- Result summary: Primary goal confirmed -- "everything is same as
  expected. OK," i.e. no `jitter overflow` warning this time, validating
  the `WINDOWS-UI-005` fix. Separately observed and reported: Disconnect
  took ~5 seconds to update the UI, and ~10 seconds after that the client
  logged `transport closed; will reconnect` while the server logged a new
  session hitting `idle timeout`. Root-caused: `AudioSender._pump_incoming`
  awaited the real transport's `recv()` directly, which blocks
  indefinitely with nothing incoming and never notices `stop` on its
  own; `SessionController.stop()`'s `thread.join(timeout=5.0)` (called
  synchronously from the Qt main thread, explaining the ~5s freeze) gave
  up and silently orphaned the still-running background thread, which
  only actually exited once the server's own 15s idle timeout eventually
  force-closed the connection. Fixed by polling `recv()` with a short
  timeout instead of awaiting it directly (matching the existing
  `_pump_outgoing` pattern), with a new regression test. See
  `WINDOWS-UI-007` for the re-verification.
- Purpose: Re-verify the `jitter overflow` fix from `WINDOWS-UI-005`.
- Run on: Windows, PC Local.
- Note: Full local suite (343 tests, +1 new regression test), ruff and
  mypy re-verified clean after the fix.

### Action ID: WINDOWS-UI-005

- Status: PASSED (2026-08-13) with a new finding (root-caused and fixed
  same-turn; see `WINDOWS-UI-006`).
- Result summary: The diagnostic-logging removal itself was confirmed
  safe: app terminal showed only the two expected `capture started`
  lines (microphone, loopback), no `capture stats` spam, no exceptions.
  However, the server terminal showed two new `WARNING ... lost packets
  (jitter overflow)` lines (5 packets on stream 1, 4 on stream 2) shortly
  after the connection was accepted, followed by a clean `client
  disconnected` at the end -- never observed in any prior action. This is
  a real, separate finding (unrelated to the logging trim itself), fully
  root-caused: `_capture_timer` was starting immediately after
  `session.start()` rather than waiting for the connection to actually
  complete, letting early audio packets get sent once via `AudioSender`'s
  resend-pending step and again via the normal outgoing pump -- a
  duplicate/early-traffic burst that could trip the server's bounded
  jitter-reorder window. Fixed by deferring the capture-send timer's
  start until the first `CONNECTED` state change. See `WINDOWS-UI-006`
  for the re-verification.
- Purpose: Confirm the diagnostic-logging removal (`WINDOWS-UI-004`'s
  follow-up) did not change observable behavior.
- Run on: Windows, PC Local.
- Note: Full local suite (342 tests), ruff and mypy re-verified clean
  after the fix.

### Action ID: WINDOWS-UI-004

- Status: PASSED (2026-08-13) -- hypothesis confirmed, no code bug.
- Result summary: With a Vietnamese-speech WAV actively playing during
  the test, loopback capture worked correctly in both patterns tested:
  (1) loopback only -- `chunks_enqueued`/`frames_produced` climbed
  smoothly over the ~10s test (93 -> 503 chunks, 99 -> 536 frames),
  `frames_sent_total` matching exactly; (2) microphone + loopback
  together -- both sources' counters climbed independently and correctly
  in parallel (mic 85->381 chunks, loopback 94->414 chunks), with
  `frames_sent_total` correctly reflecting the combined running total
  across both sources (the counter is intentionally shared/cumulative,
  not per-source). This conclusively confirms the earlier
  `WINDOWS-UI-003` finding (loopback stuck at zero) was due to no active
  playback during that test -- expected, documented WASAPI loopback
  behavior -- not a defect in `client/ui/main_window.py`,
  `client/audio/capture.py` or `client/audio/windows_backend.py`. The
  audio capture/enqueue/send pipeline is now considered
  `HARDWARE_VERIFIED` for both sources, together or independently.
- Purpose: Confirm or refute the "no active playback" hypothesis from
  `WINDOWS-UI-003` before ruling out a real bug.
- Run on: Windows, PC Local.
- Note: Since the investigation is now closed, the temporary diagnostic
  logging added for it was removed afterward (kept: the one-time
  `capture started` line and `configure_logging()`). See `WINDOWS-UI-005`
  for the resulting final regression check.

### Action ID: WINDOWS-UI-003

- Status: PASSED (2026-08-13) -- diagnostic goal fully achieved.
- Result summary: Microphone pipeline fully confirmed working
  end-to-end: `capture started` logged for both sources at connect time;
  microphone `chunks_enqueued`/`frames_produced` climbed continuously and
  smoothly over the ~10s test (98 -> 535 frames), `frames_sent_total`
  matched exactly at every sample, and the server logged a clean `client
  disconnected` with **no** `idle timeout` this time -- resolving
  `WINDOWS-UI-002`'s finding for the case where audio is actually
  flowing. Loopback opened successfully (`capture started: source=loopback
  device_index=17 ...`, no error) but stayed at
  `chunks_enqueued=0 frames_produced=0` for the entire test. Root-cause
  hypothesis (not yet fully confirmed): WASAPI loopback only delivers
  packets while something is actively playing on that output device;
  `WINDOWS-AUDIO-001` captured real audio from this same device index
  specifically because its prerequisites required active playback, so the
  most likely explanation is that nothing was playing during this test,
  not a code defect. See `WINDOWS-UI-004` for the confirming re-test.
- Purpose: Root-cause `WINDOWS-UI-002`'s idle-timeout finding via
  temporary count-only diagnostic logging rather than guessing.
- Run on: Windows, PC Local.
- Note: No code changes made in response to this result yet -- the
  leading hypothesis does not point to a bug, so `WINDOWS-UI-004`
  confirms it first rather than "fixing" something that likely isn't
  broken.

### Action ID: WINDOWS-UI-002

- Status: PASSED (2026-08-13)
- Result summary: Test A (connect/disconnect with no server running, both
  device-enabled patterns, plus closing the app while connected): button
  and state label updated correctly in all cases, terminal free of
  tracebacks -- confirming both `WINDOWS-UI-001` fixes (the `websockets`
  import and the background-thread-crash cleanup) work as intended. Test
  B (connected smoke test against a local dev server): "connected" was
  reached (first real end-to-end use of the fixed `websockets.connect`
  call), and disconnect-after-connected worked cleanly with no exception.
  Server log showed three sequential sessions, each ending in `idle
  timeout` rather than a clean client-initiated close -- see
  `WINDOWS-UI-003` for the follow-up investigating this (not a failure of
  this action's own stated criteria, but a real, separately-tracked
  finding: it suggests no audio frames reached the server during any of
  the three sessions).
- Purpose: Re-verify the Connect/Disconnect flow after `WINDOWS-UI-001`'s
  two fixes.
- Run on: Windows, PC Local.
- Note: See `WINDOWS-UI-003` for the audio-not-reaching-server
  investigation prompted by the server log's `idle timeout` pattern.

### Action ID: WINDOWS-UI-001

- Status: FAILED (2026-08-12), root-caused and fixed; see `WINDOWS-UI-002`
  for the re-verification of the fix.
- Result summary: The basic (no-server) smoke test fully PASSED: window
  layout, device dropdowns (real hardware devices listed), device/preset/
  checkbox selection, Tab-key keyboard navigation order, caption-list
  accessibility font size, and settings persistence across a relaunch all
  worked exactly as expected -- confirming `client/ui/view_model.py` and
  `client/ui/settings_store.py` (already unit-tested) work correctly when
  driven by the real `client/ui/main_window.py` widgets. The Connect/
  Disconnect flow FAILED in both device-enabled patterns tested, with a
  full traceback returned. Root-caused (not guessed) from that traceback:
  1. **Primary bug**: `client/transport/sender.py`'s `_websockets_connect`
     imported `from websockets.asyncio.client import connect`. That
     submodule only exists starting in `websockets` 13.0 (its rewritten
     implementation); this project pins `websockets>=12,<13`
     (`pyproject.toml`), and the user's installed 12.x package has no
     `websockets.asyncio` submodule at all --
     `ModuleNotFoundError: No module named 'websockets.asyncio'` on every
     connection attempt. This code path was never exercised by any
     automated test (all Phase 03 tests use a fake `Transport`), so
     nothing caught it before this first real-hardware run. Fixed by
     switching to the always-available top-level `websockets.connect`
     entry point, which is stable across the pinned range (no dependency
     version bump needed).
  2. **Secondary bug** (the actual cause of the "freezing"/repeated
     tracebacks and the button never reverting): when the background
     `AudioSender.run()` coroutine raised an uncaught exception (the bug
     above), `SessionController`'s background thread died, but neither
     `SessionController` nor `MainWindow` detected this -- `self._loop`
     still referenced the now-closed event loop, and `self._session`
     was never cleared. Every subsequent 20ms capture-timer tick then
     called `session.send_audio(...)` -> `loop.call_soon_threadsafe(...)`
     on a closed loop, raising `RuntimeError: Event loop is closed`
     repeatedly (the traceback flood the user saw); clicking Disconnect
     or closing the window hit the same dead loop via `session.stop()`
     before reaching the cleanup code that resets the button/state label,
     so neither ever happened. Fixed: `SessionController.is_running` now
     checks `Thread.is_alive()` (not just "was started"); `stop()` and
     `send_audio()` no longer touch a dead loop; a new `on_fatal_error`
     callback reports the failure exactly once and
     `MainWindow._drain_capture` catches the resulting clean
     `RuntimeError` to auto-stop the session (timer, capture streams,
     button text, state label) instead of raising on every tick.
- Purpose: First manual verification of the real PySide6 caption UI.
- Run on: Windows 10/11, PC Local.
- Note: 4 new regression tests added in `tests/test_ui_session_controller.py`
  covering the crash-and-recover behavior (a background thread that dies
  from an unhandled exception reports it via `on_fatal_error`,
  `is_running` becomes `False`, `stop()` no longer raises, and
  `send_audio()` afterward raises one clean `RuntimeError` instead of the
  underlying asyncio error). Full local suite (342 tests), ruff and mypy
  all re-verified clean after the fix. See `WINDOWS-UI-002` for hardware
  re-verification.

### Action ID: GPU-TRANSLATE-007

- Status: PASSED (2026-08-12)
- Result summary: Both requests returned `200 OK` with no
  exception/traceback. JA->VI: source "来週のリリースについて確認したいで
  す。" -> translated "Tôi muốn xác nhận về bản phát hành vào tuần tới." VI
  ->JA: source "Tôi muốn xác nhận về đợt phát hành vào tuần tới." ->
  translated "来週のリリースについて確認したいのですが。" Both outputs are
  non-empty, correctly scripted (Vietnamese with diacritics; Japanese
  kana/kanji), carry no forbidden-prefix label and show no pathological
  repetition. vLLM engine log confirms real generation occurred (non-zero
  generation throughput, `GPU KV cache usage: 0.5%`) rather than an empty/
  cached response. Claude's own linguistic assessment (fluent in both
  languages): both translations are accurate and natural renderings of the
  source meaning ("I'd like to confirm about next week's release") in each
  direction. Note: the user's raw command output did not include an
  explicit first-person plausibility verdict (unlike `GPU-ASR-005`'s "yes,
  the printed text is a roughly accurate rendering"); this PASSED
  determination rests on the technical success indicators plus Claude's
  linguistic read of the output, not an explicit user judgment call. Flag
  to the user if either translation reads as wrong to a native speaker.
- Purpose: First real-translation, real-code-path check -- the last of
  this phase's staged GPU checkpoints. Exercised the project's own prompt
  builder (`server/translation/prompts.py`) against the running vLLM
  server in both directions using `TranslationConfig`'s documented
  defaults (temperature 0, top-p 1, non-thinking mode).
- Run on: Same host as `GPU-TRANSLATE-001`-`GPU-TRANSLATE-006`.
- Note: This closes out Phase 07's staged GPU checkpoint sequence. No
  further translation-specific manual action is currently pending; wiring
  `FinalTranslator` into the live gateway/VAD/ASR pipeline and any
  completeness-classification consumer remain Phase 08's scope.

### Action ID: GPU-TRANSLATE-006

- Status: PASSED (2026-08-12)
- Result summary: `/health` returned `http_status=200`. `/v1/models`
  returned a well-formed OpenAI-compatible listing:
  `id=qwen3.6-27b-translate`, `root=/workspace/meetting-translator/models/Qwen3.6-27B-FP8`,
  `max_model_len=4096` -- matching the launch config exactly. No error,
  timeout or unexpected status.
- Purpose: First HTTP-level confirmation the running server answers
  OpenAI-compatible requests and serves the expected model name.
- Run on: Same host as GPU-TRANSLATE-001-005.
- Note: See GPU-TRANSLATE-007 for the first real translation request
  through the project's own prompt-building code.

### Action ID: GPU-TRANSLATE-005

- Status: PASSED (2026-08-12)
- Result summary: Step 1 confirmed no lingering process. Step 2 (patch)
  printed `patched OK`. Steps 3-4: server started cleanly --
  "Started server process", "Waiting for application startup.",
  "Application startup complete.", "API server: HTTP server started". No
  traceback. Step 5: `nvidia-smi` reports `72237 MiB / 81559 MiB` used --
  consistent with weights (~27.67 GiB) + KV cache (~41.03 GiB) both loaded,
  no OOM.
- Purpose: Patch the broken `flashinfer` line directly (fixes every import
  path that hits it, not just the one `--enforce-eager` avoided), then
  relaunch.
- Run on: Same host as GPU-TRANSLATE-001-004.
- Note: This is the first successful vLLM server start. See
  GPU-TRANSLATE-006 for the first HTTP-level confirmation
  (`/health`, `/v1/models`) that the server actually responds and serves
  the expected model name.

### Action ID: GPU-TRANSLATE-004

- Status: FAILED (2026-08-12)
- Result summary: Real progress this time. With `--enforce-eager`, model
  construction succeeded: weights loaded in 23.7s (27.67 GiB), KV cache
  computed (41.03 GiB available, 292,522 tokens, 71.42x max concurrency at
  4096 tokens/request) -- the exact `TorchCompileWithNoGuardsWrapper` crash
  from GPU-TRANSLATE-003 did not recur. However, `EngineCore` then still
  crashed with the identical `TypeError: type 'array.array' is not
  subscriptable` in `flashinfer/comm/fd_exchange.py`, reached via a
  *different* import chain this time:
  `_initialize_kv_caches()` -> `compile_or_warm_up_model()` ->
  `kernel_warmup()` -> unconditionally imports
  `vllm.model_executor.warmup.minimax_m3_msa_warmup` (MiniMax-M3-specific
  warmup code, unrelated to the Qwen3.5 model actually being served) ->
  `vllm.model_executor.layers.fused_allreduce_gemma_rms_norm` ->
  `vllm.compilation.passes.fusion.allreduce_rms_fusion` ->
  `flashinfer.comm` -> same broken `fd_exchange.py` line.
- Purpose: Retry the vLLM launch with `--enforce-eager` to route around the
  GPU-TRANSLATE-003 crash.
- Run on: Same host as GPU-TRANSLATE-001/002/003.
- Note: Since a second, independent code path hit the identical underlying
  bug, and more such paths may exist, GPU-TRANSLATE-005 patches the actual
  broken line in the installed `flashinfer` package directly (a one-line,
  behavior-preserving fix: quoting an invalid type annotation so it is
  never evaluated) instead of continuing to chase individual import paths.

### Action ID: GPU-TRANSLATE-003

- Status: FAILED (2026-08-12)
- Result summary: `pip install vllm` (command 1) completed normally. The
  `nohup vllm serve ...` launch (command 2) crashed during model
  construction, before any GPU memory was meaningfully used for inference
  (`EngineCore failed to start`). Root cause, confirmed by reading the
  traceback plus vLLM's own source on GitHub: vLLM's `torch.compile`
  backend setup (triggered unconditionally during model construction, not
  gated by anything project-specific) imports `vllm.compilation.backends`
  -> `PostGradPassManager` -> `AllReduceFusionPass` ->
  `flashinfer.comm` -> ... -> `flashinfer/comm/fd_exchange.py`, whose
  module-level code defines a function with the return-type annotation
  `array.array[int]`. `array.array` does not support `__class_getitem__`
  (subscripting), so this raises
  `TypeError: type 'array.array' is not subscriptable` at import time,
  unconditionally -- a genuine third-party bug in the installed
  `flashinfer` package, not caused by this project's code, the model
  download, or the host environment. Commands 3-4 (log tail, `nvidia-smi`
  check) were not meaningful to run since the server process had already
  exited.
- Purpose: Install `vllm` and launch it as an OpenAI-compatible server over
  the downloaded weights via bare-process `vllm serve`.
- Run on: Same host as GPU-TRANSLATE-001/002.
- Note: See GPU-TRANSLATE-004 for the retry with `--enforce-eager`, which
  (per vLLM's own conditional logic in `vllm/compilation/decorators.py`)
  skips the exact code path that imports the broken `flashinfer.comm`
  module.

### Action ID: GPU-TRANSLATE-002

- Status: PASSED (2026-08-12)
- Result summary: Downloaded `Qwen/Qwen3.6-27B-FP8` (80 files, ~8m11s,
  ~21.6-193MB/s) to
  `/workspace/meetting-translator/models/Qwen3.6-27B-FP8`. Resolved
  revision `e89b16ebf1988b3d6befa7de50abc2d76f26eb09`. `du -sh` reports 29G
  on disk (consistent with the officially published ~30.9 GB; the
  difference is normal GiB-vs-GB/filesystem-accounting variance, not a
  partial download -- the download tool itself reported "30.9GB / 30.9GB"
  complete). No exception/traceback.
- Purpose: Download the official weights into a persistent path, in a new
  `.venv-translate` kept separate from `.venv-asr`, and record the
  resolved revision/size.
- Run on: Same host as GPU-TRANSLATE-001.
- Note: See GPU-TRANSLATE-003 for installing and launching vLLM over these
  weights.

### Action ID: GPU-TRANSLATE-001

- Status: PASSED (2026-08-12)
- Result summary: Run on `/workspace/meetting-translator` -- the same
  physical host as the ASR GPU work (`GPU-ASR-001`-`GPU-ASR-005`), single
  GPU: NVIDIA H100 80GB HBM3, 0 MiB used, driver 580.82.07, CUDA (driver)
  13.0, nvcc 12.8. Host: 128 CPUs, 1.5 TiB RAM (596 GiB free). Disk:
  `/workspace` PVC 300G total, 155G avail. Step 5 (Docker check) was
  intentionally skipped -- user intends the bare-process `vllm serve`
  launch path, which does not need Docker. No errors observed.
- Purpose: Inspect the translation GPU host (read-only) to confirm it can
  host `Qwen3.6-27B-FP8` via vLLM before any download or launch. Installs
  nothing, downloads nothing, runs no inference.
- Run on: Translation GPU host (confirmed same host as ASR).
- Note: This host has only one GPU (H100 80GB), the same one already used
  for ASR -- see the follow-up analysis in `USER_RESULTS.md` for why 80GB
  is treated as sufficient headroom for both models despite
  `docs/ARCHITECTURE.md`'s general caution against assuming Whisper and
  Qwen safely coexist on one GPU. See GPU-TRANSLATE-002 for the model
  download.

### Action ID: GPU-ASR-005

- Status: PASSED (2026-08-12)
- Result summary: Ran against real `vi_sample.wav` (28s) and `ja_sample.wav`
  (20s). No exception for either language; `segments > 0` for both (7 and
  8); output was fluent, coherent text in each language. User confirmed:
  "yes, the printed text is a roughly accurate rendering of what i said" —
  satisfying the action's ground-truth plausibility criterion for both
  clips. GPU ASR is now hardware-verified for the ASR adapter itself
  (real speech, real project code path, both target languages).
- Purpose: First real-speech, real-code-path check. Exercises the project's
  own `WhisperAsrModel` adapter (`server/asr/whisper.py`) — not the bare
  `faster_whisper` library — against short genuine speech samples in both
  target languages (`vi`, `ja`), using the project's documented `AsrConfig`
  defaults from `.env.example` (`large-v3`, `cuda`, `float16`,
  `final_beam_size=3`, `temperature=0.0`, `condition_on_previous_text=True`).
  This is a plausibility check ("is the transcribed text roughly what was
  said"), not a scored accuracy benchmark — that is separate, later work.
- Run on: GPU ASR server, inside the existing venv at
  `/workspace/meetting-translator/.venv-asr`, from the project root
  `/workspace/meetting-translator` (so `server`/`shared` import correctly).
- Prerequisites:
  - GPU-ASR-004 PASSED (confirmed below): `large-v3` loads and decodes on
    this GPU with no CUDA/cuDNN/cuBLAS error.
  - Two short (~5-10s) WAV recordings of clear, real speech: one Vietnamese,
    one Japanese, each mono / 16-bit / 16000 Hz. The easiest way to get a
    correctly-formatted file is the already-verified capture tool from
    WINDOWS-AUDIO-001, run on your Windows client while actually speaking a
    short sentence:
    `python -m client.audio.wav_cli capture --source microphone --seconds 8 --out vi_sample.wav`
    (repeat in Japanese for `ja_sample.wav`). Any other mono/16-bit/16000 Hz
    WAV of clear speech works too.
  - Those two WAV files copied onto the GPU host into
    `/workspace/meetting-translator/` as `vi_sample.wav` and `ja_sample.wav`
    (transfer method is up to you / your normal way of copying files onto
    this pod — not prescribed here).
- Safety notes: Reads two local WAV files and runs two inference calls
  through the already-installed venv. Does not modify the venv, drivers,
  containers, services, firewall or permissions, and downloads nothing new.
  The recorded speech is a throwaway test utterance, not real meeting
  content — please say something innocuous (e.g. count or read a sentence
  aloud) since the transcribed text will be pasted back into this chat, and
  avoid recording anything sensitive.

Commands (run on the GPU ASR host, with the venv active, from the project root):

```bash
source /workspace/meetting-translator/.venv-asr/bin/activate
cd /workspace/meetting-translator

# 1. Write a script that uses the project's real ASR adapter and config,
#    not bare faster_whisper.
cat > /tmp/asr_real_speech_test.py << 'EOF'
import wave
from server.asr.types import AsrConfig, AsrRequest
from server.asr.whisper import WhisperAsrModel
from shared.protocol.enums import Language


def load_pcm(path: str) -> bytes:
    with wave.open(path, "rb") as wf:
        if wf.getnchannels() != 1 or wf.getsampwidth() != 2 or wf.getframerate() != 16000:
            raise ValueError(
                f"{path}: expected mono/16-bit/16000Hz, got "
                f"channels={wf.getnchannels()} sampwidth={wf.getsampwidth()} "
                f"framerate={wf.getframerate()}"
            )
        return wf.readframes(wf.getnframes())


config = AsrConfig(
    model="large-v3",
    device="cuda",
    compute_type="float16",
    final_beam_size=3,
    temperature=0.0,
    condition_on_previous_text=True,
)
model = WhisperAsrModel(config)

for language, filename in [(Language.VIETNAMESE, "vi_sample.wav"), (Language.JAPANESE, "ja_sample.wav")]:
    audio = load_pcm(filename)
    request = AsrRequest(
        audio=audio,
        language=language,
        beam_size=config.final_beam_size,
        temperature=config.temperature,
        condition_on_previous_text=config.condition_on_previous_text,
    )
    result = model.transcribe(request)
    print(f"--- {language.value} ({filename}) ---")
    print(f"duration_ms={result.duration_ms}")
    print(f"segments={len(result.segments)}")
    print(f"text={result.text!r}")
EOF

# 2. Run it, keeping stderr visible for any error.
PYTHONPATH=/workspace/meetting-translator python /tmp/asr_real_speech_test.py
```

Expected success indicators:
- No exception/traceback for either language.
- `segments` > 0 for both.
- The printed `text` for `vi_sample.wav` is plausible, readable Vietnamese
  (with diacritics) roughly matching what was actually said; the printed
  `text` for `ja_sample.wav` is plausible, readable Japanese (kana/kanji)
  roughly matching what was actually said. You are the ground truth judge —
  this is a rough sanity check, not automated scoring.

Expected artifacts:
- None permanent. `/tmp/asr_real_speech_test.py` is temporary.

Rollback or cleanup:
- `rm /tmp/asr_real_speech_test.py`. Delete the WAV fixture files if desired
  (`vi_sample.wav`, `ja_sample.wav`).

Return to Claude (with secrets/sensitive paths redacted):
- Exact commands used and their exit status.
- Full stdout for both languages (the printed `text` fields), plus your own
  judgment of whether each is a roughly correct/plausible transcription of
  what you actually said.
- Any exception/traceback.

Received output: No exception for either language. `vi_sample.wav`:
`duration_ms=28000 segments=7`, fluent coherent Vietnamese (company profile
passage). `ja_sample.wav`: `duration_ms=20000 segments=8`, fluent coherent
Japanese (textbook sentence-pattern examples). User confirmed (2026-08-12):
"yes, the printed text is a roughly accurate rendering of what i said."
Full text recorded in `USER_RESULTS.md`.

Note: This was a plausibility check on two short clips, not a scored
accuracy benchmark. Broader accuracy/latency benchmarking across more
samples, and wiring `FinalTranscriber` into the live gateway/VAD path, are
separate, later work.

### Action ID: GPU-ASR-004

- Status: PASSED (2026-08-11)
- Result summary: `large-v3` loaded in 3.66s and decoded a synthetic 3s tone
  in 0.29s with no exception — real model weights, real GPU compute, no
  CUDA/cuDNN/cuBLAS load error. This resolves the open question left by
  GPU-ASR-003 (missing `libcudnn` in `ldconfig`): whatever the dependency
  resolution path, it works end-to-end on this host. Detected language/
  probability and segment count on the tone are not meaningful (no real
  speech in the input) and were expected to be arbitrary. Model revision
  recorded: `Systran/faster-whisper-large-v3` @
  `edaa852ec7e145841d8ffdb056a99866b5f0a478`, 3090835702 bytes (~2.88 GiB) on
  disk.
- Purpose: First real GPU decode (model load + one inference call) to prove
  the actual codepath works, not just CUDA device enumeration.
- Run on: GPU ASR server, `/workspace/meetting-translator/.venv-asr`.
- Note: See GPU-ASR-005 for the first real-speech, real-adapter-code test.

### Action ID: GPU-ASR-003

- Status: PASSED (2026-08-11)
- Result summary: `ctranslate2` 4.8.1 installed and `cuda_device_count()`
  returned 1 — CTranslate2 (the library `faster-whisper` actually delegates
  GPU execution to) successfully sees the H100. Active Python/pip confirmed
  inside `/workspace/meetting-translator/.venv-asr` (note: the real venv path
  has an extra path segment — `meetting-translator`, not `/workspace`
  directly — earlier actions' assumed path is corrected in GPU-ASR-004).
  `faster-whisper` 1.2.1 and `ctranslate2` 4.8.1 both present in `pip list`.
  `nvidia-smi` shows the same idle H100 as GPU-ASR-001. `libcudart`/
  `libcublas`/`libcublasLt` resolved via `ldconfig`; no `libcudnn` entry
  appeared in that listing, but per this action's own stated success
  criteria a missing `ldconfig` match is only disqualifying when
  `cuda_device_count` is 0, which it was not — so this is not treated as a
  failure here. It is flagged as an open risk for GPU-ASR-004 (first real
  model load/decode) to either confirm is harmless (e.g. cuDNN bundled
  inside the `ctranslate2` wheel rather than resolved via system
  `ldconfig`) or surface as a load-time error.
- Purpose: Re-check GPU visibility through the library faster-whisper
  actually uses (`ctranslate2`), after GPU-ASR-002's flawed `torch` check.
- Run on: GPU ASR server, `/workspace/meetting-translator/.venv-asr`.
- Note: See GPU-ASR-004 for the first real model-load/decode test that
  resolves the open cuDNN-visibility question.

### Action ID: GPU-ASR-002

- Status: INCONCLUSIVE (2026-08-11)
- Result summary: `faster-whisper` 1.2.1 installed successfully. The prepared
  diagnostic additionally tried `import torch`, which failed with
  `ModuleNotFoundError` — but this was a flaw in the action as written, not a
  real failure signal: `faster-whisper` executes inference through
  CTranslate2, and the project's `pyproject.toml` `gpu` extra pins only
  `faster-whisper>=1.0,<2` with no PyTorch requirement. GPU visibility for the
  library `faster-whisper` actually uses was not checked by this action.
  Superseded by GPU-ASR-003, which checks `ctranslate2` directly.
- Purpose: Install only the faster-whisper GPU inference stack (not the full
  `gpu` extra, since translation may run on a separate GPU per
  `docs/ARCHITECTURE.md`) into a persistent virtual environment on the ASR GPU
  host, and confirm CUDA is visible to the installed PyTorch build. Installs
  packages only; downloads no model weights and runs no inference.
- Run on: GPU ASR server (same host as GPU-ASR-001: H100 80GB, driver
  580.82.07, CUDA 13.0, Python 3.11.13, containerized/Kubernetes pod with a
  persistent `/workspace` PVC mount).
- Prerequisites:
  - GPU-ASR-001 PASSED (confirmed below).
  - Project source copied to the GPU host under `/workspace` (or another path
    on the persistent PVC, not the ephemeral container overlay, so the venv
    survives a pod restart).
  - Outbound network access to PyPI (or an internal mirror) from the host.
- Safety notes: Installs Python packages into a new, isolated virtual
  environment only. Does not touch system Python, drivers, CUDA toolkit,
  containers, services, firewall or permissions. Does not download model
  weights. Do not paste secrets, tokens or full hostnames; redact as needed.

Commands (run on the GPU ASR host, from the project root under `/workspace`):

```bash
# 1. Create a persistent virtual environment on the PVC-backed path.
python3 -m venv /workspace/.venv-asr
source /workspace/.venv-asr/bin/activate

# 2. Upgrade packaging tools.
python -m pip install --upgrade pip

# 3. Install only the ASR inference dependency (pinned per pyproject.toml's
#    `gpu` extra: faster-whisper>=1.0,<2).
pip install "faster-whisper>=1.0,<2"

# 4. Confirm the installed stack imports.
python -c "import faster_whisper; print('faster_whisper', faster_whisper.__version__)"
```

Expected artifacts:
- `/workspace/.venv-asr/` virtual environment (persistent on the PVC). No
  model weights are downloaded by this action.

Rollback or cleanup:
- `rm -rf /workspace/.venv-asr` removes the environment; no other system
  state is changed.

Note: See GPU-ASR-003 for the corrected GPU-visibility diagnostic.

### Action ID: GPU-ASR-001

- Status: PASSED (2026-08-10)
- Result summary: NVIDIA H100 80GB HBM3, 0 MiB used / 81559 MiB total, driver
  580.82.07, CUDA (driver) 13.0, nvcc 12.8 (CUDA 12.8 toolkit). Host: 128
  logical CPUs, 1.5 TiB RAM (696 GiB free). Disk: container overlay 24T
  (18T avail), persistent `/workspace` PVC mount 300G (156G avail). Python
  3.11.13. Host is a containerized/Kubernetes pod (nvidia-fabricmanager
  socket, PVC-backed `/workspace`, overlay root filesystem) rather than bare
  metal — noted for later steps so installs/venvs target the persistent PVC
  path, not the ephemeral overlay. No errors observed.
- Purpose: Inspect the user-managed ASR GPU environment (read-only) to confirm
  it can host faster-whisper large-v3 before any model install or inference is
  prepared. This action installs nothing and runs no inference.
- Run on: GPU ASR server (the host that will run faster-whisper).
- Prerequisites:
  - A shell on the ASR GPU host.
  - `nvidia-smi` available (NVIDIA driver installed).
  - Python 3.11+ available (for the version check only).
- Safety notes: Read-only inspection. Does not install packages, download
  weights, change drivers, containers, services, firewall or permissions. Do
  not paste secrets, tokens or full hostnames; redact as needed.

Commands (run on the GPU ASR host):

```bash
# 1. GPU model, VRAM, driver and CUDA runtime version.
nvidia-smi

# 2. CUDA toolkit compiler version, if present (optional).
nvcc --version 2>/dev/null || echo "nvcc not on PATH (optional)"

# 3. Host CPU/RAM summary.
#    Linux:
free -h ; nproc
#    (Windows host alternative: systeminfo | findstr /C:"Total Physical Memory")

# 4. Free disk space where model weights will live (large-v3 ~ 3 GB).
df -h .

# 5. Python version available for the ASR service.
python3 --version 2>/dev/null || python --version
```

Expected success indicators:
- Step 1 prints at least one NVIDIA GPU with its total memory, driver version
  and the CUDA version supported by the driver.
- Step 3 shows the available system RAM and CPU count.
- Step 4 shows sufficient free disk (several GB) for model weights and cache.
- Step 5 reports Python 3.11 or newer.

Expected artifacts:
- None. Read-only; no files are created.

Rollback or cleanup:
- None required; no changes are made.

Return to Claude (with secrets/sensitive paths redacted):
- Exact commands used and their exit status.
- Full stdout/stderr of steps 1 and 3-5 (step 2 optional), with any tokens,
  private hostnames or personal paths redacted.
- The `nvidia-smi` GPU model, total VRAM, driver version and CUDA version.
- Any observed error, missing tool or insufficient resource.

Note: This is inspection only. Model installation and inference are separate,
later action IDs (e.g. GPU-ASR-002+) and must not begin until this action's
output is returned and analyzed.

### Action ID: WINDOWS-AUDIO-001

- Status: PASSED (2026-08-10)
- Result summary: Device enumeration listed 8 input devices and 2 loopback
  devices. Microphone capture wrote `mic_test.wav` (158720 bytes, 248 frames,
  dropped=0). Loopback capture on device 17 wrote `loopback_test.wav`
  (159360 bytes, 249 frames, dropped=0). No errors observed.
- Purpose: Verify Windows audio device enumeration and short microphone/loopback
  WAV capture using the PyAudioWPatch backend. Confirms real devices are found
  and captured audio normalizes to mono 16 kHz PCM S16LE.
- Run on: Windows 10/11 machine with a working microphone and audio output.
- Prerequisites:
  - This project directory copied to the Windows machine.
  - Python 3.11+ available.
  - A meeting/audio app or media playing during the loopback capture so the
    loopback WAV is not silent.
- Safety notes: Local-only, non-destructive. No GPU server involved. Do not
  paste secrets. Captured WAV files may contain audio content; keep them local
  and do not attach raw audio here.

Commands (PowerShell, from the project root on Windows):

```powershell
# 1. Create/activate a virtual environment and install client + windows-audio deps.
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -e ".[client]"
pip install -e ".[windows-audio]"

# 2. Enumerate microphone and loopback devices.
python -m client.audio.wav_cli list

# 3. Capture ~5s from the default microphone (speak during capture).
python -m client.audio.wav_cli capture --source microphone --seconds 5 --out mic_test.wav

# 4. Capture ~5s of system loopback (play audio during capture).
#    Use a --device index from the loopback list above if the default is wrong.
python -m client.audio.wav_cli capture --source loopback --seconds 5 --out loopback_test.wav

# 5. (Optional) Run the Windows-only integration tests.
pip install -e ".[dev]"
pytest -m windows_audio
```

Expected success indicators:
- Step 2 prints at least one input device and at least one loopback device.
- Steps 3 and 4 print a non-zero byte count and `frames > 0`, and produce
  `mic_test.wav` / `loopback_test.wav`.
- The WAV files are mono, 16000 Hz, 16-bit and audibly contain the captured
  audio (microphone speech / played system audio).
- Step 5 (if run) reports the `windows_audio` tests passing.

Expected artifacts:
- `mic_test.wav`, `loopback_test.wav` (keep local; do not upload raw audio).

Rollback or cleanup:
- Delete the generated WAV files. No system changes are made.

Return to Claude (with secrets/sensitive paths redacted):
- Exact commands used.
- Full stdout/stderr of steps 2-4 (and step 5 if run).
- For each WAV: file size, and confirmation of format (mono / 16000 Hz / 16-bit)
  and whether audio is audible. Do not attach the raw audio itself.
- Any observed errors or missing devices.

## Rules

- Mỗi action có ID duy nhất.
- Chỉ người dùng thực hiện thao tác GPU server.
- Claude phải dừng khi action có trạng thái `WAITING_FOR_USER` và kết quả là dependency cho bước tiếp theo.
- Sau khi nhận output, Claude cập nhật action thành `PASSED`, `FAILED` hoặc `NEEDS_MORE_INFO`.
