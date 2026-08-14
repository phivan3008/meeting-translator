# Final Implementation Report (Phase 11)

A point-in-time, line-by-line walkthrough of `docs/ACCEPTANCE_CRITERIA.md`,
separating what is genuinely verified from what is local-only or still
hardware-pending, per this phase's own required outcome ("a final
implementation report that separates verified results from manual or
hardware-dependent verification still required"). `IMPLEMENTATION_STATUS.md`
remains the authoritative, continuously-updated record; this document is a
snapshot as of Phase 11's completion, cross-referenced against it.

## The one gap that matters most

**`UtteranceOrchestrator` (VAD -> partial ASR -> final ASR -> translation)
is not wired into the live `server/transport/gateway.py` WebSocket ingest
path.** This has been true and explicitly flagged since Phase 08 and
remains true after Phase 11 -- it was never assigned to any phase's
required outcomes. The practical consequence: **a real client connected to
a real running server today will not see live captions.** Every piece the
pipeline is built from is real, tested, and (for the GPU-hosted pieces)
separately hardware-verified in isolation -- transport, VAD, ASR,
translation, the orchestrator, the UI -- but they are not yet connected to
each other over a live network path. `tests/test_e2e_mocked_pipeline.py`
(Phase 11) proves the full logical chain works when composed directly, and
`tests/test_e2e_gpu.py` (Phase 11, `gpu`-marked) proves it against real
GPU backends the same way -- but neither goes through the WebSocket
gateway, because the gateway does not yet drive the orchestrator. Closing
this gap is the natural next phase of work and should be discussed
explicitly with whoever directs the next phase, not assumed.

## Status legend

- **VERIFIED**: proven by an automated, currently-passing local test (CPU,
  no GPU/Windows hardware required).
- **LOCAL_VERIFIED**: implemented and reviewed/tested at the code level,
  but the specific claim (often a visual/UX property) has not been
  confirmed against real hardware/rendering.
- **HARDWARE_VERIFIED**: confirmed by real user-provided output from real
  hardware (`USER_RESULTS.md`), not inferred or assumed from a mock.
- **HARDWARE_PENDING**: implemented and local-verified, but the specific
  hardware confirmation has not happened yet.

## Repository and quality

| Criterion | Status | Evidence |
|---|---|---|
| Project installs from documented commands. | VERIFIED | `README.md`'s quick starts; `pip install -e ".[dev]"` has been the working baseline since Phase 00. |
| Formatting, linting, type checks and CPU test suite pass. | VERIFIED | `ruff format --check .` / `ruff check .` / `mypy client server shared` / `pytest -m "not gpu and not windows_audio"` all clean -- see this file's own "Final local check results" below. |
| GPU and Windows-only tests are separately marked. | VERIFIED | `pyproject.toml`'s `gpu`/`windows_audio` markers; `tests/test_e2e_gpu.py`, `tests/test_windows_audio.py`. |
| No model is downloaded implicitly during unit tests. | VERIFIED | `WhisperAsrModel`/`VllmTranslationClient`'s real backends are imported lazily and excluded from the default marker selection; `ScriptedAsrModel`/`ScriptedTranslationClient` are used everywhere else. |
| No production path contains placeholder behavior. | VERIFIED, with one honestly-flagged exception | No `pass`-stub or fake result exists on any code path that *is* wired up. The one exception is structural, not a placeholder: the gateway-to-orchestrator wiring described above does not exist yet at all (nothing pretends to be it). |

## Client audio

| Criterion | Status | Evidence |
|---|---|---|
| Microphone and WASAPI loopback are selectable independently. | HARDWARE_VERIFIED | `WINDOWS-UI-003`/`WINDOWS-UI-004` (`USER_RESULTS.md`). |
| Both can be captured concurrently without mixing. | HARDWARE_VERIFIED | `WINDOWS-UI-004`: both sources' counters climbed independently and correctly in parallel. |
| Captured server-side fixtures decode as mono 16 kHz PCM S16LE. | VERIFIED + HARDWARE_VERIFIED | `tests/test_audio_*` (format constants/conversion) plus `WINDOWS-AUDIO-001`'s real capture. |
| Audio callback does not execute network or resampling work. | VERIFIED | `client/audio/windows_backend.py`'s callback only timestamps and forwards raw bytes; `client/audio/capture.py`'s `CaptureContext` does all conversion/enqueue work outside the callback -- structural property confirmed by code review and `tests/test_audio_capture.py`. |
| Queue overflow behavior is bounded, measured and tested. | VERIFIED | `client/audio/queue.py`'s `DropPolicy`, `tests/test_audio_queue.py`. |

## Protocol

