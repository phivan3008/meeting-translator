# Manual Actions

Claude ghi các thao tác mà người dùng cần thực hiện tại đây.

## Pending actions

One action to rebuild the translation GPU environment from scratch
(`GPU-TRANSLATE-008` -- originally staged as a simple restart, expanded
after the user confirmed `models/` and `.venv-translate` are both gone
from that host) plus one action from Phase 11's original staging
(`LATENCY-001`, on hold -- see below). Neither is required to close out
Phase 11's own local scope. `WINDOWS-PACKAGE-001`, `GPU-E2E-001` and
`GPU-E2E-002` have all PASSED -- see "Completed actions" below
(`GPU-E2E-002`'s diagnostic is what first found that the vLLM server
simply wasn't running, which the user then traced to the underlying
`models/`/`.venv-translate` loss).

### Action ID: GPU-TRANSLATE-008

- Status: WAITING_FOR_USER
- Purpose: Originally staged as a simple restart, but the user has since
  confirmed both `models/` (containing the downloaded `Qwen3.6-27B-FP8`
  weights from `GPU-TRANSLATE-002`) and `.venv-translate` are gone from
  the GPU host -- likely accidentally deleted. This is now a full redo of
  `GPU-TRANSLATE-002` through `GPU-TRANSLATE-006` from scratch: recreate
  the venv, re-download the weights, reinstall vLLM, relaunch (including
  the known venv-scoped `flashinfer` `array.array[int]` import-time bug
  and its patch -- see `docs/OPERATOR_RUNBOOK_SEED.md`'s "Prerequisites
  and GPU compatibility"; a fresh `pip install vllm` will very likely hit
  it again since the patch does not survive a reinstall), then verify.
  ASR is unaffected -- `.venv-asr` and the `large-v3` weights are
  confirmed still present and working (`GPU-E2E-001`/`GPU-E2E-002` both
  ran successfully against them this session).
- Run on: The translation GPU host (same physical host as ASR, per
  `GPU-TRANSLATE-001`).
- Prerequisites: Outbound network access to Hugging Face (or an internal
  mirror). Enough free disk for the ~30.9 GB weights (confirm with
  `df -h .` first -- `GPU-TRANSLATE-002` needed this much and more was
  free at the time, but don't assume that's still true). Confirm the
  project's real root path with `pwd`/`ls` before using the placeholder
  path below -- prior sessions' docs inconsistently spelled it
  `meetting-translator` vs `meeting-translator`, and this session's own
  ASR-side commands resolved the single-"t" spelling, but don't assume
  that carries over here without checking.
- Safety notes: Downloads real model weights (~30.9 GB) and installs real
  packages (`vllm` and its dependencies, a large install) into a new,
  isolated venv -- does not touch `.venv-asr`, the `large-v3` weights, or
  any other part of the host. Starts a real, resource-heavy background
  process (~72 GB GPU memory once loaded, per `GPU-TRANSLATE-005`'s
  precedent). This will take a while end to end (weights download was
  ~8 minutes previously; `pip install vllm` and first model load add
  more) -- there is no need to babysit it in real time, just check back
  and paste the results.
- Commands:
  ```bash
  cd /workspace/meeting-translator   # adjust to the real path on this host -- verify with `pwd`/`ls` first
  df -h .                             # confirm enough free disk for ~30.9 GB before downloading

  # 1. Recreate the translation venv (matching GPU-TRANSLATE-002's setup).
  python3 -m venv .venv-translate
  source .venv-translate/bin/activate
  python -m pip install --upgrade pip
  pip install "huggingface_hub[cli]>=0.24"

  # 2. Re-download the weights, resolving and printing the revision SHA
  #    (matching GPU-TRANSLATE-002's precedent).
  cat > /tmp/download_qwen.py << 'EOF'
  from huggingface_hub import HfApi, snapshot_download

  REPO_ID = "Qwen/Qwen3.6-27B-FP8"
  TARGET_DIR = "models/Qwen3.6-27B-FP8"

  api = HfApi()
  info = api.model_info(REPO_ID)
  print(f"repo_id={REPO_ID} revision_sha={info.sha}")

  path = snapshot_download(repo_id=REPO_ID, revision=info.sha, local_dir=TARGET_DIR)
  print(f"downloaded to {path}")
  EOF
  python /tmp/download_qwen.py
  du -sh models/Qwen3.6-27B-FP8

  # 3. Install vLLM (matching GPU-TRANSLATE-003's precedent -- unpinned,
  #    same as before).
  pip install vllm

  # 4. Confirm nothing is already listening on the target port.
  pgrep -fa "vllm serve" || echo "confirmed: no vllm serve process running"

  # 5. Launch, matching GPU-TRANSLATE-004/005's proven flags exactly.
  nohup vllm serve "$(pwd)/models/Qwen3.6-27B-FP8" \
      --served-model-name qwen3.6-27b-translate \
      --max-model-len 4096 \
      --enforce-eager \
      --port 8000 \
      > vllm_serve.log 2>&1 &
  disown
  sleep 30
  tail -n 60 vllm_serve.log

  # 6. If the log shows the flashinfer TypeError (search for
  #    "array.array' is not subscriptable" -- expected on a fresh
  #    install, per GPU-TRANSLATE-003/004's history), patch it directly,
  #    matching GPU-TRANSLATE-005's fix, then relaunch.
  grep -q "is not subscriptable" vllm_serve.log && python3 - << 'EOF'
  import re
  import flashinfer.comm.fd_exchange as m
  from pathlib import Path
  path = Path(m.__file__)
  text = path.read_text()
  pattern = r'(?<!["\'])array\.array\[int\](?!["\'])'
  if re.search(pattern, text):
      path.write_text(re.sub(pattern, '"array.array[int]"', text))
      print("patched OK")
  else:
      print("pattern not found -- file may differ from GPU-TRANSLATE-005's; do not guess further, report back")
  EOF
  # If "patched OK" printed, relaunch (repeat step 5's nohup command,
  # then re-check the log the same way).

  # 7. Once the log shows a clean startup ("Application startup complete."
  #    / "API server: HTTP server started", matching GPU-TRANSLATE-005),
  #    verify over HTTP exactly as GPU-TRANSLATE-006 did.
  curl -s -o /dev/null -w "http_status=%{http_code}\n" http://localhost:8000/health
  curl -s http://localhost:8000/v1/models
  nvidia-smi --query-gpu=memory.used,memory.total --format=csv
  ```
