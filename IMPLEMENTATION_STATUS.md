# Implementation Status

## Current phase

Phase 11: End-to-end tests and Windows packaging. This is the last
phase-by-phase prompt in `prompts/phases/` -- see "Next action" for what
that does and does not mean.

## Verification state

- Local verification: LOCAL_VERIFIED (Phase 00, Phase 01, Phase 02, Phase 03, Phase 04, Phase 05,
  Phase 06, Phase 07, Phase 08, Phase 09, Phase 10, Phase 11). A pre-existing, Phase-06-unrelated failure in
  `test_transport_sender.py` found while running Phase 06's checks was
  investigated and fixed (see "Bug fix: sender reconnect cancellation race"
  under "Known limitations"); the full suite is clean.
- Phase 11 verification: **LOCAL_VERIFIED, with three genuine local
  hardware-adjacent verifications performed in this session** (not just
  code review): a real PyInstaller build of the Windows client succeeded
  end-to-end (real PySide6/PyAudioWPatch installed temporarily, a real
  ~120 MB one-directory build produced, then the packages were uninstalled
  again to restore the project's documented baseline dev environment
  before the final canonical check run below); `scripts/load_test.py` was
  run against a real local `uvicorn` instance of this project's own
  `server.app:app` (real WebSocket connections, real handshake/ack/rate
  -limit behavior); `scripts/latency_report.py` was run and produces real
  measured percentiles (against fake backends locally, as documented in
  its own docstring). None of this is GPU or Windows-audio-hardware
  verification -- see "Phase 11 deliverables" and "Known limitations" for
  exactly what remains staged as a manual action (`MANUAL_ACTIONS.md`) and
  what "the one gap that matters most" is
  (`docs/FINAL_IMPLEMENTATION_REPORT.md`: `UtteranceOrchestrator` is still
  not wired into the live gateway).
- Phase 10 verification: **LOCAL_VERIFIED only.** Everything built this
  phase (JWT auth, circuit breaker, graceful shutdown, correlation ids,
  Prometheus metrics, session cap, readiness dependency check, redaction
  strengthening, reconnect/restart tests, `docs/SECURITY.md`,
  `docs/DEPLOYMENT.md`) is pure/local/CPU-testable or a real in-process
  FastAPI `TestClient`/WebSocket integration test -- none of it requires
  GPU hardware or Windows audio, so no `MANUAL_ACTIONS.md` entry was
  needed and none is pending. TLS/reverse-proxy guidance
  (`docs/DEPLOYMENT.md`) is documentation only, not verified against a
  real proxy/certificate. JWT verification is fully tested against real,
  locally-generated RSA keys but never against a real external identity
  provider/JWKS endpoint. See "Phase 10 deliverables" and "Known
  limitations".
- Windows audio verification: HARDWARE_VERIFIED (WINDOWS-AUDIO-001 PASSED 2026-08-10)
- GPU ASR verification: HARDWARE_VERIFIED for the `WhisperAsrModel` adapter
  itself (GPU-ASR-001 environment inspection PASSED 2026-08-10; GPU-ASR-002
  faster-whisper install INCONCLUSIVE 2026-08-11, superseded; GPU-ASR-003
  ctranslate2/CUDA visibility PASSED 2026-08-11; GPU-ASR-004 real model
  load/decode smoke test PASSED 2026-08-11; GPU-ASR-005 real-speech adapter
  test PASSED 2026-08-12, user confirmed both vi/ja transcripts roughly
  accurate). Still HARDWARE_PENDING for gateway/VAD-integrated end-to-end use
  and for scored accuracy/latency benchmarking — neither has been attempted.