| Criterion | Status | Evidence |
|---|---|---|
| Binary packet round-trip tests pass. | VERIFIED | `tests/test_protocol_binary.py`; re-exercised through real encode/decode in `tests/test_e2e_mocked_pipeline.py`. |
| Truncated, oversized and length-mismatched packets are rejected. | VERIFIED | `tests/test_protocol_binary.py`, `tests/test_transport_gateway.py::test_payload_too_large_is_rejected`/`test_malformed_packet_is_rejected`. |
| Duplicate revisions and packets are idempotently ignored. | VERIFIED | `tests/test_transport_jitter_buffer.py` (packet level), `tests/test_ui_view_model.py`/`CaptionTimeline` (revision level). |
| JSON events validate against versioned Pydantic schemas. | VERIFIED | `shared/protocol/messages.py`'s `ProtocolModel(extra="forbid")`; every message type has direct test coverage. |

## VAD and utterance

| Criterion | Status | Evidence |
|---|---|---|
| Per-stream state is independent. | VERIFIED | `tests/test_orchestration_pipeline.py::test_concurrent_streams_finalize_independently`; `tests/test_load_concurrent_meetings.py` (Phase 11) extends this across concurrent *sessions*. |
| Pre-roll and post-roll behavior is covered by tests. | VERIFIED | `tests/test_vad_state_machine.py`, `tests/test_vad_ring_buffer.py`. |
| Soft silence may trigger a completeness decision. | VERIFIED | `tests/test_orchestration_pipeline.py`'s soft-silence race-safety tests. |
| Hard silence forces finalization. | VERIFIED | `tests/test_vad_state_machine.py`; exercised end-to-end in `tests/test_e2e_mocked_pipeline.py`. |
| Maximum utterance duration forces a safe boundary. | VERIFIED | `tests/test_vad_state_machine.py` (`max_utterance_ms`). |
| Real Silero VAD (as opposed to the scripted fake). | HARDWARE_PENDING | `SileroVadModel` is implemented but excluded from the CPU suite (needs `torch`/`silero_vad`); no GPU/CPU-inference hardware check has been staged for it specifically -- segmentation *logic* is fully verified with scripted probabilities, real Silero accuracy is not. |

## ASR

| Criterion | Status | Evidence |
|---|---|---|
| Source language is passed from stream configuration. | VERIFIED | `tests/test_asr_worker.py`, `tests/test_e2e_mocked_pipeline.py`. |
| Partial revisions strictly increase. | VERIFIED | `tests/test_asr_partial.py`. |
| Stable-prefix logic does not duplicate committed text. | VERIFIED | `tests/test_asr_stable_prefix.py`. |
| Final ASR is run against the completed utterance. | VERIFIED | `tests/test_asr_worker.py`, `tests/test_e2e_mocked_pipeline.py`. |
| Test doubles allow CPU CI without model weights. | VERIFIED | `ScriptedAsrModel` used throughout; confirmed no implicit download (see "Repository and quality" above). |
| Real `WhisperAsrModel` (faster-whisper large-v3) decode. | HARDWARE_VERIFIED (adapter only, not integrated) | `GPU-ASR-004` (real model load/decode, no CUDA/cuDNN/cuBLAS error), `GPU-ASR-005` (real vi/ja speech, user-confirmed roughly accurate). **Not** hardware-verified integrated into a live gateway-driven session -- see "The one gap that matters most." |

## Translation

| Criterion | Status | Evidence |
|---|---|---|
| Requests target `qwen3.6-27b-translate` through an OpenAI-compatible client. | VERIFIED + HARDWARE_VERIFIED | `tests/test_translation_client.py` (mock transport); `GPU-TRANSLATE-006` confirmed the real served model id matches. |
| Thinking is disabled. | VERIFIED | `tests/test_translation_client.py` asserts `chat_template_kwargs: {"enable_thinking": false}` is sent. |
| Only finalized transcription enters translation. | VERIFIED | `server/orchestration/pipeline.py` only calls `FinalTranslator` from `_finalize_utterance`, never from the partial-decode path; `tests/test_orchestration_pipeline.py`. |
| Japanese-to-Vietnamese and Vietnamese-to-Japanese prompt paths are tested. | VERIFIED + HARDWARE_VERIFIED | `tests/test_translation_prompts.py` (both directions, unit); `GPU-TRANSLATE-007` (both directions, real vLLM, plausible correctly-scripted output). |
| Validation detects number or identifier corruption. | VERIFIED | `tests/test_translation_validator.py`. |
| Translation failure still publishes final transcription. | VERIFIED | `tests/test_orchestration_pipeline.py::test_translation_retry_publishes_translation_updated`; re-proven through the full encode/VAD/ASR/UI chain by `tests/test_e2e_mocked_pipeline.py::test_translation_failure_still_publishes_final_transcription_to_ui` (Phase 11). |

## UI