- Expected success indicators: Step 2 prints a resolved `revision_sha` and
  `du -sh` shows ~29-31G on disk (matching `GPU-TRANSLATE-002`'s result).
  Step 5's log reaches "Application startup complete." with no traceback
  (if the flashinfer bug appears instead, that's expected on a fresh
  install -- proceed to step 6, not a dead end). Step 7's `/health`
  returns `http_status=200`, `/v1/models` lists `qwen3.6-27b-translate`
  with `max_model_len:4096` (matching `GPU-TRANSLATE-006` exactly), and
  `nvidia-smi` shows substantial GPU memory in use (~72 GB total is
  consistent with weights + KV cache, matching `GPU-TRANSLATE-005`) with
  no OOM.
  Expected artifacts: `models/Qwen3.6-27B-FP8/` (~30.9 GB), `.venv-translate/`,
  `vllm_serve.log` in the project root (same as `GPU-TRANSLATE-002`-`005`'s
  precedent -- keep it local, paste the relevant excerpt back rather than
  the whole file if it's large).
- Rollback or cleanup: If something goes wrong and needs to be stopped:
  `pkill -f "vllm serve"`. `/tmp/download_qwen.py` can be removed after
  use (`rm /tmp/download_qwen.py`). No other cleanup needed.
- Return to Claude (secrets/hostnames redacted):
  - The resolved `revision_sha` and `du -sh` output from step 2.
  - Whether `pip install vllm` completed cleanly (and the version it
    installed, e.g. from `pip show vllm`).
  - Whether the flashinfer patch (step 6) was needed.
  - The final `vllm_serve.log` excerpt showing startup success (or
    failure, if it didn't start).
  - The `/health` status code, the `/v1/models` response, and the
    `nvidia-smi` memory line.

### Action ID: LATENCY-001

- Status: WAITING_FOR_USER (**on hold** -- do not run until
  `GPU-TRANSLATE-008` gets the vLLM server running again and `GPU-E2E-001`
  is re-run to confirm translation actually works end-to-end; running it
  now would measure latency against a translation backend already known
  to be down)
- Purpose: Get the first-ever *real* hardware latency numbers for this
  project -- every latency measurement so far (Phase 11's local smoke
  runs of `scripts/latency_report.py`) has been against fake backends.
  Compare the results to `docs/PRODUCT_REQUIREMENTS.md` section 5's
  objectives (VAD speech-start p95 < 250ms, first partial p95 < 1.8s,
  final ASR p95 < 1.2s, translation p95 < 1.2s, end-to-end final p95 <
  3.5s -- noting `latency_report.py` does not isolate VAD speech-start or
  precise translation-only latency; see its own docstring).
- Run on: On or near the GPU host(s) (low network latency to both
  faster-whisper and vLLM matters for a meaningful reading) -- the same
  environment as `GPU-E2E-001` is a reasonable choice.
- Prerequisites: Same as `GPU-E2E-001` (`faster-whisper` installed,
  reachable vLLM server, this project's source + `dev` extra installed).
- Safety notes: Read-only; generates real but synthetic (sine-tone) load
  against both backends for the duration of the run (default 20
  utterances, a few minutes) -- not a stress test, ordinary single-stream
  load.
- Commands:
  ```bash
  cd /workspace/meetting-translator   # adjust to the real path on this host
  source .venv-asr/bin/activate
  python scripts/latency_report.py --count 20 --real-backends --json
  ```
- Expected success indicators: The script completes and prints a JSON
  report with real, non-zero `asr_final_ms`/`end_to_end_ms`/
  `first_partial_ms` percentiles. There is no pass/fail built into the
  tool itself -- "success" here means getting real numbers to compare
  against the documented objectives by hand.
  Expected artifacts: None persisted; console output only (redirect to a
  file if you want to keep it, e.g. `> latency-report.json`).
- Rollback or cleanup: None needed.
- Return to Claude:
  - Exact command used and exit status.
  - The full JSON (or table) output.
  - Any error output (secrets/hostnames redacted per
    `GPU_MANUAL_WORKFLOW.md`).

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