- GPU translation verification: HARDWARE_VERIFIED for the
  `VllmTranslationClient`/prompt-building code path itself.
  `GPU-TRANSLATE-001` (environment inspection), `GPU-TRANSLATE-002` (model
  download), `GPU-TRANSLATE-005` (vLLM launch, after patching a
  third-party `flashinfer` bug that failed
  `GPU-TRANSLATE-003`/`GPU-TRANSLATE-004`), `GPU-TRANSLATE-006` (HTTP
  health check) and `GPU-TRANSLATE-007` (real two-direction translation
  request through the project's own prompt-building code) all PASSED
  2026-08-12: the server is up, answers `/health` (200) and `/v1/models`
  correctly (served id `qwen3.6-27b-translate`, `max_model_len=4096`
  matching the launch config), and produced plausible, correctly-scripted
  translations in both directions (JA->VI and VI->JA) with no
  exception/traceback and confirmed real generation in the engine log. See
  "Known limitations" for a caveat on how the JA/VI plausibility judgment
  was made. This was the last of Phase 07's staged GPU checkpoints; still
  HARDWARE_PENDING for wiring into the live gateway/VAD/ASR pipeline and
  for scored accuracy/latency benchmarking (both explicitly out of this
  phase's scope).
- Completeness/orchestration verification (Phase 08): LOCAL_VERIFIED only.
  The full pipeline (`UtteranceOrchestrator`) and the completeness
  heuristic are pure/composed logic exercised entirely with scripted ASR
  and translation fakes -- no GPU work is required to implement or test
  this phase's own scope. However, the completeness-check prompt/JSON
  schema (`CompletenessClassifier`) has never been sent to the real,
  already-running vLLM server -- only `TranslationClient.complete_chat`'s
  existing translation-prompt path was hardware-verified in Phase 07
  (`GPU-TRANSLATE-007`). Whether Qwen3.6-27B-FP8 reliably returns valid
  `{"complete": bool, "confidence": float}` JSON for this new prompt is
  therefore HARDWARE_PENDING; see "Known limitations". Not staged as a
  `MANUAL_ACTIONS.md` entry yet since it was not required to complete this
  phase's own local scope -- available on request.
- Client UI verification (Phase 09): **HARDWARE_VERIFIED**, for both the
  Qt-independent layer and the real PySide6 window, as of `WINDOWS-UI-007`
  (2026-08-13). `client/ui/view_model.py`, `client/ui/settings_store.py`
  and `client/ui/session_controller.py` are pure/composed logic with real
  unit and integration tests (no Qt import needed) -- see "Phase 09
  deliverables". `client/ui/main_window.py` cannot be imported or
  type-checked against real Qt in this development environment, so it
  was verified entirely through a seven-action manual sequence
  (`WINDOWS-UI-001` through `WINDOWS-UI-007`, 2026-08-12 to 2026-08-13)
  that found and fixed four real bugs -- none caught by local checks,
  since none of them are reachable without real hardware/network/Qt:
  1. A `websockets` import (`websockets.asyncio.client`) incompatible
     with the pinned `websockets>=12,<13` range, causing every real
     connection attempt to raise `ModuleNotFoundError`.
  2. A background-thread-crash cleanup gap: when the thread died, the UI
     kept treating the session as live, causing a `RuntimeError: Event
     loop is closed` traceback flood and a stuck "Disconnect" button.
  3. The capture-send timer starting before the WebSocket handshake
     completed, causing an early duplicate-traffic burst that tripped
     the server's jitter buffer (spurious `jitter overflow` warnings).
  4. `AudioSender._pump_incoming` awaiting a real (blocking) `recv()`
     directly, so it never noticed `stop` -- causing a ~5s UI freeze on
     Disconnect and a silently orphaned background thread that only
     exited once the server's own idle timeout eventually force-closed
     the connection.

  All four are now hardware-confirmed fixed, each with new regression
  tests. The audio capture/enqueue/send pipeline itself was separately,
  conclusively confirmed working for both microphone and loopback,
  together or independently (`WINDOWS-UI-003`/`WINDOWS-UI-004` -- the
  earlier "loopback produces nothing" observation was expected WASAPI
  behavior with no audio playing, not a bug). See "Known limitations" for
  the full per-action history and root-cause detail.
- Hardware end-to-end verification: NOT_STARTED

## Completed

- [x] Phase 00: Local project foundation and backup workflow
- [x] Phase 01: Contracts and protocol
- [x] Phase 02: Windows audio capture
- [x] Phase 03: WebSocket streaming
- [x] Phase 04: VAD and utterance state machine
- [x] Phase 05: Final Whisper ASR
- [x] Phase 06: Partial Whisper ASR and stable prefix
- [x] Phase 07: Qwen translation with vLLM
- [x] Phase 08: Completeness and finalization orchestration
- [x] Phase 09: PySide6 client UI
- [x] Phase 10: Reliability, security and observability
- [x] Phase 11: End-to-end tests and Windows packaging

## Latest local snapshot

`.local_backups/20260813T102059Z_phase-11.zip`, taken as the literal first
action of this phase (per `LOCAL_WORKFLOW.md` and the
`feedback_snapshot_before_editing` memory) -- this is a clean
pre-Phase-11 rollback point. `.local_backups/20260813T072309Z_phase-10.zip`
(end-of-Phase-10) remains available as the snapshot immediately before
that. Excludes `.venv`, `.local_backups`, models, caches, logs, recordings
and secrets; `.env.example` retained. Manifest with per-file SHA-256
alongside each zip. `.local_backups/20260812T122840Z_phase-09.zip`,
`.local_backups/20260812T104740Z_phase-08.zip`,
`.local_backups/20260811T184112Z_phase-07.zip`,
`.local_backups/20260811T182415Z_sender-cancel-race-fix.zip`,
`.local_backups/20260811T173029Z_phase-06.zip` and prior
Phase 00/01/02/03/04/05 snapshots are retained.

## Commands last run locally

```
python scripts/local_backup.py --label phase-11
ruff format --check .
ruff check .
mypy client server shared
pytest -m "not gpu and not windows_audio"
```

Note: this environment's `.venv` normally carries only the `dev`/`server`
extras (`pip install -e ".[dev]"`, plus `websockets`/`uvicorn` from the
`server` extra, installed this phase to genuinely run/verify
`scripts/load_test.py` against a real local dev server -- see "Phase 11
deliverables"). Phase 11 also added `pyinstaller` as a new, packaging-only
optional-dependency group (`pyproject.toml`'s `packaging` extra) --
**not** part of `dev`, since the CPU test suite never needs it. During
this phase, real `PySide6`/`PyAudioWPatch`/`pyinstaller` were installed
temporarily to perform a genuine PyInstaller build verification (see
"Phase 11 deliverables"), then **uninstalled again** before the final
canonical check run below, so these results reflect the project's normal,
documented baseline environment (the same one `README.md`'s CPU-mocked
quick start describes) -- consistent with every prior phase's reported
environment, and with `mypy`'s `PySide6.*` -> `ignore_missing_imports`
override actually being exercised as intended (it is a no-op, and
`client/ui/main_window.py`'s two `# type: ignore[misc]` comments become
genuinely *unused*, whenever real PySide6 stubs are present instead).

## Local test results

- ruff format --check: PASS (179 files already formatted)
- ruff check: PASS (all checks passed)
- mypy client server shared: PASS (no issues in 78 source files; includes
  `client/ui/main_window.py`, type-checked with PySide6 treated as an
  external untyped import per the existing mypy override -- see "Phase 09
  deliverables" for the two `type: ignore[misc]` annotations this
  requires in the project's normal (no-PySide6-installed) baseline
  environment)
- pytest (CPU, not gpu/not windows_audio): 421 passed, 0 failed, 3 deselected
  (424 collected)
  - Phase 11 end-to-end/load/version suites (6 new tests across 3 new
    files, plus 1 new gpu-marked file that skips locally; see "Phase 11
    deliverables"): test_e2e_mocked_pipeline.py (2),
    test_load_concurrent_meetings.py (1), test_version.py (2),
    test_e2e_gpu.py (1 test, `gpu`-marked, skipped in this environment --
    counted in the 3 deselected, along with the 2 pre-existing
    `windows_audio`-marked tests).
  - Phase 10 reliability/security/observability suites (73 new tests
    across 9 files; see "Phase 10 deliverables" for what each covers):
    test_transport_auth_jwt.py (18), test_reliability_circuit_breaker.py
    (10), test_reliability_shutdown.py (4), test_observability_correlation.py
    (8), test_observability_metrics.py (5), test_app_translation_backend_check.py
    (5), test_app_metrics_endpoint.py (2), test_app_jwt_wiring.py (4),
    test_logging_no_content_leak.py (4, new file), plus extensions to
    existing files: test_transport_session.py (+3), test_health.py (+3),
    test_logging_redaction.py (+2), test_translation_worker.py (+4),
    test_asr_worker.py (+3), test_orchestration_pipeline.py (+2),
    test_transport_sender.py (+1), test_transport_gateway.py (+1).
  - Phase 09 client UI suites, updated after `WINDOWS-UI-001`/
    `WINDOWS-UI-006` found three real bugs in the Connect/Disconnect flow
    (52 total; 5 are regression tests added for those fixes -- see "Known
    limitations"):
    - test_ui_view_model.py: 26 passed (Vietnamese-side/Japanese-side
      preset mapping, custom-preset raises, a partial creates a new
      caption entry, a stale/equal partial revision is ignored, a higher
      revision replaces the entry in place (not appended), a partial
      arriving after a final is ignored, a final replaces a partial and
      sets the bold/final marker, a failed-translation final marks
      `retryable`, a `translation.updated` for an unknown utterance is
      ignored, a known one replaces the translation and clears retry, an
      error event sets the message/retryable flag and is ignored without
      an `utterance_id`, `display_text` reflects stable+unstable before
      final and the transcription after, default/explicit preset
      application, custom per-source language override, device
      selection/clearing, source enable/disable, device-list assignment,
      connection-state passthrough, stream-id-to-source backfill on
      inbound events, event-type dispatch, and a full persisted-settings
      round trip including an unrecognized preset value falling back to
      `CUSTOM`)
    - test_ui_settings_store.py: 7 passed (missing file returns defaults,
      save-then-load round trips exactly, parent directories are created
      on save, corrupt/non-object JSON falls back to defaults, a partial
      document fills in missing fields from defaults, the saved file
      contains no token/password/secret-looking key, the default path is
      under a dedicated per-user directory)
    - test_ui_session_controller.py: 13 passed, using a real background
      thread (no Qt) and a fake transport modeled on
      `tests/test_transport_sender.py`'s: `parse_inbound_event` accepts
      each known event type and rejects an unknown type or a
      schema-invalid payload, `send_audio` before `start`/after `stop`
      raises, `start`/`stop` manage the thread lifecycle (including
      rejecting a second concurrent `start`), connection-state callbacks
      are reported in order, a real inbound `utterance.final` JSON
      message is parsed and delivered through the background thread to
      an `on_event` callback -- and, added after `WINDOWS-UI-001`'s
      report, 4 regression tests using a `CrashingTransport` whose
      `connect()` raises (modeling the real bug found): the background
      thread reports the exception via `on_fatal_error` exactly once,
      `is_running` becomes `False` once the thread actually dies, `stop()`
      no longer raises `RuntimeError: Event loop is closed` afterward, and
      `send_audio()` afterward raises one clean `RuntimeError` ("not
      running") instead of the underlying asyncio error.
    - `client/transport/sender.py` gained `ConnectionState` and two new
      optional `AudioSender` constructor callbacks
      (`on_state_change`, `on_message`) needed for the UI's connect/
      disconnect display and event bridge, plus (after `WINDOWS-UI-006`)
      a fix to `_pump_incoming` (polls `recv()` with a short timeout
      instead of awaiting it directly, so `stop` is noticed promptly even
      against a real transport whose `recv()` blocks indefinitely); 5 new
      tests in `test_transport_sender.py` (state reported as
      `CONNECTING`->`CONNECTED`->`DISCONNECTED` across one connect/
      disconnect cycle, `_open()` alone reports no state change,
      `on_message` fires for every parsed message type, and `run()` stops
      well under a second even with a transport whose `recv()` never
      returns on its own).
  - All Phase 09 tests are pure, use a fake `Transport` (no real socket),
    or use a real background thread with a fake transport (no Qt, no
    real network, no audio hardware) -- consistent with the phase's own
    required outcome ("view-model tests independent of Qt rendering").
    `client/ui/main_window.py` (the real PySide6 widgets) has no
    automated tests; it is excluded from CPU test collection entirely
    (never imported by any test) and was verified entirely through the
    seven-action manual sequence `WINDOWS-UI-001`-`WINDOWS-UI-007`
    (2026-08-12 to 2026-08-13, all now PASSED/HARDWARE_VERIFIED) -- see
    the "Client UI verification" bullet above and "Known limitations" for
    the four real bugs that sequence found and fixed.
  - Phase 08 orchestration/completeness suites (33):
    - test_orchestration_heuristics.py: 12 passed (Vietnamese/Japanese
      sentence-ending punctuation is definite-complete, language-specific
      ending signals without punctuation are definite-complete, a long
      unstable tail is definite-incomplete (not ambiguous), empty stable
      text is definite-incomplete, too-short confirmed speech duration
      makes an otherwise-matching punctuation signal ambiguous instead of
      definite, no-signal text is ambiguous with a deterministic
      (incomplete) fallback, a short unstable tail within the configured
      threshold does not block completion, invalid config rejected,
      `from_settings` reads the `completeness_heuristic_*` fields)
    - test_translation_completeness.py: 11 passed (valid complete/incomplete
      JSON parsed, JSON wrapped in extra text/markdown fences is still
      extracted, missing keys/wrong types/bool-as-confidence are all
      treated as invalid (unknown), a scripted backend
      timeout/overloaded error is unknown, the classifier's own
      `wait_for` timeout is enforced independent of the backend, invalid
      config rejected)
    - test_orchestration_pipeline.py: 8 passed, exercising the full
      `UtteranceOrchestrator` (VAD -> partial ASR -> final ASR ->
      translation -> final event) against `ScriptedAsrModel`/
      `ScriptedTranslationClient` fakes -- no GPU/model weights: hard
      silence finalizes without a completeness check when no
      punctuation/ending-signal is present; a definite-complete heuristic
      verdict at soft silence finalizes early as `semantic_complete`
      (before hard silence); a stale soft-silence decision is discarded
      (no early finalize) when speech resumes before the decision
      resolves (uses a real, artificially-delayed completeness call to
      create a genuine race window); hard silence firing synchronously
      before a still-pending soft-silence decision gets a chance to run
      results in *exactly one* `utterance.final` (race-safe, no double
      finalize); a completeness-check timeout falls back to the
      deterministic (incomplete) verdict rather than wrongly finalizing;
      two streams with independently-open utterances finalize
      independently with distinct utterance ids and correct stream
      attribution; `flush_stream` forces finalization while still
      actively speaking (`client_flush`); a failed initial translation
      publishes `utterance.final` with `translation_status=failed`
      immediately and a later successful retry publishes a separate
      `translation.updated` event.
    - `server/vad/state_machine.py` gained a read-only `speech_ms`
      property (exposes the state machine's existing internal counter for
      the heuristic's "stable duration" signal); 1 new test in
      `test_vad_state_machine.py`.
    - `server/asr/partial.py` gained `PartialTranscriber.current_text()`
      (exposes the last-published stable/unstable text without forcing a
      new decode, for the completeness decision to read); 1 new test in
      `test_asr_partial.py`.
  - All Phase 08 tests are pure, use `ScriptedAsrModel`/
    `ScriptedTranslationClient`, or use small local fakes with an
    artificial `asyncio.sleep` -- no real Whisper/vLLM/CUDA, no network
    access, and no model weights are downloaded.
  - Phase 07 translation suites (72):
    - test_translation_types.py: 8 passed (config defaults/from_settings
      mapping/validation, glossary entry validation, request validation
      (empty text, same source/target language), outcome validation
      (COMPLETED requires text, FAILED forbids text))
    - test_translation_errors.py: 5 passed (error kinds/retryable flags,
      error-code mapping, backend-exception classification for
      timeout/connection/default-to-failed)
    - test_translation_fake.py: 4 passed (scripted ordering/clamp, call
      recording, scripted error, empty-outcomes guard)
    - test_translation_prompts.py: 11 passed (JA->VI and VI->JA system
      prompts match docs/TRANSLATION.md's requirements text, unsupported
      direction rejected, glossary block rendering and relevance filtering
      (case-insensitive), corrective-prompt suffix appended for retries,
      user content with/without context trimmed to at most 2 prior
      sentences, completeness-check prompt matches the documented schema)
    - test_translation_validator.py: 15 passed (valid vi/ja outputs pass;
      empty output, forbidden prefix (English and Vietnamese labels),
      pathological repetition for Vietnamese (space-delimited) and Japanese
      (no spaces), wrong-language detection both directions, missing
      version/URL preservation rejected, preserved version+date passes,
      length ratio too short and too long rejected)
    - test_translation_client.py: 9 passed against `httpx.MockTransport`
      (no real vLLM server): correct request payload (model, temperature 0,
      top_p 1, stream false, non-thinking `chat_template_kwargs`), auth
      header sent, HTTP 429/503 -> overloaded, HTTP 500 -> failed, timeout ->
      timeout error, malformed/missing-choices JSON -> failed, an injected
      `httpx.AsyncClient` is not closed by `aclose()`
    - test_translation_queue.py: 9 passed (final drains before retry before
      completeness, FIFO within a priority, a newer final item still drains
      before an older retry, bounded per-priority lane rejected explicitly
      on overflow without affecting other lanes, qsize totals,
      `should_skip_completeness` threshold behavior)
    - test_translation_worker.py: 11 passed (`translate_once` success and
      validation-failure paths (no auto-retry), backend-error mapping,
      `wait_for` timeout enforcement, `retry()` uses a corrective prompt
      after a validation failure vs. the original prompt after a timeout,
      bounded concurrency actually caps concurrent in-flight calls,
      glossary/context reach the client, `apply_translation` returns a new
      event without mutating the original, `build_translation_updated`
      requires a COMPLETED outcome)
  - All translation tests are either pure (types/errors/fake/prompts/
    validator/queue), use `ScriptedTranslationClient`, or use
    `httpx.MockTransport` -- no real vLLM server or network access, and no
    model weights are downloaded.
  - Phase 06 partial-ASR suites (36):
    - test_asr_stable_prefix.py: 10 passed (first-hypothesis no-commit,
      two-hypothesis agreement for Vietnamese and Japanese (no spaces),
      punctuation-variation does not prematurely commit, a later contradicting
      hypothesis does not rewrite committed text, committed text never
      shrinks across a sequence, stable-boundary-ms segment mapping, window
      reset keeps committed text but restarts agreement, finalize)
    - test_asr_sliding_window.py: 9 passed (append/accumulate, advance
      no-ops on a non-positive boundary, advance keeps the overlap margin,
      advance clamps at zero when overlap exceeds the boundary, advance
      clamps to the actually-buffered length so it can never over-trim,
      advance is relative to the current window across repeated trims)
    - test_asr_partial_scheduler.py: 9 passed (interval validation, not due
      before the interval, due-and-reschedule, stop removes an utterance,
      independent streams scheduled by their own start time, simultaneous
      due utterances all returned so none is starved, a missed/late tick
      reschedules from "now" rather than the missed due time so it cannot
      burst catch-up decodes)
    - test_asr_partial.py: 10 passed (unknown/no-audio utterances return no
      event, first partial event published with correct revision/text/
      timing, duplicate stable+unstable text is suppressed, revision only
      increases on a real content change, `previous_text` conditioning uses
      the committed text, a decode superseded by a newer one or by the
      utterance being stopped mid-flight is discarded rather than applied)
  - `AsrConfig` gained `partial_beam_size` (mirrors `whisper_partial_beam_size`);
    test_asr_config.py extended with 1 new test (2 new assertions total).
  - All partial-ASR tests use `ScriptedAsrModel`; no weights are downloaded,
    no real Whisper/CUDA/asyncio-timer dependency.
  - A pre-existing failure unrelated to Phase 06,
    `tests/test_transport_sender.py::test_run_reconnects_and_resends_pending`
    (Phase 03 client reconnect test, deterministic 2s timeout in this
    environment), was investigated at the user's request and fixed; see
    "Bug fix: client reconnect cancellation race" below. It now passes
    (0.117s) and the suite has 0 failures.
  - (Prior 129 VAD/transport/protocol/audio tests otherwise unchanged.)
- windows_audio-marked tests remain deselected on this environment.
- One non-blocking warning: Starlette TestClient httpx deprecation notice
  (from FastAPI test client, not project code).

## Phase 03 deliverables

Server transport (`server/transport/`):
- `auth.py`: `Authenticator` interface, `AuthContext`, `AuthError`, and the
  functional dev `StaticTokenAuthenticator` (anonymous in non-production or a
  constant-time shared-token check). Production JWT validation slots in behind
  the same interface; no placeholder crypto shipped.
- `limits.py`: monotonic-time `TokenBucket` packet rate limiter.
- `jitter_buffer.py`: per-stream reorder buffer; holds out-of-order packets,
  releases contiguously, deduplicates, rejects stale packets, and force-advances
  past oversized gaps (bounded capacity, reported loss).
- `acks.py`: `AckBatcher` emitting one `audio.ack` per N packets or T ms.
- `session.py`: `StreamContext`, `Session`, `SessionManager` built from a
  validated `session.start` (unique ids, per-stream contexts, stream cap).
- `gateway.py`: FastAPI `/ws/stream` endpoint — handshake + validation, auth,
  independent binary ingest per stream, batched acks, payload/rate limits,
  keepalive/idle handling and typed `error` events. Never logs payloads/text.

Client transport (`client/transport/`):
- `backoff.py`: deterministic exponential `ReconnectBackoff` with optional
  injectable jitter.
- `outbound.py`: bounded `OutboundBuffer` (drop-oldest) of unacked frames for
  idempotent resend.
- `sender.py`: `AudioSender` with a `Transport` protocol (injectable),
  session handshake, per-stream sequence assignment, ack-driven buffer
  release, and a reconnect loop that resends unacked frames on each connect.
  `WebSocketClientTransport` (lazy `websockets`) provides the real socket.
  `_serve()` shuts down its pump tasks via a `_cancel_and_wait` helper that
  retries cancellation until both tasks actually finish, rather than a
  single `cancel()` call (see "Bug fix: client reconnect cancellation race"
  under "Known limitations").

Wiring/tooling:
- `server/app.py` now mounts the gateway with a dev authenticator and session
  manager.
- `shared/settings.py` + `.env.example`: transport, ack-batching, jitter,
  idle/heartbeat, rate-limit, auth-token and reconnect settings.
- mypy override treats `websockets` as an external untyped import.

## Phase 04 deliverables

VAD segmentation (`server/vad/`), pure synchronous CPU logic with no I/O,
FastAPI, Qt or CUDA coupling:
- `types.py`: audio constants (16 kHz S16LE, `BYTES_PER_MS`), the `VadState`
  enum (IDLE, SPEECH_STARTING, SPEAKING, POSSIBLE_END, FINALIZING), the frozen
  `VadConfig` (thresholds/durations/padding with validation and a
  `from_settings` mapping) and the frozen `Utterance` value object (id, source,
  timestamps, speech duration, final reason, audio buffer).
- `events.py`: `VadEventType` and frozen event records `SpeechStarted`,
  `SoftSilence`, `ResumedSpeech`, `UtteranceFinalized`, plus the `VadEvent`
  union.
- `interface.py`: `VadModel` runtime-checkable protocol (`probability`,
  `reset`) documented to run off the event loop.
- `fake.py`: deterministic `ScriptedVadModel` for tests (per-call probabilities,
  clamps to the last value when exhausted, `reset` rewinds).
- `silero.py`: `SileroVadModel` adapter with lazy `torch`/`silero_vad`
  initialization, 512-sample windowing and int16→float32 conversion; kept out
  of the CPU suite.
- `ring_buffer.py`: bounded `PreRollBuffer` (deque of recent frames) supporting
  pre-roll snapshots; disabled cleanly when capacity is below one frame.
- `state_machine.py`: `UtteranceSegmenter` — the per-stream IDLE/
  SPEECH_STARTING/SPEAKING/POSSIBLE_END machine. Confirms speech after
  `speech_start_ms`, prepends pre-roll audio, emits speech-start, soft-silence
  (once) and resumed-speech events, finalizes on hard silence or max utterance,
  trims trailing silence to `speech_pad_after_ms`, discards sub-`min_speech_ms`
  utterances (unless force-flushed), assigns incrementing utterance ids, and
  supports forced finalization via `flush(reason)`.

Tooling:
- mypy override extended to treat `silero_vad` and `torch` as external untyped
  imports.

## Manual actions waiting for user

### GPU-ASR-001 (PASSED 2026-08-10)

Read-only inspection of the ASR GPU host: NVIDIA H100 80GB HBM3 (0 MiB used),
driver 580.82.07, CUDA (driver) 13.0, nvcc 12.8, 128 CPUs, 1.5 TiB RAM (696 GiB
free), ample disk on both the container overlay and the persistent `/workspace`
PVC, Python 3.11.13. Host is a containerized/Kubernetes pod, not bare metal. No
errors observed. Full output is recorded in `USER_RESULTS.md`; the action entry
is now under "Completed actions" in `MANUAL_ACTIONS.md`.

### GPU-ASR-002 (INCONCLUSIVE 2026-08-11, superseded)

Installed `faster-whisper` 1.2.1 into a venv on the GPU host successfully
(real path confirmed by GPU-ASR-003 as
`/workspace/meetting-translator/.venv-asr`, not `/workspace/.venv-asr` as
first assumed). The action also asked for `import torch`, which failed with
`ModuleNotFoundError`. That check was a mistake in the action, not a real
signal: `faster-whisper` runs inference through CTranslate2, and the
project's `pyproject.toml` `gpu` extra pins only `faster-whisper>=1.0,<2`
with no PyTorch dependency, so a missing `torch` module proves nothing about
GPU readiness. Full result recorded in `USER_RESULTS.md`; action entry moved
to "Completed actions" (INCONCLUSIVE) in `MANUAL_ACTIONS.md`.

### GPU-ASR-003 (PASSED 2026-08-11)

Corrected diagnostic: `ctranslate2` 4.8.1 installed, `cuda_device_count()`
returned 1 (CTranslate2 sees the H100). Active interpreter and installed
packages confirmed inside the venv; `nvidia-smi` matched GPU-ASR-001.
`libcudart`/`libcublas`/`libcublasLt` resolved via `ldconfig`; `libcudnn`
did not appear in that listing. Per this action's own stated success
criteria (a missing `ldconfig` match only disqualifies if
`cuda_device_count` is 0), this is not treated as a failure, but it is an
open question carried into GPU-ASR-004: a real model load/decode is the
only way to confirm cuDNN (if needed by CTranslate2's ops) is actually
resolvable, since enumerating a CUDA device does not require loading a
model. Full result recorded in `USER_RESULTS.md`; action entry moved to
"Completed actions" in `MANUAL_ACTIONS.md`.

### GPU-ASR-004 (PASSED 2026-08-11)

First real GPU decode: downloaded `large-v3` weights (revision
`edaa852ec7e145841d8ffdb056a99866b5f0a478`, ~2.88 GiB) and ran one
`model.transcribe()` call against a locally-synthesized sine tone. Model
load (3.66s) and decode (0.29s) both completed with no CUDA/cuDNN/cuBLAS
error — resolving the open question from GPU-ASR-003 about `libcudnn` not
appearing in `ldconfig`. Still not an accuracy test (synthetic tone, no real
speech). Full result recorded in `USER_RESULTS.md`; action entry moved to
"Completed actions" in `MANUAL_ACTIONS.md`.

### GPU-ASR-005 (PASSED 2026-08-12)

First real-speech, real-code-path check: ran the project's own
`WhisperAsrModel` adapter (`server/asr/whisper.py`), built with the
project's documented `AsrConfig` defaults, against two real-speech WAV
samples (`vi_sample.wav`, 28s; `ja_sample.wav`, 20s). No exception for
either language; `segments > 0` for both (7 and 8); both outputs are
fluent, coherent, well-formed text in their respective language (Vietnamese
company-profile passage; Japanese textbook sentence-pattern examples) — see
`USER_RESULTS.md` for full text. User confirmed the ground-truth criterion:
"yes, the printed text is a roughly accurate rendering of what i said," for
both clips. This is the first hardware confirmation that the project's own
ASR adapter code (not just bare faster-whisper/ctranslate2) produces
plausible real transcripts in both target languages. Broader scored
accuracy/latency benchmarking and wiring `FinalTranscriber` into the live
gateway/VAD path remain separate, not-yet-started work.

No ASR manual action is currently pending.

### GPU-TRANSLATE-001 (PASSED 2026-08-12)

Read-only inspection: 1x NVIDIA H100 80GB HBM3 (0 MiB used), driver
580.82.07, CUDA (driver) 13.0, nvcc 12.8, 128 CPUs, 1.5 TiB RAM (596 GiB
free), `/workspace` PVC 300G (155G avail). Docker check intentionally
skipped -- user intends the bare-process `vllm serve` launch path. No
errors observed. Confirmed: this is the *same physical host and the same
single GPU* already used for ASR (`GPU-ASR-001`-`GPU-ASR-005`), not a
separate GPU as `docs/ARCHITECTURE.md` recommends. Flagged explicitly (see
"Known limitations") rather than silently accepted -- 80 GB of VRAM gives
meaningful headroom for both models' likely combined footprint, but final
co-location suitability under real concurrent production load is a
capacity-planning judgment call, not verified here. Full output recorded in
`USER_RESULTS.md`; action entry moved to "Completed actions" in
`MANUAL_ACTIONS.md`.

### GPU-TRANSLATE-002 (PASSED 2026-08-12)

Downloaded the official `Qwen/Qwen3.6-27B-FP8` weights (confirmed real via
web search, ~30.9 GB) into
`/workspace/meetting-translator/models/Qwen3.6-27B-FP8`, in a new
`.venv-translate` kept separate from `.venv-asr`. Resolved revision
`e89b16ebf1988b3d6befa7de50abc2d76f26eb09`; 80 files, 8m11s; `du -sh`
reports 29G, consistent with the download tool's own "30.9GB / 30.9GB
complete" report. No exception. Full output recorded in `USER_RESULTS.md`;
action entry moved to "Completed actions" in `MANUAL_ACTIONS.md`.

### GPU-TRANSLATE-003 (FAILED 2026-08-12)

`pip install vllm` succeeded, but launching (`vllm serve ...`) crashed
during model construction: `TypeError: type 'array.array' is not
subscriptable` inside `flashinfer/comm/fd_exchange.py`, imported as part
of vLLM's `torch.compile` backend setup (`AllReduceFusionPass`). Root
-caused via the traceback plus reading vLLM's own source on GitHub: this
is a genuine bug in the installed `flashinfer` package (`array.array`
does not support subscripting, so `array.array[int]` as a type annotation
always fails at import time) -- not caused by this project, the download,
or the host environment. Full analysis in `USER_RESULTS.md`; action entry
moved to "Completed actions" in `MANUAL_ACTIONS.md`.

### GPU-TRANSLATE-004 (FAILED 2026-08-12)

Retried the vLLM launch with `--enforce-eager` added. This correctly fixed
the targeted crash: model construction succeeded (weights loaded in 23.7s,
27.67 GiB; KV cache computed: 41.03 GiB available, 292,522 tokens). But
`EngineCore` then crashed on the *same* `flashinfer` `array.array[int]`
bug via a *different* import chain: `kernel_warmup()` unconditionally
imports MiniMax-M3-specific warmup code (unrelated to the Qwen3.5 model
being served), which transitively imports the same broken
`flashinfer.comm`. Full analysis in `USER_RESULTS.md`; action entry moved
to "Completed actions" in `MANUAL_ACTIONS.md`.

### GPU-TRANSLATE-005 (PASSED 2026-08-12)

Patched the one broken line in the installed `flashinfer` package
(`.venv-translate/.../flashinfer/comm/fd_exchange.py`) by quoting the
invalid `array.array[int]` return-type annotation as a string, then
relaunched (`--enforce-eager` kept). Server reached full startup this
time: "Started server process", "Application startup complete.", "API
server: HTTP server started" -- no traceback. `nvidia-smi`:
`72237/81559 MiB` used, consistent with weights (~27.67 GiB) + KV cache
(~41.03 GiB) both resident, no OOM. This is the first successful vLLM
server start across five launch-related actions. Explicitly a local,
venv-scoped workaround, not a permanent fix (reinstalling/upgrading
`flashinfer`/`vllm` in this venv would overwrite it). Full output recorded
in `USER_RESULTS.md`; action entry moved to "Completed actions" in
`MANUAL_ACTIONS.md`.

### GPU-TRANSLATE-006 (PASSED 2026-08-12)

First HTTP-level confirmation that the running server actually answers
OpenAI-compatible requests and serves the expected model name: `/health`
returned `http_status=200`; `/v1/models` returned a well-formed
OpenAI-compatible listing (`id=qwen3.6-27b-translate`,
`root=/workspace/meetting-translator/models/Qwen3.6-27B-FP8`,
`max_model_len=4096`, matching the launch config exactly and matching
`VLLM_MODEL` in `.env.example`). No error, timeout or unexpected status.
Full output recorded in `USER_RESULTS.md`; action entry moved to
"Completed actions" in `MANUAL_ACTIONS.md`.

### GPU-TRANSLATE-007 (PASSED 2026-08-12)

The last of this phase's staged GPU checkpoints: a real two-direction
translation request (Japanese->Vietnamese, Vietnamese->Japanese) through
the project's own prompt-building code (`server/translation/prompts.py`'s
`build_system_prompt`/`build_user_content`) against the running vLLM
server. Both requests returned `200 OK` with no exception/traceback:
JA->VI "来週のリリースについて確認したいです。" -> "Tôi muốn xác nhận về
bản phát hành vào tuần tới."; VI->JA "Tôi muốn xác nhận về đợt phát hành
vào tuần tới." -> "来週のリリースについて確認したいのですが。" Both
correctly scripted, no forbidden prefix, no repetition; the vLLM engine
log confirms real generation (non-zero throughput, non-zero KV cache
usage). See "Known limitations" for a note on how the plausibility
judgment was made. No further translation-specific manual action is
currently pending.

No translation manual action is currently pending.

## Phase 05 deliverables

Final ASR (`server/asr/`), framework-independent domain logic plus a lazy GPU
adapter:
- `types.py`: audio constants, the frozen `AsrConfig` (model/device/
  compute_type/final_beam_size/temperature/condition_on_previous_text with
  validation and a `from_settings` mapping to the `whisper_*` baseline),
  `AsrRequest` (audio + decode options + optional conditioning prompt, with a
  `duration_ms` helper) and the frozen result models `TranscriptionSegment` /
  `TranscriptionResult`.
- `errors.py`: `AsrErrorKind` and the typed `AsrError` hierarchy
  (`ModelUnavailableError`, `AsrTimeoutError`, `AsrOutOfMemoryError`,
  `AsrDecodeError`) with `retryable` flags, an `error_code` mapping to
  `ErrorCode.ASR_FAILED`, and `classify_backend_error` to normalize backend
  exceptions (OOM / model-missing / decode) without importing GPU libraries.
- `interface.py`: `AsrModel` runtime-checkable protocol documented to run off
  the event loop.
- `fake.py`: deterministic `ScriptedAsrModel` (scripted results/errors, request
  recording) for CPU tests.
- `whisper.py`: `WhisperAsrModel` faster-whisper adapter with lazy `WhisperModel`
  load, int16->float32 conversion, per-language decode with beam/temperature/
  conditioning, and backend-error mapping. Excluded from the CPU suite.
- `worker.py`: `FinalTranscriber` runs decoding in a dedicated single-worker
  executor (never blocks the event loop; final ASR prioritized/serialized),
  enforces `asr_final_timeout_ms` via `wait_for` (timeout -> `AsrTimeoutError`),
  performs final reconciliation over completed utterance audio, and `finalize()`
  builds the `utterance.final` event with the transcription and
  `translation=None` / `translation_status=pending`. `build_asr_error_event`
  maps a typed error to a protocol `error` event.

Configuration/tooling:
- `shared/settings.py` + `.env.example`: added `whisper_final_beam_size`,
  `whisper_partial_beam_size`, `whisper_temperature`,
  `whisper_condition_on_previous_text` and `asr_final_timeout_ms`.
- mypy override extended to treat `faster_whisper` as an external untyped import.

## Phase 06 deliverables

Streaming partial ASR (`server/asr/`), pure/testable domain logic plus a thin
async orchestrator, mirroring the layering already used for transport
(`AckBatcher`) and final ASR (`FinalTranscriber`) — no gateway/VAD wiring yet
(consistent with Phase 05's `FinalTranscriber`, which is also not yet wired
into the live ingest path):
- `stable_prefix.py`: `StablePrefixTracker`/`StablePrefixResult` — pure,
  Whisper-independent local-agreement text merging. Commits text only once it
  agrees, segment-for-segment, across two consecutive decodes of the same
  audio window (comparing whole Whisper segments, not characters or
  whitespace-split words, so it works uniformly for Japanese and Vietnamese
  and never truncates mid-token). Committed text is monotonic — a later
  contradicting hypothesis cannot rewrite it. `stable_boundary_ms` maps the
  committed prefix back to a window-relative audio timestamp for windowing;
  `reset_window` restarts the agreement baseline (without discarding
  committed text) after the audio window shifts; `finalize` commits full text.
- `sliding_window.py`: `SlidingAudioWindow` — pure, growing PCM buffer for one
  in-progress utterance. `advance` drops audio already confirmed stable,
  keeping a configurable `overlap_ms` safety margin before the boundary (so a
  word spanning the trim point is not cut acoustically) and clamps to what is
  actually buffered so a boundary from an inconsistent backend can never
  over-trim. Continuity for dropped audio comes from feeding committed text
  back as `AsrRequest.previous_text`, not from re-decoding it.
- `partial_scheduler.py`: `PartialDecodeScheduler` — pure, time-injected
  (matches `AckBatcher`'s style) per-utterance due-time tracking at a
  configurable interval (`whisper_partial_interval_ms`, default 500ms).
  Independent per-stream due times, all simultaneously-due utterances
  returned (no stream starved), and a missed/slow tick reschedules from "now"
  rather than the missed due time so a gap cannot cause a catch-up burst.
- `partial.py`: `PartialTranscriber` — composes the above with an `AsrModel`
  to produce `transcription.partial` events. Runs decoding off the event loop
  in a dedicated executor (like `FinalTranscriber`); per-utterance state
  (window, tracker, revision, last-published text, a decode "generation"
  counter). Protections: duplicate stable/unstable text is not republished;
  revision only increases and only on a real change; a decode result that
  completes after the utterance was stopped or after a newer decode
  superseded it is discarded rather than applied (checked via the generation
  counter and utterance presence, both re-checked after the `await`).
  `current_revision` is exposed for a future final-reconciliation caller to
  assign the final event a strictly higher revision than the last partial
  (not wired up in this phase — final ASR's own revision handling is
  untouched, per "final reconciliation remains authoritative").

Configuration:
- `types.py`: `AsrConfig` gained `partial_beam_size: int = 1` (validated >= 1)
  and `from_settings` now maps `whisper_partial_beam_size`. `final_beam_size`
  and `FinalTranscriber` are unchanged.

Not in this phase's scope (consistent with Phase 05 precedent and the phase
prompt's own scope): a live asyncio loop driving `PartialDecodeScheduler` on
a wall clock, and wiring `PartialTranscriber`/`FinalTranscriber` into the
gateway/VAD ingest path. See "Known limitations".

## Phase 07 deliverables

Qwen3.6-27B-FP8 translation via vLLM (`server/translation/`), framework
-independent domain logic plus a plain async HTTP adapter (unlike the ASR/
VAD GPU adapters, `httpx` is CPU-only and already in the `dev`/`server`
extras, so the client is imported directly and fully unit-tested against a
local mock transport, not excluded from the CPU suite):
- `types.py`: `TranslationConfig` (base_url/api_key/model/token limits/
  timeout/concurrency from `vllm_*`/`translation_*` settings via
  `from_settings`; temperature 0 and top-p 1 are fixed constants, not
  settings-driven, per the documented baseline), `GlossaryEntry`,
  `TranslationRequest` (finalized text + source/target language + glossary +
  at most `MAX_CONTEXT_SENTENCES`=2 prior sentences, with validation), and
  `TranslationOutcome` (text/status/issue, with validation that a COMPLETED
  outcome carries text and a FAILED one does not).
- `errors.py`: `TranslationErrorKind` and the typed `TranslationError`
  hierarchy (`TranslationTimeoutError`, `TranslationOverloadedError`,
  `TranslationFailedError`) with `retryable` flags, an `error_code` mapping
  to `TRANSLATION_TIMEOUT`/`OVERLOADED`/`TRANSLATION_FAILED`, and
  `classify_backend_error` to normalize backend exceptions without
  requiring callers to import `httpx` exception types.
- `interface.py`: `TranslationClient` runtime-checkable protocol (plain
  async, no executor needed, unlike the ASR/VAD model protocols).
- `fake.py`: deterministic `ScriptedTranslationClient` (scripted
  results/errors, call recording) for CPU tests.
- `prompts.py`: `build_system_prompt` (JA->VI and VI->JA templates matching
  docs/TRANSLATION.md verbatim, glossary substitution, a corrective-prompt
  suffix for the retry path), `build_user_content` (current text plus at
  most 2 trailing prior sentences as explicitly non-translatable context),
  `select_relevant_glossary` (case-insensitive substring filter so only
  glossary entries actually present in the text are sent) and
  `build_completeness_prompt` (matches the documented completeness-check
  JSON schema; only the prompt text -- scheduling/consuming it is
  finalization-orchestration work for a later phase).
- `validator.py`: `validate_translation` checking, in order, empty output,
  forbidden explanation/label prefixes, pathological repetition (a
  character-level repeated-run regex, not word-tokenized, so it works for
  non-space-delimited Japanese too), target-language plausibility (CJK
  character-ratio heuristic), preservation of numbers/dates/URLs/versions/
  identifiers extracted from the source and required verbatim in the
  translation, and extreme length ratio. Returns a machine-readable
  `reason` on failure.
- `client.py`: `VllmTranslationClient` posts an OpenAI-compatible
  `/chat/completions` request (temperature 0, top-p 1, `stream: false`,
  `chat_template_kwargs: {"enable_thinking": false}` for non-thinking mode)
  and maps HTTP 429/503 to overloaded, other non-2xx/malformed responses to
  failed, and `httpx` errors via `classify_backend_error`. Timeout/
  cancellation are the caller's responsibility (matches `FinalTranscriber`'s
  pattern), not enforced inside the client itself.
- `queue.py`: `TranslationPriority` (FINAL < RETRY < COMPLETENESS, matching
  the `docs/ARCHITECTURE.md` vLLM scheduler priority policy) and
  `TranslationQueue`, a bounded, per-priority-lane FIFO (pure/synchronous,
  matching `AckBatcher`/`OutboundBuffer`'s style) that rejects overflow on
  one lane explicitly without affecting the others, plus
  `should_skip_completeness` (the documented queue-pressure skip policy).
- `worker.py`: `FinalTranslator` runs one bounded (semaphore-limited
  concurrency), timed (`wait_for`) translation attempt per call and
  validates the result. `translate_once` never auto-retries, so a caller can
  publish `utterance.final` immediately on failure/timeout without blocking;
  `retry` is the single allowed second attempt, using a corrective prompt
  when the prior failure was a recoverable validation issue or the original
  prompt after a backend timeout/error. `apply_translation` returns a *new*
  `UtteranceFinal` with the outcome attached (does not modify or mutate
  `server.asr.worker.FinalTranscriber`'s output). `build_translation_updated`
  builds a `translation.updated` event from a later successful retry
  (raises if the outcome is not COMPLETED).

Not in this phase's scope (consistent with Phase 05/06 precedent and the
phase prompt's own scope, since the full orchestrator is explicitly
Phase 08's "Completeness and Finalization Orchestration"): actually calling
`translate_once`/`retry` from the ASR final-event path, deciding *when* a
background retry runs and publishing its `translation.updated` over a real
socket, a live consumer draining `TranslationQueue`, and any completeness
-classification consumer (only the prompt builder and the queue's
completeness priority/skip-policy primitive are implemented here). See
"Known limitations".

## Phase 08 deliverables

Completeness and finalization orchestration
(`server/orchestration/`, `server/translation/completeness.py`), composing
every component built in Phases 04-07 into the full documented pipeline
(`docs/ARCHITECTURE.md`: VAD -> partial ASR -> final ASR -> translation ->
final event) plus this phase's own deterministic heuristic checker. As with
every prior phase, this is composable/testable domain logic, not yet wired
into the live gateway WebSocket ingest path -- see "Known limitations".

- `server/orchestration/heuristics.py`: `HeuristicConfig`
  (language-specific sentence-ending punctuation and ending-signal
  vocabularies, `min_stable_speech_ms`, `max_unstable_tail_chars`, with a
  `from_settings` mapping) and `evaluate_heuristic`, the deterministic
  completeness checker. Evaluates, in order: an empty stable text (definite
  incomplete), an unstable tail longer than the configured threshold
  (definite incomplete -- ASR is still actively catching up, so no
  confident decision can be made), sentence-ending punctuation with
  sufficient confirmed speech duration (definite complete), a
  language-specific ending-signal word/phrase with sufficient speech
  duration (definite complete), else ambiguous with a deterministic
  (incomplete) fallback value. "Stable duration" is interpreted as the
  utterance's own confirmed `speech_ms` (a very short burst is unreliable
  even with a punctuation match) -- documented explicitly in the module
  docstring since the phase prompt does not prescribe an exact algorithm.
- `server/orchestration/types.py`: `CompletenessConfig` (enabled/timeout/
  skip-queue-depth/max-tokens/min-confidence, with a `from_settings`
  mapping to the new `completeness_*` settings below) and the
  `PublishEvent`/`OrchestratorEvent` type aliases for the orchestrator's
  event-publishing sink.
- `server/translation/completeness.py`: `CompletenessClassifier` -- the
  optional low-priority Qwen completeness check (docs/TRANSLATION.md).
  Reuses the existing `TranslationClient` protocol and
  `build_completeness_prompt` (Phase 07); bounded by a strict
  `asyncio.wait_for` timeout and a small `max_tokens`. Parses the model's
  JSON response (with one bounded fallback extraction if the model wrapped
  it in extra text/markdown despite instructions); any failure -- timeout,
  backend error, invalid JSON, wrong types, or a `confidence` that is
  actually a `bool` (a Python subtlety: `bool` is a subclass of `int`) --
  yields an explicit "unknown" outcome (`complete=None`) rather than
  raising, so the caller always has a clean fallback path.
- `server/orchestration/pipeline.py`: `UtteranceOrchestrator` -- the full
  per-session pipeline. Owns one `UtteranceSegmenter` per registered stream
  (VAD state is inherently per-stream) and shares one `PartialTranscriber`,
  `PartialDecodeScheduler`, `FinalTranscriber`, `FinalTranslator`,
  `CompletenessClassifier` and `TranslationQueue` across every stream in
  the session (matching one real ASR/translation backend serving multiple
  streams). Frame ingestion (`ingest_frame`) and partial-decode ticking
  (`run_due_partial_decodes`) are caller-driven (matches
  `PartialDecodeScheduler`'s existing time-injected style); `flush_stream`
  forces finalization for `client_flush`/`session_end`/
  `device_reconfigured`. Soft silence triggers a background completeness
  *decision* (heuristic first; only an ambiguous verdict -- and only when
  completeness checking is enabled and the shared `TranslationQueue`'s
  current depth is below `completeness_skip_queue_depth`
  (`should_skip_completeness`, Phase 07) -- consults the classifier) rather
  than blocking or auto-finalizing; hard silence and max-utterance duration
  remain handled synchronously inside `UtteranceSegmenter` itself
  (unchanged from Phase 04). On finalization, runs final ASR then one
  bounded translation attempt before publishing `utterance.final`
  (translation failure never blocks the transcription publish -- Phase 07's
  documented policy); a failed attempt schedules the single allowed retry
  in the background, publishing `translation.updated` if it later
  succeeds. At most the last two finalized sentences per stream are kept as
  translation context (`MAX_CONTEXT_SENTENCES`, Phase 07), captured once
  before the retry request is built so a retry's context never includes
  the utterance being retried.
  - **Race safety** (this phase's own required outcome -- "one utterance
    cannot finalize twice"): each utterance carries a monotonically
    increasing "pending generation" counter, bumped on every soft silence
    (a new decision), resumed speech (invalidates any decision in flight)
    and finalization for any reason (invalidates; already finalized). A
    soft-silence decision only acts (calling `segmenter.flush` with
    `semantic_complete`) if, at the moment it is ready to act, its captured
    generation still matches the current one for that utterance id *and*
    the segmenter still reports that same utterance as open -- both are
    re-checked immediately before acting, after any `await` (e.g. the
    completeness model round trip). Verified by
    `test_no_double_finalize_when_hard_silence_races_pending_decision` and
    `test_pause_resume_discards_stale_decision_no_early_finalize` in
    `tests/test_orchestration_pipeline.py`, which deliberately construct
    the race (a still-pending decision, then a competing hard-silence
    finalize or a speech resume) and assert exactly one `utterance.final`
    is ever published, with the correct `final_reason`.
  - The `TranslationQueue` (Phase 07, previously unconsumed) is used here
    as a live in-flight-work depth tracker for queue-pressure purposes: one
    placeholder item is `put` into the relevant priority lane for the
    duration of each final/retry/completeness attempt and `get` back out
    when it completes, so `qsize()` reflects real concurrent load across
    all streams in the session. This is a deliberately lighter-weight design
    than a full generic priority dispatcher (not required by this phase's
    outcomes): priority ordering for concurrently-*queued* work is achieved
    because `FinalTranslator`/`CompletenessClassifier` calls are dispatched
    as soon as they are ready and then wait on `FinalTranslator`'s own
    internal semaphore, whose FIFO admission order matches dispatch order;
    building a true generic drain-loop dispatcher is left as future work if
    a later phase's real-time gateway wiring needs it.
- Small, additive accessors needed by the above, backward compatible with
  Phase 04/06's existing tests: `UtteranceSegmenter.speech_ms` (read-only
  property exposing the existing internal counter) and
  `PartialTranscriber.current_text()` (exposes the last-published stable/
  unstable text without forcing a new decode).
- `shared/settings.py` + `.env.example`: added `completeness_max_tokens`,
  `completeness_min_confidence`, `completeness_heuristic_min_speech_ms`,
  `completeness_heuristic_max_unstable_tail_chars` and
  `translation_queue_capacity_per_priority`.

Not in this phase's scope (consistent with every prior phase's precedent
and this phase's own required outcomes, which do not mention the gateway or
WebSocket): wiring `UtteranceOrchestrator` into the live
`server/transport/gateway.py` WebSocket ingest path (feeding real released
audio frames in, sending published events out over the socket), and a
real-time asyncio loop driving `run_due_partial_decodes` off a wall clock.
See "Known limitations".

## Phase 09 deliverables

PySide6 client UI (`client/ui/`), split into a Qt-independent layer (fully
unit-tested) and a thin Qt-rendering layer (untestable in this environment
-- see "Known limitations" and `WINDOWS-UI-001`):

- `client/ui/view_model.py` (Qt-free): `LanguagePreset`
  (`VIETNAMESE_SIDE`/`JAPANESE_SIDE`/`CUSTOM`) and
  `resolve_preset_mapping` (docs/PRODUCT_REQUIREMENTS.md's fixed
  mic/loopback language mappings); `SourceConfig` (per-source device
  selection, enabled flag, language mapping); `CaptionEntry` (one
  utterance's display state) and `CaptionTimeline`, which applies inbound
  protocol events with the exact idempotency rules `docs/PROTOCOL.md`
  requires -- a partial at or below the currently-applied revision is
  ignored, a partial arriving after a final for the same utterance is
  ignored (cannot resurrect a stale hint), and a final always replaces a
  partial in place regardless of revision; `ClientViewModel`, the
  top-level state aggregator (connection state, device lists, per-source
  config, the timeline, settings load/save) with a `handle_event`
  dispatcher covering all four inbound event types
  (`transcription.partial`/`utterance.final`/`translation.updated`/
  `error`).
- `client/ui/settings_store.py` (Qt-free): `SettingsStore`, a plain JSON
  file persistence layer (deliberately not `QSettings`/the Windows
  registry, so it is unit-testable without Qt) for device selection,
  per-source enabled flags and the language preset -- explicitly
  excludes any token/secret field, matching this phase's "settings
  persistence without secrets" requirement (verified by a test asserting
  no token/password/secret-looking key appears in the saved file).
  `default_settings_path` resolves to `%APPDATA%\MeetingTranslator\
  client_settings.json` on Windows.
- `client/ui/session_controller.py` (Qt-free): `SessionController` runs
  an `AudioSender` reconnect loop (Phase 03) on a dedicated background
  thread with its own asyncio event loop; `parse_inbound_event` decodes a
  raw JSON dict into its typed protocol model
  (`TranscriptionPartial`/`UtteranceFinal`/`TranslationUpdated`/
  `ErrorEvent`), returning `None` for an unrecognized type (e.g.
  `audio.ack`, already handled internally by `AudioSender`) or a
  schema-invalid payload. `start`/`stop` manage the thread; `send_audio`
  marshals onto the background loop via `call_soon_threadsafe` since
  `asyncio.Queue.put_nowait` is not safe to call cross-thread. This class
  is the piece that makes a "thread-safe bridge from network worker to
  Qt signals" possible without putting any Qt code on the hot path: it
  has no Qt dependency itself, and the UI layer only has to call
  `Signal.emit()` from inside its callbacks (see below).
- `client/transport/sender.py` (Phase 03, extended): added
  `ConnectionState` (`DISCONNECTED`/`CONNECTING`/`CONNECTED`/
  `RECONNECTING`) and two optional `AudioSender` constructor callbacks --
  `on_state_change`, invoked by `run()` at well-defined lifecycle points
  (first connect reported as `CONNECTING`, a later reconnect as
  `RECONNECTING`, a successful handshake as `CONNECTED`, every
  disconnect/error as `DISCONNECTED`), and `on_message`, invoked with
  every successfully-parsed inbound JSON dict regardless of type (in
  addition to `AudioSender`'s own existing internal `audio.ack`/`error`
  handling, unchanged). Both are additive and optional; every existing
  Phase 03 test still passes unmodified.
- `client/ui/main_window.py` (PySide6; the only module besides
  `bootstrap.py`'s launcher that imports Qt): `MainWindow(QMainWindow)`
  wires the two Qt-free layers above to real widgets and real Windows
  audio capture (`client.audio.capture.CaptureContext` +
  `client.audio.windows_backend.PyAudioWPatchBackend`, both from Phase
  02, drained by a `QTimer` into `SessionController.send_audio`). A
  `_EventBridge(QObject)` with two `Signal(object)`s is the thread-safe
  bridge: `SessionController`'s callbacks (running on its background
  thread) call `.emit()` directly, and Qt's own cross-thread queued
  -connection delivery (the standard PySide6 pattern for this -- no
  manual locking/queueing needed) marshals the call onto the main
  thread's slot, which updates `ClientViewModel` and re-renders. Caption
  rendering uses one `QLabel` (rich text) per utterance via
  `QListWidget.setItemWidget`: a gray partial hint with stable text in a
  darker shade and an italicized lighter unstable tail (both visually
  distinct, not just via color -- also distinguished by style), a bold
  final transcription, a normal-weight translation line below it, and a
  colored retry/failure line when applicable. An explicit `setTabOrder`
  chain and a larger-than-default caption font address the phase's
  accessibility/keyboard-navigation requirement. Settings are loaded on
  startup and saved on every control change and on window close.
  - **This file cannot be imported, executed or type-checked against a
    real Qt runtime in this development environment** (no PySide6
    installed, no Windows audio hardware). `ruff format`/`ruff check`
    pass (they only parse the AST, not import the code), and `mypy`
    passes using the existing `PySide6.*` -> `ignore_missing_imports`
    override (both Qt base classes required one `# type:
    ignore[misc]` each, since mypy's `strict`/`disallow_subclassing_any`
    flags subclassing an `Any`-typed base even with that override -- a
    known, unavoidable limitation of type-checking Qt code without real
    stubs, not a suppressed real error). Beyond that static review, this
    file was entirely unverified until run on real Windows hardware --
    now done: the `WINDOWS-UI-001`-`WINDOWS-UI-007` manual sequence
    (2026-08-12 to 2026-08-13) found and fixed four real bugs and
    confirmed the rest works correctly; see "Known limitations" for
    detail. `client/ui/main_window.py` is now HARDWARE_VERIFIED.

Not in this phase's scope (consistent with prior-phase precedent, and
the `WINDOWS-UI-*` actions said so explicitly so a PASS there was not
misread as covering it): VAD/ASR/translation are still not wired into the live
gateway ingest path (Phase 08's own "Known limitations"), so even a fully
working, connected UI will not display live captions yet -- only the
connect/disconnect lifecycle and (once the gateway sends real events) the
caption-rendering path itself are this phase's concern. See "Known
limitations".

## Phase 10 deliverables

Reliability, security and observability, per
`prompts/phases/10_RELIABILITY_SECURITY_OBSERVABILITY.md`'s required
outcomes. Everything below is pure/local/CPU-testable or a real in-process
FastAPI `TestClient`/WebSocket integration test -- no GPU or Windows
hardware is required for any of it, so no `MANUAL_ACTIONS.md` entry was
needed.

- **JWT authentication** (`server/transport/auth.py`): `JwtAuthenticator`
  using `PyJWT[crypto]`, asymmetric (`RS256`) only -- construction rejects
  `HS*` symmetric algorithms explicitly, since a symmetric secret
  configured as if it were a "public" key would let anyone who can read
  server config forge tokens. Verifies signature, issuer, audience, expiry
  (with configurable leeway) and requires a non-empty string `sub` claim;
  rejects the classic `alg: none` attack by passing `algorithms=[...]`
  explicitly to `jwt.decode`. Error messages are generic and never contain
  the raw token. `server/app.py`'s `_build_authenticator` selects it only
  when `JWT_PUBLIC_KEY_PATH` is set and fails fast (at app construction) if
  that path is unreadable; otherwise falls back to the existing
  `StaticTokenAuthenticator` dev path. Tested against real, locally
  -generated RSA keypairs (`cryptography`), fully offline --
  `tests/test_transport_auth_jwt.py` (18 tests) and
  `tests/test_app_jwt_wiring.py` (4 tests, including a full real WS
  handshake with a validly-signed token).
- **Reliability primitives** (`server/reliability/`): `CircuitBreaker`
  (CLOSED/OPEN/HALF_OPEN, pure and time-injected via an optional `now_fn`,
  single-trial half-open recovery) and `ShutdownCoordinator` (flips
  readiness immediately on shutdown start; the actual bounded drain-wait
  loop lives in `server/app.py`'s `lifespan` handler, kept out of the pure
  coordinator so it stays unit-testable without asyncio).
  `tests/test_reliability_circuit_breaker.py` (10) and
  `tests/test_reliability_shutdown.py` (4).
  - Wired into both `FinalTranslator` (`server/translation/worker.py`) and
    `FinalTranscriber` (`server/asr/worker.py`) via an optional
    `circuit_breaker=` constructor param: when open, a call is skipped
    before it ever reaches the backend (`issue="circuit_open"` for
    translation; a retryable `AsrCircuitOpenError` mapping to
    `ErrorCode.OVERLOADED` for ASR) instead of piling more load onto an
    already-struggling GPU host. Deliberately *not* wired into
    `CompletenessClassifier`: that call is already skipped under queue
    pressure (`should_skip_completeness`, Phase 07/08) and already has its
    own strict timeout, so a second overload mechanism would be redundant
    for a check that is optional and low-priority by design.
    `tests/test_translation_worker.py` (+4) and `tests/test_asr_worker.py`
    (+3) cover short-circuiting without calling the backend, success/
    failure recording, and metrics.
- **Observability** (`server/observability/`): `correlation.py` binds
  `session_id`/`stream_id`/`utterance_id`/`request_id` via `contextvars`
  (async-safe, unlike thread-locals) and injects them into every log
  record through `CorrelationFilter`; `metrics.py`'s `Metrics` dataclass
  (via `prometheus_client`) covers `sessions_active`,
  `packets_received_total`/`packets_lost_total`/`packets_duplicate_total`
  (labeled by source), `translation_requests_total` (priority + status),
  `translation_latency_seconds` (priority), `asr_latency_seconds` (stage),
  `translation_queue_depth` (priority) and `circuit_breaker_state`
  (backend). `create_metrics()` gives every test (and, if ever needed,
  every process) its own isolated `CollectorRegistry`, avoiding the
  global-registry duplicate-metric-name collision that would otherwise
  make per-test isolation impossible. `tests/test_observability_correlation.py`
  (8) and `tests/test_observability_metrics.py` (5).
  - Wired into `server/transport/gateway.py` (already existed going into
    this phase's own work in an earlier pass: `sessions_active`,
    `packets_received_total`/`packets_lost_total`/`packets_duplicate_total`,
    and `session_id`/`stream_id` correlation binding) and, this phase,
    into `server/orchestration/pipeline.py`'s `UtteranceOrchestrator`:
    `translation_requests_total`/`translation_latency_seconds` (via
    `FinalTranslator`), `asr_latency_seconds` (via `FinalTranscriber`),
    `translation_queue_depth` (updated in `_pressure_slot` on both
    admission and release) and `circuit_breaker_state`, plus
    `utterance_id`/`request_id` correlation binding around
    `_finalize_utterance`/`_retry_translation` (a fresh `request_id` per
    attempt). `tests/test_orchestration_pipeline.py` (+2: metrics recorded
    and queue depth returns to 0; correlation ids bound only during the
    final-event publish, not during partial-decode publishes, and never
    leak outside the bound block).
  - **Caveat**: `UtteranceOrchestrator` is still not constructed or wired
    into the live gateway WebSocket ingest path (unchanged from Phase 08's
    "Known limitations" -- this phase did not change that). So today, in
    the actually-running application, only the gateway-level metrics
    (`sessions_active`, `packets_*`) and `session_id`/`stream_id`
    correlation are live; `translation_requests_total`,
    `translation_latency_seconds`, `asr_latency_seconds`,
    `translation_queue_depth`, `circuit_breaker_state` and
    `utterance_id`/`request_id` correlation are fully implemented, wired
    into the constructors and exercised by real integration tests, but
    will only appear in a real running deployment's `/metrics` once a
    later phase wires `UtteranceOrchestrator` into the gateway.
- **Server-wide session cap**: `SessionManager` gained a `max_sessions`
  parameter (`WS_MAX_SESSIONS`, default 500) distinct from the pre-existing
  per-session `max_streams_per_session` cap -- the former bounds total
  resource usage across all clients, the latter bounds one client's fan
  -out. Enforced twice (defense in depth): `gateway._handshake` pre-checks
  and rejects with `OVERLOADED`/retryable before even attempting
  `create_session`, and `SessionManager.create_session` itself also
  raises. `tests/test_transport_session.py` (+3).
- **`server/app.py`** (rewritten this phase): FastAPI `lifespan` handler
  (replacing the older `@app.on_event` style) coordinates graceful
  shutdown -- `/health/ready` flips to not-ready the instant shutdown
  begins, then the handler waits, bounded by `SHUTDOWN_DRAIN_TIMEOUT_MS`,
  polling `ShutdownCoordinator.drained()` every 100ms for active sessions
  to finish, logging a warning (session count only) on timeout rather than
  silently killing in-flight work. `/health/ready` also gained an opt-in
  (`READINESS_CHECK_TRANSLATION_BACKEND`) best-effort reachability probe
  against the translation backend (`_check_translation_backend`, injectable
  `httpx.AsyncBaseTransport` for tests, bounded by
  `READINESS_CHECK_TIMEOUT_MS`) that never surfaces raw exception/hostname
  detail into the response -- only a boolean. New `/metrics` route returns
  Prometheus text-format output. `tests/test_health.py` (+3),
  `tests/test_app_translation_backend_check.py` (5, `httpx.MockTransport`,
  no real network), `tests/test_app_metrics_endpoint.py` (2).
- **Redaction strengthened and proven end-to-end**
  (`shared/logging.py`/`tests/test_logging_redaction.py`,
  `tests/test_logging_no_content_leak.py`): `_KV_SECRET_RE` (the pattern
  that catches a secret embedded directly in free-form message text, e.g.
  `f"transcript={text}"`, as opposed to a structured log extra) now covers
  every hint in `SENSITIVE_KEY_HINTS` (previously only the
  password/token/secret family; `transcript`/`translation`/`prompt`/
  `audio`/`jwt` were only redacted when passed as a separate structured
  extra, not when embedded inline in message text -- a real gap for any
  future `f"transcript={x}"`-style call site). More importantly, a new
  `tests/test_logging_no_content_leak.py` (4 tests) proves the actual
  requirement end-to-end rather than just testing the filter in isolation:
  it drives the real `FinalTranscriber`, `FinalTranslator` and full
  `UtteranceOrchestrator` pipeline with distinctive marker text standing in
  for transcript/translation content, captures every log record emitted
  anywhere in the process during the run, and asserts the marker never
  appears -- including a negative-control test proving the harness really
  would catch a leak if one occurred (so the "no marker found" assertions
  are meaningful, not vacuous).
- **Server restart / client reconnect tests**: since this project has no
  real second server process to restart, "server restart" is tested from
  both sides of the same real contract instead of simulated end-to-end:
  `tests/test_transport_sender.py`'s new
  `test_run_reconnect_after_server_restart_resends_only_unacked_frames`
  proves the client-side `AudioSender` only resends frames still unacked
  after a reconnect (not a blind full resend of everything ever sent), and
  `tests/test_transport_gateway.py`'s new
  `test_reconnect_after_connection_drop_gets_a_clean_session` proves the
  real gateway accepts a fresh connection that resends the same session/
  stream ids and sequence numbers from scratch as an ordinary new session,
  with no stale cross-connection state and no crash -- exactly what
  `AudioSender`'s reconnect/resend does against a server that has actually
  restarted (no session-manager memory of the old connection survives a
  real process restart, so this is a faithful model of that scenario even
  though both tests run against the same live process).
- **`docs/SECURITY.md`** (new): authentication requirements (including the
  operationally important "`APP_ENV=production` alone does not enable JWT
  auth -- `JWT_PUBLIC_KEY_PATH` must also be set" gap), transport, request/
  packet/session/queue limits table, the privacy/redaction guarantee and
  how it's proven, correlation ids, readiness leak-safety, overload/circuit
  -breaker behavior, graceful shutdown, secrets handling, the dependency
  -pinning strategy (why `>=X,<Y`, why the GPU extra is looser, why
  `websockets` is pinned narrower than the rest), and a pre-deployment
  security review checklist.
- **`docs/DEPLOYMENT.md`** (new): TLS/reverse-proxy guidance -- what the
  proxy must do (terminate TLS, forward the WebSocket `Upgrade`/
  `Connection` headers, use a long idle timeout on the WebSocket route
  specifically since a meeting session's socket is legitimately long-lived,
  forward `/health/*`, decide whether `/metrics` is reachable outside the
  internal network), a complete nginx example and a complete Caddy example,
  client-side `CLIENT_SERVER_URL` guidance, and how this relates to
  `deployment/docker-compose.yml`'s existing local-only skeleton.
- `pyproject.toml`: added `PyJWT[crypto]>=2.8,<3` and
  `prometheus-client>=0.20,<1` to the `server`/`dev` extras.
  `shared/settings.py`/`.env.example`: added `ws_max_sessions`,
  `jwt_algorithm`, `jwt_leeway_seconds`,
  `readiness_check_translation_backend`, `readiness_check_timeout_ms`,
  `shutdown_drain_timeout_ms`, `circuit_breaker_failure_threshold`,
  `circuit_breaker_reset_timeout_ms`.

Not in this phase's scope (consistent with every prior phase's precedent):
wiring `UtteranceOrchestrator` into the live gateway ingest path remains
Phase 08's original, still-open gap -- this phase made the orchestrator's
own metrics/circuit-breaker/correlation wiring real and tested, but did not
close that separate gateway-wiring gap, which was never assigned to this
phase's required outcomes either. See "Known limitations".

## Phase 11 deliverables

End-to-end tests and packaging, per
`prompts/phases/11_E2E_PACKAGING.md`'s required outcomes. See
`docs/FINAL_IMPLEMENTATION_REPORT.md` for the full line-by-line
`docs/ACCEPTANCE_CRITERIA.md` walkthrough this phase produced; this
section covers what was built and how it was verified.

- **End-to-end mocked test** (`tests/test_e2e_mocked_pipeline.py`, 2
  tests): the first test in this project to compose *every* layer in one
  in-process test -- real binary packet encode/decode
  (`shared/protocol/binary.py`) -> a real `UtteranceOrchestrator`
  (VAD -> partial ASR -> final ASR -> translation, scripted backends) ->
  real published protocol events -> a real `ClientViewModel.handle_event`
  (the same Qt-independent state layer `client/ui/main_window.py` renders
  from) -> asserted final caption/translation UI state. A second test
  proves `docs/ACCEPTANCE_CRITERIA.md`'s "Translation failure still
  publishes final transcription" through this same full chain, not just
  at the worker level. Does **not** exercise the live WebSocket gateway
  (see "the one gap that matters most" below) -- constructs
  `UtteranceOrchestrator` directly, the same way every orchestration test
  since Phase 08 has.
- **Optional GPU end-to-end test** (`tests/test_e2e_gpu.py`, `gpu`-marked,
  skips locally via `find_spec("faster_whisper")`, matching
  `tests/test_windows_audio.py`'s existing skip-marker pattern): a real
  `WhisperAsrModel` + real `VllmTranslationClient` (plain `httpx`, no
  `vllm` package needed to *call* an already-running server) driven
  through a real `UtteranceOrchestrator`, fed a locally-synthesized sine
  tone (no bundled/personal audio content, matching `GPU-ASR-004`'s
  precedent) for ~1.5s then silence to force deterministic hard-silence
  finalization. Asserts exactly one `utterance.final` with real recorded
  ASR latency and no exception -- deliberately does not assert
  transcription *content* accuracy on a synthetic tone (that was already
  separately hardware-verified with real speech by
  `GPU-ASR-005`/`GPU-TRANSLATE-007`). Staged as `GPU-E2E-001` in
  `MANUAL_ACTIONS.md`.
- **Concurrent-meetings load scenario**
  (`tests/test_load_concurrent_meetings.py`, 1 deterministic test, no real
  sleep-based timing): six independent `UtteranceOrchestrator` instances
  (simulating six concurrent meetings, the dimension Phase 08's own
  race-safety tests never covered -- those proved exactly-once
  finalization *within* one session) sharing one fake translation backend
  and one process-wide `Metrics` instance, driven concurrently via
  `asyncio.gather` so their finalizations land in the same event-loop tick
  window. The shared backend forces a validation-failure "queue spike" of
  retry work for half the sessions. Asserts: real concurrent overlap
  happened (`max_active >= 2`, proven the same way
  `test_bounded_concurrency_is_respected` proves it for one session);
  every session finalizes exactly once with correct, uncontaminated
  session/stream/utterance attribution; retry-forced sessions correctly
  publish a `translation.updated`; `Counter`-based metrics accumulate
  correctly across sessions. **This test is what surfaced the
  `translation_queue_depth` Gauge cross-session limitation** documented
  below and in `docs/OPERATOR_RUNBOOK_SEED.md`.
- **Latency measurement tooling** (`scripts/latency_report.py`): feeds
  synthetic utterances through a real `UtteranceOrchestrator` with frames
  paced at real 20ms intervals, reporting real measured p50/p95/p99 for
  `first_partial_ms`, `asr_final_ms` (read directly from
  `UtteranceFinal.latency.asr_final_ms`), `end_to_end_ms` and a labeled
  `translation_ms_approx` -- never a hard-coded pass/fail (the phase's own
  required wording). Supports `--real-backends` for genuine GPU-backed
  numbers (staged as `LATENCY-001` in `MANUAL_ACTIONS.md`) and
  `--fake-*-delay-ms` to simulate backend latency locally. **Actually run
  in this session** (not just written): a local smoke run
  (`--count 3`) produced real numbers (e.g. `asr_final_ms` p50 0.0ms
  against instant fakes; with `--fake-asr-delay-ms 150
  --fake-translation-delay-ms 100`, `asr_final_ms` p50 correctly read back
  ~149ms), confirming the tool measures what it claims to.
- **Load-test tooling** (`scripts/load_test.py`): opens N real concurrent
  WebSocket sessions (via the real `websockets` client library) against a
  real running server, exercising the real transport/gateway layer
  (handshake, binary audio ingest, batched acks, rate/session limits) --
  explicitly documented as *not* exercising VAD/ASR/translation, since the
  gateway doesn't drive those yet. Reports real packet/ack counts and ack
  round-trip percentiles, never a pass/fail verdict. **Actually run in
  this session**: `websockets`/`uvicorn` were installed, a real local
  `uvicorn server.app:app` instance was started, and `load_test.py --url
  ws://127.0.0.1:8099/ws/stream --sessions 5 --duration-s 3` was run
  against it -- 5/5 sessions connected, 496 packets sent, 70 acks
  received, real ack-RTT percentiles reported (both table and `--json`
  output modes confirmed working).
- **Windows client packaging** (`scripts/build_windows_client.py`,
  `packaging/entrypoint.py`, new `packaging` extra in `pyproject.toml`):
  drives PyInstaller with `--hidden-import pyaudiowpatch` (needed because
  `client/audio/windows_backend.py` imports it lazily inside a function,
  which PyInstaller's static scan doesn't always catch on its own).
  **A real build was actually performed and verified to succeed in this
  session**: real `PySide6`/`PyAudioWPatch`/`pyinstaller` were installed
  (this dev environment's OS is Windows, per the system platform, even
  though these packages are normally absent from the CPU-only baseline),
  `python scripts/build_windows_client.py --clean` ran PyInstaller's full
  analysis/build pipeline against the real dependency graph (PySide6
  widgets/plugins, PyAudioWPatch, this project's own `client`/`shared`
  packages) with no import errors, and produced a real one-directory build
  (`dist/MeetingTranslator-0.1.0/MeetingTranslator-0.1.0.exe`, ~120 MB
  total). The build output was deleted afterward (`build/`/`dist/` are
  already excluded from local snapshots by `scripts/backup_common.py`) and
  the temporarily-installed packages were uninstalled to restore the
  documented baseline environment (see "Commands last run locally"). **A
  successful build is not the same as a hardware-verified working
  application on its own** -- consistent with `CLAUDE.md`'s "never claim
  hardware verification from mocks," this was staged as
  `WINDOWS-PACKAGE-001` in `MANUAL_ACTIONS.md` rather than assumed. **The
  user has since run that action and it PASSED (2026-08-14)**: a fresh
  venv, a real PyInstaller build, and the packaged `.exe` launched with a
  real window title, real device dropdowns, and clean Connect/Disconnect
  against a local dev server (Vietnamese-speech WAV playing for the
  loopback path), no traceback or exception. See `USER_RESULTS.md`'s
  `WINDOWS-PACKAGE-001` entry. This is a UI/connectivity check only, not
  evidence of live captions (see "the one gap that matters most" below).
- **Version metadata and upgrade strategy**: `shared/version.py`
  (`__version__ = "0.1.0"`, bumped from the placeholder `0.0.0`), synced
  with `pyproject.toml`'s `[project] version` and enforced by
  `tests/test_version.py` (2 tests). `server/app.py`'s FastAPI app and
  `client/ui/main_window.py`'s window title (`f"Meeting Translator
  v{__version__}"`) both now read this single source instead of a
  separate hardcoded literal. `docs/DEPLOYMENT.md`'s new "Version metadata
  and upgrade strategy" section covers semantic-versioning meaning,
  `PROTOCOL_VERSION`-gated compatibility (server-first rollout on any
  protocol change), the client's no-auto-updater replace-the-exe model and
  why `SettingsStore`'s partial-document tolerance makes that safe, and
  the server's drain-then-replace upgrade path.
- **Docker Compose production-like example**
  (`deployment/docker-compose.prod.yml`, `deployment/monitoring/`): adds
  Prometheus (scraping the real `/metrics` endpoint via
  `deployment/monitoring/prometheus.yml`) and Grafana (with Prometheus
  auto-provisioned as its default data source) alongside the application
  server and Redis; a real `/health/ready`-based container healthcheck.
  Treats the translation GPU backend as a genuine external dependency
  (`VLLM_BASE_URL` via `.env`), never started by this file, consistent
  with the existing local `docker-compose.yml`'s GPU-exclusion precedent.
  All four YAML files (this one, the existing `docker-compose.yml`, and
  the two new monitoring config files) were parsed with `pyyaml` and
  confirmed structurally valid (`services`/`volumes` keys, healthcheck
  `test` list) -- `docker compose config` itself could not be run (Docker
  is not installed in this environment), so this is YAML-syntax
  verification, not a real `docker compose up` verification.
- **Administrative runbook** (`docs/OPERATOR_RUNBOOK_SEED.md`, expanded
  from a seed/outline into full content for every section its own
  "Required runbook sections" list named): prerequisites/GPU compatibility
  (including the real `flashinfer` bug and single-shared-GPU caveat from
  `USER_RESULTS.md`), faster-whisper model download/verification,
  application start/readiness, Windows client installation, a metrics
  -to-alert-meaning table for every Phase 10 metric (including the
  `translation_queue_depth` caveat below), queue-pressure response, ASR/
  vLLM OOM response, client reconnect/device-change troubleshooting (with
  pointers to the real `WINDOWS-UI-*` bug history), safe shutdown (tied to
  `ShutdownCoordinator`), privacy-preserving diagnostics, and backup/
  restore scoped explicitly to configuration, never content.
- **Final README** (`README.md`, fully rewritten): quick starts for
  CPU-mocked development, Windows client development, and GPU deployment;
  repository layout; pointers to `IMPLEMENTATION_STATUS.md` and the new
  `docs/FINAL_IMPLEMENTATION_REPORT.md`; the local-only/no-Git development
  workflow explanation preserved (in English, condensed) rather than
  duplicated at length.
- **Complete acceptance-criteria review**
  (`docs/FINAL_IMPLEMENTATION_REPORT.md`, new): every line of
  `docs/ACCEPTANCE_CRITERIA.md`, tagged VERIFIED / LOCAL_VERIFIED /
  HARDWARE_VERIFIED / HARDWARE_PENDING with evidence pointers. Its most
  important finding is repeated here because it affects how every other
  claim in this document should be read:

  **"The one gap that matters most": `UtteranceOrchestrator` is still not
  wired into the live gateway WebSocket ingest path** (true since Phase
  08, never assigned to any phase's required outcomes, still true after
  Phase 11). A real client connected to a real running server today will
  not see live captions. Every piece is real and tested -- including, now,
  a real end-to-end *mocked* composition (`test_e2e_mocked_pipeline.py`)
  and a real end-to-end *GPU-backed* composition
  (`test_e2e_gpu.py`) -- but neither goes through the WebSocket gateway,
  because the gateway does not yet drive the orchestrator. This is the
  natural next phase of work.
- **A real, newly-found metrics limitation**: `translation_queue_depth`
  (a Prometheus `Gauge`) does not aggregate correctly when multiple
  concurrent `UtteranceOrchestrator` sessions in the same process share
  one `Metrics` instance -- each session's own reading overwrites the
  gauge rather than summing, so it is not a reliable system-wide total
  today (found by `tests/test_load_concurrent_meetings.py`; documented in
  `docs/OPERATOR_RUNBOOK_SEED.md`'s metrics table and
  `docs/FINAL_IMPLEMENTATION_REPORT.md`). `translation_requests_total` (a
  `Counter`) does not have this problem. Not fixed in this phase --
  flagged for whoever revisits Phase 10's metrics design, since redesigning
  it (e.g. a per-session label, which has its own high-cardinality
  tradeoffs) was not part of this phase's required outcomes.

## User-provided hardware results

- WINDOWS-AUDIO-001 (PASSED, 2026-08-10): see `USER_RESULTS.md`. Unchanged by
  Phase 05.
- GPU-ASR-001 (PASSED, 2026-08-10): see `USER_RESULTS.md`. ASR GPU host
  confirmed capable (H100 80GB, CUDA 13.0, Python 3.11.13).
- GPU-ASR-002 (INCONCLUSIVE, 2026-08-11): see `USER_RESULTS.md`.
  `faster-whisper` 1.2.1 installed; the action's `torch` check was invalid
  (not a project dependency) and proved nothing about GPU readiness.
  Superseded by GPU-ASR-003.
- GPU-ASR-003 (PASSED, 2026-08-11): see `USER_RESULTS.md`. `ctranslate2`
  4.8.1 sees 1 CUDA device on the H100; real venv path confirmed as
  `/workspace/meetting-translator/.venv-asr`. `libcudnn` not seen via
  `ldconfig` — not disqualifying per this action's own criteria, but left as
  an open question for GPU-ASR-004's real model load.
- GPU-ASR-004 (PASSED, 2026-08-11): see `USER_RESULTS.md`. `large-v3`
  (revision `edaa852ec7e145841d8ffdb056a99866b5f0a478`) loaded (3.66s) and
  decoded a synthetic tone (0.29s) with no CUDA/cuDNN/cuBLAS error, resolving
  GPU-ASR-003's open cuDNN question.
- GPU-ASR-005 (PASSED, 2026-08-12): see `USER_RESULTS.md`. No exception,
  `segments > 0` for both languages, fluent well-formed vi/ja text; user
  confirmed both transcripts roughly accurate.
- GPU-TRANSLATE-001 (PASSED, 2026-08-12): see `USER_RESULTS.md`. Same H100
  80GB host as ASR (single GPU, shared, not separate as recommended); ample
  RAM/CPU/disk; no errors.
- GPU-TRANSLATE-002 (PASSED, 2026-08-12): see `USER_RESULTS.md`.
  `Qwen/Qwen3.6-27B-FP8` downloaded (revision
  `e89b16ebf1988b3d6befa7de50abc2d76f26eb09`, ~29-30.9 GB, 8m11s); no
  exception.
- GPU-TRANSLATE-003 (FAILED, 2026-08-12): see `USER_RESULTS.md`. vLLM
  launch crashed on a third-party `flashinfer` `array.array[int]`
  `TypeError` during `torch.compile` backend setup; root-caused, not
  project-caused. Retried as GPU-TRANSLATE-004 with `--enforce-eager`.
- GPU-TRANSLATE-004 (FAILED, 2026-08-12): see `USER_RESULTS.md`.
  `--enforce-eager` fixed the targeted crash (model construction and KV
  -cache sizing succeeded), but a second import path hit the identical
  `flashinfer` `array.array[int]` bug.
- GPU-TRANSLATE-005 (PASSED, 2026-08-12): see `USER_RESULTS.md`. Direct
  `flashinfer` patch resolved the bug; server reached full startup;
  72237/81559 MiB GPU memory in use; no traceback.
- GPU-TRANSLATE-006 (PASSED, 2026-08-12): see `USER_RESULTS.md`. `/health`
  returned 200; `/v1/models` confirmed `id=qwen3.6-27b-translate` with
  matching `root`/`max_model_len`. No error.
- GPU-TRANSLATE-007 (PASSED, 2026-08-12): see `USER_RESULTS.md`. Real
  JA->VI and VI->JA translation requests through the project's own prompt
  -building code both returned 200 OK, no exception; outputs plausible and
  correctly scripted per Claude's linguistic assessment (see "Known
  limitations" for the caveat that the user did not separately state an
  explicit plausibility verdict). Last of Phase 07's staged GPU
  checkpoints.
- WINDOWS-UI-001 (PARTIALLY PASSED, 2026-08-12): see `USER_RESULTS.md`.
  Basic smoke test (window, devices, controls, keyboard nav, font,
  settings persistence) fully PASSED. Connect/Disconnect flow FAILED with
  two real bugs, both root-caused and fixed (see "Known limitations"):
  a `websockets` import incompatible with the pinned `<13` range, and a
  background-thread-crash cleanup gap. `WINDOWS-UI-002` re-verifies the
  fix.
- WINDOWS-UI-002 (PASSED, 2026-08-13): see `USER_RESULTS.md`. Both fixes
  confirmed: clean connect/disconnect with no server (both device
  patterns, close-while-connected) and a real connected session against a
  local dev server, no exceptions. Server log revealed a new,
  separately-tracked finding: every session hit `idle timeout` rather
  than staying open, suggesting audio frames are not reaching the server.
  `WINDOWS-UI-003` investigates with new diagnostic logging.
- WINDOWS-UI-003 (PASSED, 2026-08-13): see `USER_RESULTS.md`. Diagnostic
  logging confirmed the microphone capture/send pipeline works correctly
  end-to-end (continuous frames, matching sent count, no idle timeout,
  clean disconnect). Loopback opened but produced zero chunks/frames the
  whole test; leading hypothesis is no active playback on the output
  device (documented WASAPI behavior), not a bug. `WINDOWS-UI-004`
  re-confirms.
- WINDOWS-UI-004 (PASSED, 2026-08-13): see `USER_RESULTS.md`. With audio
  actively playing, loopback confirmed working both alone and together
  with microphone, both sources' counters climbing correctly in
  parallel. Confirms no code bug -- the audio pipeline is
  HARDWARE_VERIFIED for both sources. Diagnostic logging removed
  afterward; `WINDOWS-UI-005` is the final regression check.
- WINDOWS-UI-005 (PASSED, 2026-08-13): see `USER_RESULTS.md`.
  Diagnostic-logging removal confirmed safe. Surfaced a new finding:
  `jitter overflow` warnings on the server, root-caused to the
  capture-send timer starting before the handshake completed. Fixed
  (defer timer start to first CONNECTED). `WINDOWS-UI-006` re-verifies.
- WINDOWS-UI-006 (PASSED, 2026-08-13): see `USER_RESULTS.md`. Confirmed
  the `jitter overflow` fix (no warning this time). Surfaced a further
  finding: ~5s UI freeze on Disconnect plus a delayed reconnect/
  idle-timeout ~15s later, root-caused to `_pump_incoming` blocking
  indefinitely on a real `recv()` and never noticing `stop`. Fixed
  (poll `recv()` with a short timeout). `WINDOWS-UI-007` re-verifies.
- WINDOWS-UI-007 (PASSED, 2026-08-13): see `USER_RESULTS.md`. "Everything
  is good. OK. No traceback/error or exception." Confirms the
  `_pump_incoming` fix -- Disconnect now updates promptly with no delayed
  reconnect or server-side idle timeout. Closes out Phase 09's manual
  -verification sequence; no further Phase 09 manual action is pending.

## Known limitations

- `whisper_device` defaults to `cuda`; CPU-only local runs do not load ASR.
- GPU dependency group: the host is confirmed capable (GPU-ASR-001 PASSED),
  `faster-whisper` 1.2.1 is installed on the GPU host venv (GPU-ASR-002),
  `ctranslate2` confirms the GPU is visible and enumerable (GPU-ASR-003
  PASSED), and a real `large-v3` model load + decode succeeded with no
  CUDA/cuDNN/cuBLAS error (GPU-ASR-004 PASSED), and GPU-ASR-005 confirmed the
  real adapter produces plausible transcripts on real vi/ja speech, per the
  user's own judgment (PASSED 2026-08-12). The ASR adapter itself is now
  hardware-verified end-to-end on a two-sample plausibility basis; scored
  accuracy/latency benchmarking across more samples has not been done.
- `WhisperAsrModel` is implemented, hardware-confirmed for model-load/decode
  (GPU-ASR-004), and hardware-confirmed for real-speech plausibility in both
  target languages (GPU-ASR-005, user-judged roughly accurate). It is still
  excluded from the CPU suite (needs the GPU/model weights). Scored accuracy
  and latency across a larger sample set remain unmeasured/future work.
- The `FinalTranscriber` is not yet wired into the gateway/VAD ingest path;
  connecting utterance finalization to real audio and emitting `utterance.final`
  over the socket is integrated in a later phase. Translation is not attached
  yet (events carry `translation=null` / status `pending`).
- The gateway validates, orders and acknowledges audio but does not yet forward
  released frames into the `UtteranceSegmenter`; wiring VAD into the ingest path
  (and running probabilities off the event loop) lands with the ASR phases.
- `PartialTranscriber`/`PartialDecodeScheduler` (Phase 06) are implemented and
  unit-tested with a scripted model, but not yet wired into the gateway/VAD
  ingest path or driven by a live asyncio loop — same status as
  `FinalTranscriber`. `transcription.partial` events are not yet actually
  published over a real socket. Not hardware-verified: `PartialTranscriber`
  uses the same `WhisperAsrModel`/`AsrModel` interface already
  hardware-verified for final decoding (GPU-ASR-004/005), but no GPU-side
  smoke test has exercised `partial_beam_size`/the partial code path
  specifically; that would be natural follow-up manual work if/when this
  phase's output is integrated, not required to close Phase 06's own scope
  (which is local domain logic per `prompts/phases/06_WHISPER_PARTIAL.md`).
- **Bug fix: client reconnect cancellation race** (2026-08-11, investigated
  and fixed at the user's request, separate from Phase 06's own scope).
  `tests/test_transport_sender.py::test_run_reconnects_and_resends_pending`
  (Phase 03) was timing out deterministically (2s) in this environment;
  reproduced in a minimal script with no project code involved. Root cause:
  `AudioSender._serve()` (`client/transport/sender.py`) cancelled its two
  pump tasks exactly once each in a `finally` block. A single
  `Task.cancel()` call can race with the task's currently-awaited future
  resolving just beforehand and be silently swallowed — a documented
  asyncio subtlety, not a Windows-only bug, though it manifested here on
  this platform/loop's scheduling timing — leaving `_pump_outgoing` running
  forever instead of stopping, so `asyncio.gather()` in the `finally` block
  never returned and the whole reconnect loop hung. Fixed by extracting a
  `_cancel_and_wait` helper that retries `cancel()` in a loop until every
  task actually finishes, instead of a single fire-and-forget cancel. Local
  snapshot `.local_backups/20260811T182415Z_sender-cancel-race-fix.zip`
  taken before the change. Verified: the previously-hanging test now passes
  in 0.117s; full suite is 187 passed / 0 failed / 2 deselected; `ruff
  format`/`ruff check`/`mypy` remain clean.
- `SileroVadModel` is implemented but unverified: it is excluded from the CPU
  suite and requires `torch`/`silero_vad` weights, so real VAD accuracy is not
  yet hardware-verified. Segmentation logic is verified with scripted
  probabilities only.
- Translation (Phase 07) is implemented and unit-tested (scripted client +
  `httpx.MockTransport`; no real vLLM), and is now verified end-to-end with
  a real translation request: `GPU-TRANSLATE-001` through
  `GPU-TRANSLATE-007` all PASSED 2026-08-12 -- the server is running,
  reached full startup, answers OpenAI-compatible requests, and a real
  JA->VI/VI->JA translation request through the project's own
  prompt-building code returned plausible, correctly-scripted output for
  both directions with no exception. Caveat: the JA/VI plausibility
  judgment for `GPU-TRANSLATE-007` was made by Claude (fluent in both
  languages) from the raw output, since the user's report did not include
  a separate explicit first-person verdict the way `GPU-ASR-005` did ("yes,
  the printed text is a roughly accurate rendering"); if a native speaker's
  review later disagrees, this should be revisited. `VllmTranslationClient`
  itself is now HARDWARE_VERIFIED against real hardware; wiring it into the
  live gateway/VAD/ASR pipeline and scored accuracy/latency benchmarking
  remain separate, not-yet-started work (Phase 08 and later).
- The `flashinfer` package installed alongside `vllm==0.27.1` (unpinned
  `pip install vllm`) had a real bug: `flashinfer/comm/fd_exchange.py`
  used `array.array[int]` as a type annotation, which always raises
  `TypeError` at import time since `array.array` has no
  `__class_getitem__`. This surfaced via multiple, independent vLLM code
  paths that import `flashinfer.comm` unconditionally (confirmed two:
  `torch.compile` backend setup via `AllReduceFusionPass`, and
  `kernel_warmup`'s unconditional MiniMax-M3 warmup import), even though
  this is a single-GPU deployment of an unrelated model (Qwen3.5) where
  neither needed to run. `--enforce-eager` (GPU-TRANSLATE-004) fixed only
  the first path; `GPU-TRANSLATE-005` patched the broken line directly in
  the installed package (quoting the invalid annotation so it is never
  evaluated -- no behavior change), which fixed every remaining import
  path at once and the server now starts successfully. This is a local,
  venv-scoped workaround (lost on reinstall/upgrade of `flashinfer`/`vllm`
  in that venv), not a permanent fix; the real fix would be a patched
  upstream `flashinfer` release, not yet identified/pinned -- not
  investigated further since the direct patch is sufficient to unblock
  functional verification.
- The translation GPU host has only one GPU (H100 80GB), and it is the
  *same* GPU already used for ASR (confirmed by `GPU-TRANSLATE-001`), not a
  separate one as `docs/ARCHITECTURE.md` recommends ("do not assume Whisper
  large-v3 and Qwen3.6-27B-FP8 can safely coexist on one 48 GB GPU under
  production load" -- written with a 48 GB GPU in mind; this is 80 GB, with
  meaningful estimated headroom, but real concurrent-load co-location has
  not been verified). Flagged for the user's awareness in
  `USER_RESULTS.md`; not currently blocking, since the model download step
  does not depend on the final co-location decision.
- **Superseded by Phase 08** (kept for history; see "Phase 08 deliverables"
  above for the current state): translation used to have no consumer/
  scheduler at all, and the completeness-check prompt had no classifier
  consuming it. `UtteranceOrchestrator` now calls
  `FinalTranslator.translate_once`/`retry`, schedules the retry in the
  background and publishes `translation.updated`, and
  `CompletenessClassifier` now actually calls vLLM to classify semantic
  completeness for ambiguous soft-silence cases. What remains genuinely
  not-yet-done is captured in the next two bullets.
- `UtteranceOrchestrator` (Phase 08) is implemented and integration-tested
  (`ScriptedAsrModel`/`ScriptedTranslationClient` fakes; no GPU/model
  weights) but, consistent with every prior phase's precedent, is **not
  wired into the live gateway WebSocket ingest path**: nothing currently
  constructs an `UtteranceOrchestrator` from `server/app.py`, feeds it
  released audio frames from `server/transport/gateway.py`, drives
  `run_due_partial_decodes` off a real wall-clock timer, or sends its
  published events back out over a real socket. The gateway still only
  validates, orders and acknowledges audio (Phase 03); VAD, ASR, partial
  transcription and translation all still run only in tests, not in the
  live request path. Wiring this into the gateway is not called for by
  this phase's own required outcomes (which do not mention the gateway or
  WebSocket) and has not been assigned to any later phase's prompt file
  either (Phase 09, now also done, built the client UI around the
  existing transport without touching this gap either; Phases 10-11 cover
  reliability/security/observability and end-to-end tests/packaging) --
  it should be raised with the user explicitly before being started, per
  the standing "do not proceed to another phase without direction"
  instruction.
- The completeness-check JSON schema/prompt (`CompletenessClassifier`) has
  never been sent to the real vLLM server: Phase 07's `GPU-TRANSLATE-007`
  hardware-verified the *translation* prompt path through
  `VllmTranslationClient`, but this phase's *new* completeness prompt
  (`{"complete": bool, "confidence": float}` JSON, via the same client)
  has only been exercised against local fakes. Whether the real
  Qwen3.6-27B-FP8 deployment reliably returns valid, schema-matching JSON
  for this prompt (as opposed to prose, markdown-wrapped JSON, or a
  refusal) is unverified. This is a lightweight, well-scoped follow-up
  manual action (reusing the already-running server from
  `GPU-TRANSLATE-005`, no new download/launch) that can be prepared on
  request; it was not staged automatically since it was not required to
  complete this phase's own local scope.
- Only `StaticTokenAuthenticator` (development) is provided; a production JWT
  authenticator implementing the `Authenticator` interface is future work.
- `WebSocketClientTransport` requires the `websockets` package (client/server
  extras); it is imported lazily and covered by unit tests via a fake transport
  rather than a live socket.
- `client/ui/main_window.py` (Phase 09's real PySide6 window) could not be
  imported, run or type-checked against real Qt in this development
  environment (no PySide6 installed, no Windows audio hardware) before
  `WINDOWS-UI-001`, so it was reviewed only statically. That first real
  run (2026-08-12) confirmed the widget layout, controls, keyboard
  navigation, accessibility font sizing and settings persistence all work
  correctly, but found two real bugs in the Connect/Disconnect flow, not
  caught by any local check because nothing in the CPU suite exercises a
  real `websockets` connection or a real background-thread crash:
  1. **`websockets` import incompatible with the pinned version.**
     `client/transport/sender.py`'s `_websockets_connect` imported
     `websockets.asyncio.client`, a submodule that only exists starting in
     `websockets` 13.0 (its rewritten implementation). This project pins
     `websockets>=12,<13`, and the installed 12.x package has no such
     submodule -- `ModuleNotFoundError` on every connection attempt.
     Fixed by switching to the stable, always-available top-level
     `websockets.connect` entry point (no dependency version bump
     needed). This is a pre-existing Phase 03 bug (`WebSocketClientTransport`
     was written then), invisible until now because every Phase 03 test
     uses a fake `Transport` -- this was the first time the real one ever
     ran.
  2. **Stale state after a background-thread crash.** When bug (1) made
     `AudioSender.run()` raise inside `SessionController`'s background
     thread, the thread died, but `SessionController`/`MainWindow` kept
     treating the session as live: `self._loop` still referenced the now
     -closed event loop, and `MainWindow._session` was never cleared. The
     20ms capture-timer tick then called `send_audio()` ->
     `loop.call_soon_threadsafe(...)` on a closed loop every tick,
     raising `RuntimeError: Event loop is closed` repeatedly (the
     traceback flood the user saw and reasonably described as
     "freezing"); clicking Disconnect or closing the window hit the same
     dead loop via `session.stop()` before reaching the cleanup code, so
     the button/state label never reset either. Fixed:
     `SessionController.is_running` now checks `Thread.is_alive()`
     instead of just "was started"; `stop()`/`send_audio()` no longer
     touch a dead loop; a new `on_fatal_error` callback reports the
     failure exactly once (shown via a message box) while
     `MainWindow._drain_capture` catches the resulting clean
     `RuntimeError` to auto-stop the session cleanly instead of raising
     every tick. This class of bug (a background worker thread dying
     unexpectedly) is a realistic production scenario beyond just this
     specific `websockets` bug -- e.g. DNS failure, connection refused,
     server down -- so this fix has value independent of bug (1).
  4 new regression tests cover the crash-and-recover behavior
  (`tests/test_ui_session_controller.py`); full local suite (342 tests),
  ruff and mypy all re-verified clean after the fix. `WINDOWS-UI-002`
  (2026-08-13) re-verified both fixes on real hardware and PASSED: clean
  connect/disconnect with no server (both device patterns,
  close-while-connected) and a real connected session against a local
  dev server, no exceptions. Both bugs are now `HARDWARE_VERIFIED` fixed.
- `WINDOWS-UI-002`'s connected test also surfaced a new, separate finding
  from the server log: every session hit `idle timeout`
  (`ws_idle_timeout_ms`, 15s of the server receiving nothing at all)
  rather than staying open. Since the client is expected to stream a
  continuous 20ms audio frame once connected (capture does not gate on
  speech -- silence still produces frames), this suggests the capture ->
  enqueue -> send pipeline (`client/ui/main_window.py`'s
  `_start_capture`/`_drain_capture`, wired through
  `client/audio/capture.CaptureContext` and
  `client/audio/windows_backend.PyAudioWPatchBackend`) is not actually
  delivering frames to the server, even though the WebSocket handshake
  itself succeeds (a separate code path from audio delivery). Code review
  did not find an obvious bug in this specific wiring (it closely mirrors
  the already-hardware-verified `client/audio/wav_cli.py` pattern), so
  rather than guess at a fix, temporary, non-sensitive (counts only,
  never audio content) diagnostic logging was added:
  `client/ui/main_window.py` logged a `capture started: source=...` line
  per opened stream and a `capture stats: source=... queue_depth=...
  chunks_enqueued=... chunks_dropped=... overflow_events=...
  frames_produced=... frames_sent_total=...` line every 2 seconds while
  connected (via `CaptureContext`'s existing counters, already exposed
  and unit-tested since Phase 02). `client/ui/main_window.run()` also
  gained a `shared.logging.configure_logging()` call on startup, since
  the client had no logging output configured at all before this (the
  server side already did) -- this part is kept permanently.
- `WINDOWS-UI-003` (2026-08-13) ran with this diagnostic logging active
  and fully resolved the finding above for the **microphone** side: the
  capture/enqueue/send pipeline works correctly end-to-end --
  `chunks_enqueued`/`frames_produced` climbed smoothly and continuously,
  `frames_sent_total` matched exactly, and the server logged a clean
  `client disconnected` with no `idle timeout`. The **loopback** stream
  opened without error but stayed at `chunks_enqueued=0
  frames_produced=0` for the entire test -- i.e. the PyAudio callback for
  that stream never fired with data, even once. Leading hypothesis:
  Windows WASAPI loopback capture only delivers packets while there is an
  active render (playback) session on that output device; if nothing was
  playing sound during the test, the endpoint legitimately produces
  nothing, by platform design, regardless of the capturing code --
  consistent with `WINDOWS-AUDIO-001`'s original prerequisite ("a
  meeting/audio app or media playing during the loopback capture") for
  this *same* `device_index=17`, which did successfully capture real
  audio when that prerequisite was met. No code change was made at that
  point, deliberately -- the hypothesis did not point to a bug, so
  "fixing" something without confirming it was broken would have risked
  masking the real signal.
- `WINDOWS-UI-004` (2026-08-13), re-run with a WAV file of Vietnamese
  speech actively playing, fully confirmed the hypothesis: loopback
  worked correctly both alone (`chunks_enqueued` 93 -> 503,
  `frames_produced` 99 -> 536 over ~10s) and together with microphone
  (both sources' counters climbing independently and correctly in
  parallel; the shared `frames_sent_total` counter correctly reflected
  the combined running total across both sources at each sample). **No
  code bug was ever present** -- the audio capture/enqueue/send pipeline
  is now `HARDWARE_VERIFIED` for both sources, together or independently.
  Since the investigation was now closed, the temporary diagnostic
  instrumentation (`_diagnostics_timer`, the periodic `capture stats`
  log line, the `_frames_sent` counter) was removed from
  `client/ui/main_window.py` as debugging scaffolding that had served its
  purpose and was never part of this phase's required outcomes; the
  one-time `capture started` line and `configure_logging()` call were
  kept.
- **Bug fix: capture-send timer started before the connection was
  established** (found by `WINDOWS-UI-005`, 2026-08-13, fixed same-turn).
  The logging-removal trim itself was confirmed safe (only the expected
  `capture started` lines, no `capture stats` spam, no exceptions), but
  the server log showed two `WARNING ... lost packets (jitter overflow)`
  lines -- never seen in any prior action -- shortly after the connection
  was accepted, on both streams. Root cause: `_start_session` called
  `self._capture_timer.start()` immediately after `session.start()`, but
  `SessionController.start()` only blocks until the background event loop
  *exists* (`ready.wait()`), not until the WebSocket handshake actually
  completes. This let the 20ms capture-drain tick call
  `AudioSender.send_audio()` (queuing packets into both the ack-tracking
  buffer and the outgoing queue) *before* `_open()` had run. Once `_open()`
  did run, its `_resend_pending()` step -- designed for real reconnects,
  where resending already-sent-but-unacked frames is correct -- sent
  those same early packets once, and then the normal outgoing pump sent
  them *again* from the outgoing queue, producing a burst of duplicate/
  early traffic right as the server's bounded (64-slot) jitter reorder
  window was warming up, plausibly tripping its forced-advance/loss
  -reporting path even though nothing was actually lost in transit (this
  is reliable localhost TCP). Fixed: the capture-drain timer no longer
  starts in `_start_session`; it now starts on the first `CONNECTED`
  state change (`_on_state_changed`), so no audio is sent before the
  handshake genuinely completes. Real audio capture (into
  `CaptureContext`'s bounded, drop-oldest queue) is unaffected -- it still
  starts immediately, so at most a short, harmless amount buffers up
  while connecting. Full local suite (342 tests), ruff and mypy
  re-verified clean. `WINDOWS-UI-006` (2026-08-13) confirmed this fix: no
  more `jitter overflow` warning.
- **Bug fix: `_pump_incoming` never noticed `stop` against a real,
  idle transport** (found by `WINDOWS-UI-006`, 2026-08-13, fixed
  same-turn). `WINDOWS-UI-006` also reported: clicking Disconnect took
  ~5 seconds to update the button/state label, and ~10 seconds after
  that the client logged `transport closed; will reconnect` while the
  server logged a *new* session hitting `idle timeout`. Root cause:
  `AudioSender._pump_incoming` awaited `transport.recv()` directly in a
  loop; the real `WebSocketClientTransport.recv()` blocks indefinitely
  until the peer sends something or closes the connection, so with
  nothing incoming it never re-checked `stop`. `MainWindow._stop_session`
  calls `SessionController.stop()` synchronously from the Qt main
  thread, which does `thread.join(timeout=5.0)` -- explaining the ~5s UI
  freeze -- and when the background thread was still stuck in
  `_pump_incoming` after that timeout, `stop()` gave up and returned
  anyway, **silently orphaning the still-running background thread**
  (holding the WebSocket open with nothing being sent). That orphaned
  session then sat idle until the *server's own* `ws_idle_timeout_ms`
  (15s) force-closed it, which is only when `_pump_incoming` finally
  unblocked, discovered `stop` was already set, and exited for real --
  matching the observed ~5s-freeze-then-~10s-more timeline (summing to
  the server's 15s idle timeout). Fixed: `_pump_incoming` now polls
  `transport.recv()` with a short (50ms) timeout instead of awaiting it
  directly, matching `_pump_outgoing`'s existing style, so it notices
  `stop` almost immediately regardless of what the peer does. A new
  regression test
  (`test_run_stops_promptly_even_with_a_permanently_blocked_recv`)
  simulates a transport whose `recv()` never returns on its own and
  asserts `run()` still stops well under one second. Full local suite
  (343 tests), ruff and mypy re-verified clean. `WINDOWS-UI-007`
  (2026-08-13) confirmed this fix: "everything is good. OK. No
  traceback/error or exception" -- Disconnect now updates promptly with
  no delayed reconnect or server-side idle timeout. **This closes out
  Phase 09's manual-verification sequence**; no further Phase 09 manual
  action is currently pending.
- Even a fully-working, connected UI will not display live captions yet:
  VAD/ASR/translation are still not wired into the live gateway ingest
  path (see the `UtteranceOrchestrator` bullet above, unchanged by this
  phase). This is unrelated to any of the bugs above and was never in
  Phase 09's scope.
- The client UI's connect flow always constructs its own
  `StreamConfig`/`SessionStart` with fixed stream ids (`microphone-01`/
  `loopback-01`) and stream numbers (1/2); multi-session or
  multi-window use (more than one meeting at a time from the same
  client) is not supported and was not requested by this phase's
  required outcomes.
- There is no auth-token UI control: `_start_session` always connects
  anonymously (matching the server's development default,
  `StaticTokenAuthenticator` with no `AUTH_DEV_TOKEN` set), with no
  text-entry field for a token. This satisfies "settings persistence
  without secrets" trivially (there is nothing token-related to persist
  or even collect), but a production/token-protected server cannot be
  reached from the UI yet; adding that control is straightforward
  follow-up work, not attempted here since it was not exercised by any of
  this phase's required outcomes.

- Phase 10 (reliability/security/observability) is implemented and
  local-verified but has no hardware-verification component of its own
  (see "Phase 10 verification" above) -- everything is either pure logic
  or a real in-process FastAPI/WebSocket integration test. The gaps that
  matter are documentation/scope gaps, not unverified-against-hardware
  gaps:
  - **`UtteranceOrchestrator` is still not wired into the live gateway**
    (Phase 08's original gap, unchanged by this phase -- see the bullet
    above under Phase 08). This means the new orchestrator-level metrics
    (`translation_requests_total`, `translation_latency_seconds`,
    `asr_latency_seconds`, `translation_queue_depth`,
    `circuit_breaker_state`) and `utterance_id`/`request_id` correlation
    are fully implemented and tested but will not appear on a real running
    deployment's `/metrics` until that wiring happens; only gateway-level
    metrics (`sessions_active`, `packets_*`) and `session_id`/`stream_id`
    correlation are live today.
  - `docs/DEPLOYMENT.md`'s nginx/Caddy examples are documentation, not
    verified against a real reverse proxy, real TLS certificate or real
    WebSocket traffic through either.
  - `JwtAuthenticator` is fully tested against real, locally-generated RSA
    keypairs (signature/issuer/audience/expiry/leeway/`alg:none`/HS*
    -rejection all covered), but has never been exercised against a real
    external identity provider or JWKS endpoint -- only against a static
    PEM public key file, which is the only mode this phase's outcomes
    called for (`JWT_PUBLIC_KEY_PATH`, a single static key, not a JWKS
    rotation scheme).
  - `CompletenessClassifier` deliberately has no circuit breaker (see
    "Phase 10 deliverables" for the reasoning); if a later phase changes
    how completeness checking is scheduled, revisit whether that decision
    still holds.

- Phase 11 (end-to-end tests and packaging) is implemented and
  local-verified, with three genuine local hardware-adjacent verifications
  actually performed this session (real PyInstaller build,
  `load_test.py` against a real local server, `latency_report.py`'s
  numbers spot-checked) -- see "Phase 11 verification" and "Phase 11
  deliverables" above for detail. What remains:
  - **"The one gap that matters most" is unchanged by this phase**:
    `UtteranceOrchestrator` is still not wired into the live gateway. See
    `docs/FINAL_IMPLEMENTATION_REPORT.md`'s opening section -- this is the
    single most important thing to read before assuming this project is
    ready for a real meeting.
  - The `translation_queue_depth` Gauge cross-session-sharing limitation
    (found by this phase's own load test) is newly documented, not fixed
    -- see "Phase 11 deliverables"'s last bullet.
  - All three genuinely hardware-dependent verifications staged in
    `MANUAL_ACTIONS.md` have now PASSED. `WINDOWS-PACKAGE-001` (launch
    the packaged `.exe` on real Windows hardware) PASSED 2026-08-14.
    `GPU-E2E-001`'s first run (2026-08-14) surfaced a real translation
    failure (`translation_status: FAILED`) against the real vLLM server,
    root-caused by `GPU-E2E-002` to the vLLM server simply not running,
    then further traced by the user to `models/` (the `Qwen3.6-27B-FP8`
    weights) and `.venv-translate` both having been accidentally deleted
    from the GPU host. `GPU-TRANSLATE-008` redid that setup from scratch
    (including hitting and fixing a bug in Claude's own first
    `flashinfer`-patch script, which self-defeatingly tried to *import*
    the broken module to locate it) and was independently verified
    working (`/health` 200, `/v1/models` matching `GPU-TRANSLATE-006`
    exactly, `nvidia-smi` showing no OOM). `GPU-E2E-003` then re-ran the
    full pipeline and PASSED meaningfully: `translation_status: COMPLETED`
    with a real, correct Vietnamese translation
    (`'Cảm ơn quý vị đã theo dõi.'`) -- **the first real, hardware-confirmed
    proof that real ASR and real translation work together end-to-end on
    real GPU hardware.** `LATENCY-001` then ran and produced this
    project's **first-ever real hardware latency numbers**
    (`scripts/latency_report.py --count 20 --real-backends`): first
    partial p95 934.3ms (< 1.8s objective, PASSES), final ASR p95 94.2ms
    (< 1.2s, PASSES comfortably), end-to-end final p95 2484.0ms (< 3.5s,
    PASSES, though p99 4593.1ms exceeds it), and **translation p95
    2392.1ms -- FAILS the documented < 1.2s objective by roughly 2x**.
    This is a real, new, unresolved finding: plausibly explained by
    `--enforce-eager` (required to work around the `flashinfer` bug)
    disabling `torch.compile`/CUDA graph capture, but not root-caused with
    certainty (no A/B measurement against a non-eager launch exists), and
    measured against a single short synthetic utterance rather than a
    realistic distribution of meeting utterances or concurrent load. Full
    detail in `USER_RESULTS.md`'s `LATENCY-001` entry and
    `MANUAL_ACTIONS.md`'s completed-actions section. No manual action is
    currently `WAITING_FOR_USER`.
  - UI acceptance criteria about partial/final/translation *rendering*
    (gray hint, bold final, normal-weight translation, retry/failure
    visibility) remain LOCAL_VERIFIED only, not screen-verified with real
    data -- a direct consequence of the gateway-wiring gap above (no real
    session has ever produced real events for `WINDOWS-UI-*` to render).
    See `docs/FINAL_IMPLEMENTATION_REPORT.md`'s "UI" table.
  - `SileroVadModel` (the real, non-scripted VAD adapter) remains
    excluded from the CPU suite and has no staged hardware check of its
    own -- unchanged since Phase 04; segmentation *logic* is fully
    verified with scripted probabilities.

## Next action

**Phase 11 (end-to-end tests and Windows packaging) is complete:
LOCAL_VERIFIED**, per `prompts/phases/11_E2E_PACKAGING.md`'s required
outcomes (end-to-end mocked test proving audio packet -> VAD -> partial ->
final ASR -> translation -> final UI state; optional GPU end-to-end test
command; a load-test scenario for concurrent meetings/queue spikes/
synchronized finalization; latency measurement tooling reporting real
p50/p95/p99 without hard-coded success; Windows client packaging with
PyAudioWPatch/PySide6 handling verified; version metadata and upgrade
strategy; a production-like Docker Compose example with monitoring; an
administrative runbook; a final README with all three quick starts; a
complete acceptance-criteria review). All local checks pass (421 passed, 0
failed, 3 deselected; ruff format --check/ruff check and mypy clean).

**This is the last phase-by-phase prompt in `prompts/phases/`** -- but
completing it is not the same as this project being ready for a real
meeting. Read `docs/FINAL_IMPLEMENTATION_REPORT.md`'s opening section
first: `UtteranceOrchestrator` is still not wired into the live gateway,
so a real client connected to a real running server today will not
produce live captions. Every individual piece is real and tested,
including new whole-chain compositions this phase (mocked and, optionally,
real-GPU), but they are not yet connected to each other over the live
network path. Closing that gap is the natural next phase of work and
should be raised explicitly with the user before starting, not assumed --
consistent with the standing "do not proceed to another phase without
direction" instruction, which applies here as much as ever precisely
*because* this was the last titled phase.

**All three of Phase 11's staged hardware-dependent manual actions have
now PASSED**, closing out that staging entirely:

- `WINDOWS-PACKAGE-001` (2026-08-14): the packaged Windows client `.exe`
  launches, shows real device dropdowns, and Connect/Disconnect works
  cleanly against a local dev server -- a UI/connectivity check, not
  evidence of live captions.
- `GPU-E2E-001` (2026-08-14) initially surfaced a real translation
  failure against the real vLLM server. `GPU-E2E-002` root-caused it to
  the vLLM server simply not running; the user then found the deeper
  cause -- `models/` (the `Qwen3.6-27B-FP8` weights) and `.venv-translate`
  had both been accidentally deleted from the GPU host. `GPU-TRANSLATE-008`
  rebuilt everything from scratch (also catching and fixing a bug in
  Claude's own first flashinfer-patch script, which self-defeatingly
  tried to *import* the broken module to locate it) and was independently
  verified (`/health` 200, `/v1/models` matching `GPU-TRANSLATE-006`
  exactly, no OOM per `nvidia-smi`). `GPU-E2E-003` then re-ran the full
  pipeline and PASSED meaningfully: `translation_status: COMPLETED` with
  a correct real translation -- **the first real, hardware-confirmed
  proof that ASR and translation work together end-to-end on real GPU
  hardware.**
- `LATENCY-001` (2026-08-15) then produced this project's **first-ever
  real hardware latency numbers**. Three of four measured objectives
  pass; **translation p95 (2392.1ms) fails the documented <1.2s
  objective by roughly 2x**, plausibly due to `--enforce-eager` (the
  flashinfer workaround) disabling `torch.compile`/CUDA graphs, though
  not root-caused with certainty. See `USER_RESULTS.md`'s `LATENCY-001`
  entry for the full breakdown.

Full detail for all of the above is in `MANUAL_ACTIONS.md`'s
completed-actions section and `USER_RESULTS.md`. **No manual action is
currently `WAITING_FOR_USER`.**

This closes out everything Phase 11 originally staged. What's left is
unchanged from before and remains the natural next topic to raise with
the user, not to start unprompted: **"the one gap that matters most"** --
`UtteranceOrchestrator` is still not wired into the live gateway, so a
real client connected to a real running server today will not produce
live captions, despite every individual piece (including the newly
end-to-end-confirmed real ASR+translation chain) now being real and
tested. A secondary, lower-priority open item is the measured translation
p95 latency miss above, which may be worth investigating (e.g., whether
an upstream `flashinfer` fix exists that would allow removing
`--enforce-eager`) before any latency-sensitive production commitment.
Do not begin either without the user's explicit direction, per the
standing "do not proceed without direction" instruction. Take a local
snapshot first (`python scripts/local_backup.py --label <name>`) -- as
the very first action, before any reading/research -- before starting
whichever the user chooses next.

---

**Phase 10 (reliability, security and observability) is complete:
LOCAL_VERIFIED**, per
`prompts/phases/10_RELIABILITY_SECURITY_OBSERVABILITY.md`'s required
outcomes (JWT verification interface and production configuration; TLS
deployment guidance and reverse-proxy example; request/packet/session/
queue limits; redaction tests proving no raw audio/transcript/prompt/
translation is logged by default; Prometheus metrics per the product
documents; structured correlation ids across session/stream/utterance/
model request; readiness reflecting dependency health without leaking
sensitive detail; graceful shutdown flush policy; translation/ASR circuit
-breaker/backoff behavior; model overload/queue-pressure behavior; server
restart and client reconnect tests; a security review checklist and
dependency-pinning strategy). All local checks pass (416 passed, 0 failed,
2 deselected; ruff format --check/ruff check and mypy clean). No
`MANUAL_ACTIONS.md` entry was needed this phase -- everything built is
pure/local or a real in-process integration test; no manual action is
currently `WAITING_FOR_USER`.

Per the original instruction for this phase ("Do not proceed to another
phase"), Claude is stopping here. Do not begin Phase 11, the
`UtteranceOrchestrator`-to-gateway wiring gap, or any other follow-up work
without the user's explicit direction. Take a local snapshot first
(`python scripts/local_backup.py --label <name>`) -- as the very first
action, before any reading/research -- before starting whichever the user
chooses next.

No manual action is currently WAITING_FOR_USER.

---

**Phase 09 (PySide6 client UI) is complete: LOCAL_VERIFIED and
HARDWARE_VERIFIED**, per `prompts/phases/09_PYSIDE_UI.md`'s required
outcomes (main window with connect/disconnect state; device selectors;
language presets; independent source enable/disable; a caption timeline
with the exact revision-idempotency/final-replaces-partial rules
`docs/PROTOCOL.md` requires; a gray partial hint with stable/unstable
text visually distinguished; a bold final transcription; a normal-weight
translation line; visible source/direction/timestamp/retry/failure state;
a thread-safe worker-to-Qt bridge; settings persistence provably without
secrets; accessibility font sizing and keyboard tab order; view-model/
settings/session-controller tests independent of Qt rendering). All local
checks pass (343 passed, 0 failed, 2 deselected; ruff format/check and
mypy clean).

The seven-action manual-verification sequence (`WINDOWS-UI-001` through
`WINDOWS-UI-007`, 2026-08-12 to 2026-08-13) is fully closed out: it found
and fixed four real bugs (a `websockets` import incompatible with the
pinned dependency range; a background-thread-crash cleanup gap; a
capture-send timer starting before the handshake completed, causing
spurious `jitter overflow` warnings; and `_pump_incoming` never noticing
`stop` against a real transport, causing a Disconnect-time UI freeze and
an orphaned background thread), each with new regression tests, and
separately confirmed the audio capture/enqueue/send pipeline works
correctly for both microphone and loopback. `WINDOWS-UI-007`'s clean
PASS ("everything is good. OK.") confirms the last fix and closes the
sequence. See "Known limitations" for full root-cause detail on each.

Two gaps remain flagged in "Known limitations" for awareness, not
blocking this phase's completion and unrelated to anything above: (1)
even with a fully working audio pipeline, no live captions will appear
yet, since `UtteranceOrchestrator` is still not wired into the live
gateway ingest path (Phase 08's gap, never in Phase 09's scope); (2) the
completeness-check JSON prompt has never been hardware-verified against
real vLLM (Phase 08's other flagged gap).

Per the original instruction for this phase ("Do not proceed to another
phase"), Claude is stopping here. No manual action is currently pending.
Do not begin Phase 10 (or any other phase), gateway-wiring work, or the
optional completeness-JSON hardware verification without the user's
explicit direction. Take a local snapshot first
(`python scripts/local_backup.py --label <name>`) -- as the very first
action, before any reading/research -- before starting whichever the user
chooses next.

No manual action is currently WAITING_FOR_USER.