All of the following are implemented in `client/ui/view_model.py`
(Qt-free, fully unit-tested) and rendered by `client/ui/main_window.py`
(real PySide6, excluded from the CPU suite by design). Because the
gateway-orchestrator wiring gap above means no real session has ever
produced real `transcription.partial`/`utterance.final` events during
`WINDOWS-UI-*` manual testing, **the visual rendering of live captions has
never been eyeballed on a real screen with real data** -- only the
connect/disconnect lifecycle, device/settings controls and static layout
were hardware-verified (`WINDOWS-UI-001`). The caption-state *logic* is
fully verified; its real-Qt *rendering* is not.

| Criterion | Status | Evidence |
|---|---|---|
| Partial text is shown as a gray hint. | LOCAL_VERIFIED | `CaptionEntry.display_text`/`main_window.py`'s rich-text styling reviewed; never rendered on a real screen with real data. |
| Stable and unstable parts are visually distinguishable. | LOCAL_VERIFIED | Same as above (darker stable text, italicized lighter unstable tail). |
| Newer revision replaces older partial in place. | VERIFIED | `tests/test_ui_view_model.py`'s `CaptionTimeline` idempotency tests; re-proven via `tests/test_e2e_mocked_pipeline.py`. |
| Final transcription is bold and replaces partial. | VERIFIED (state) / LOCAL_VERIFIED (visual) | State transition verified by tests; bold rendering not screen-verified. |
| Translation appears below in normal weight. | LOCAL_VERIFIED | Rendering code reviewed; not screen-verified. |
| Retry and failure states are visible. | LOCAL_VERIFIED | `CaptionEntry.retryable`/`error_message` verified by tests; the color/text rendering itself not screen-verified. |

## Integration

| Criterion | Status | Evidence |
|---|---|---|
| An in-memory or mocked flow demonstrates audio packets -> VAD -> partial -> final ASR -> translation -> final event. | VERIFIED | `tests/test_e2e_mocked_pipeline.py` (Phase 11) -- real packet encode/decode through a real `UtteranceOrchestrator` with scripted backends, through to real `ClientViewModel` UI state. |
| WebSocket reconnect does not duplicate final utterances. | VERIFIED | `tests/test_transport_sender.py::test_run_reconnect_after_server_restart_resends_only_unacked_frames`, `tests/test_transport_gateway.py::test_reconnect_after_connection_drop_gets_a_clean_session` (both Phase 10/11). |
| Metrics expose stage latency and queue depth. | VERIFIED, with one documented caveat | `/metrics` exposes real histograms/gauges/counters (Phase 10); Phase 11's load test (`tests/test_load_concurrent_meetings.py`) found that `translation_queue_depth` (a `Gauge`) does not aggregate correctly across multiple concurrent sessions sharing one process-wide `Metrics` instance -- documented in `docs/OPERATOR_RUNBOOK_SEED.md`'s "Metrics and alert interpretation" as informational-only until revisited. `translation_requests_total` (a `Counter`) does not have this problem. |
| Sensitive content is not present in default production logs. | VERIFIED | `tests/test_logging_redaction.py` (filter-level) and `tests/test_logging_no_content_leak.py` (Phase 10, end-to-end through real `FinalTranscriber`/`FinalTranslator`/`UtteranceOrchestrator`, with a negative control proving the test would catch a real leak). |

## What Phase 11 added on top of this

- `tests/test_e2e_mocked_pipeline.py`, `tests/test_e2e_gpu.py` (optional,
  `gpu`-marked), `tests/test_load_concurrent_meetings.py`.
- `scripts/latency_report.py` (real measured p50/p95/p99, fake backends by
  default, `--real-backends` for genuine GPU numbers) and
  `scripts/load_test.py` (real concurrent-session load against a real
  running server's transport layer) -- both actually run and verified
  working during this phase (see `IMPLEMENTATION_STATUS.md`'s "Phase 11
  deliverables" for the real output captured).
- `scripts/build_windows_client.py` + `packaging/entrypoint.py`
  (PyInstaller packaging) -- a real build was performed and verified to
  succeed during this phase (see "Phase 11 deliverables"); the produced
  `.exe` was not run against real hardware (that remains a staged manual
  action).
- `shared/version.py` (single version source, `0.1.0`), synced with
  `pyproject.toml` and enforced by `tests/test_version.py`; `docs/DEPLOYMENT.md`'s
  "Version metadata and upgrade strategy".
- `deployment/docker-compose.prod.yml` + `deployment/monitoring/` (real,
  YAML-validated Prometheus/Grafana example stack).
- `docs/OPERATOR_RUNBOOK_SEED.md` expanded with every section its own
  "Required runbook sections" list named.
- This report and the rewritten `README.md`.

## Final local check results

See `IMPLEMENTATION_STATUS.md`'s "Local test results" for the exact,
current pass/fail counts (`ruff format --check`, `ruff check`,
`mypy client server shared`, `pytest -m "not gpu and not windows_audio"`)
-- reproduced here would only go stale faster than the primary record.
