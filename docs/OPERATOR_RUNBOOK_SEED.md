# Operator Runbook

## Expected deployment

- Application server and Redis run as containers.
- faster-whisper runs on an assigned ASR GPU.
- vLLM runs `Qwen3.6-27B-FP8` on a separate translation GPU.
- A reverse proxy terminates TLS and forwards WebSocket traffic.

## Contents

- Prerequisites and GPU compatibility.
- Model download and checksum/version recording (vLLM and faster-whisper).
- vLLM launch and health verification.
- Application start and readiness verification.
- Windows client installation.
- Metrics and alert interpretation.
- Queue pressure response.
- Whisper or vLLM OOM response.
- Client reconnect and device-change troubleshooting.
- Safe shutdown.
- Privacy-preserving diagnostics.
- Backup and restore for non-content configuration only.

## vLLM (Qwen3.6-27B-FP8) model download and launch

Written from `docs/ARCHITECTURE.md`'s "Translation server baseline" and
`docs/TRANSLATION.md`. This is documentation only -- these steps are run
manually by the operator on the translation GPU host, per
`GPU_MANUAL_WORKFLOW.md`; Claude never runs them. The application server's
own container (`deployment/Dockerfile`) does not build or run vLLM (GPU
inference stays off that image, per its header comment); vLLM runs as its
own container (or bare process) on the separate translation GPU host.

### Model download and version recording

1. Download `Qwen3.6-27B-FP8` (FP8-quantized weights) to a local path on the
   translation GPU host, e.g. `/models/Qwen3.6-27B-FP8`, using whatever
   internal mirror/registry policy applies -- no download command is
   prescribed here, since that depends on where the weights are hosted for
   this deployment.
2. Record the exact revision/commit hash and total on-disk size of the
   downloaded weights (mirrors how `GPU-ASR-004`/`USER_RESULTS.md` recorded
   the faster-whisper `large-v3` revision and size for the ASR model). Keep
   this alongside deployment records, not in source control.
3. Confirm available disk and VRAM are sufficient for an FP8 27B model
   (tens of GB on disk; see `docs/ARCHITECTURE.md`'s GPU allocation
   guidance -- do not assume it safely coexists with Whisper `large-v3` on
   one 48 GB GPU under production load).

### vLLM launch (Docker)

Official vLLM OpenAI-compatible server image, run on the translation GPU
host (adjust the image tag/model path/GPU device to the actual
deployment):

```bash
docker run --rm -d \
  --name vllm-translate \
  --gpus '"device=0"' \
  -v /models/Qwen3.6-27B-FP8:/models/Qwen3.6-27B-FP8:ro \
  -p 8000:8000 \
  vllm/vllm-openai:latest \
  --model /models/Qwen3.6-27B-FP8 \
  --served-model-name qwen3.6-27b-translate \
  --host 0.0.0.0 \
  --port 8000 \
  --language-model-only \
  --max-model-len 4096 \
  --max-num-seqs 32 \
  --max-num-batched-tokens 4096 \
  --gpu-memory-utilization 0.88 \
  --enable-prefix-caching \
  --trust-remote-code \
  --default-chat-template-kwargs '{"enable_thinking": false}'
```

Equivalent bare-process launch (no Docker) is the `vllm serve ...` command
already documented in `docs/ARCHITECTURE.md`'s "Translation server
baseline" -- both forms serve the same OpenAI-compatible API that
`server/translation/client.py` (`VllmTranslationClient`) talks to.

MTP speculative decoding is an optional benchmark feature, not a mandatory
default (`docs/ARCHITECTURE.md`).

### Health verification

```bash
curl -s http://<translation-gpu-host>:8000/v1/models
```

Expected: a JSON body listing `qwen3.6-27b-translate` as an available
model, with no error. `GPU-TRANSLATE-006`/`GPU-TRANSLATE-007`
(`USER_RESULTS.md`) already confirmed this exact check, plus a real
two-direction translation request through this project's own
prompt-building code, against this launch configuration -- re-run it after
any vLLM restart or config change as a quick smoke test.

### Application-side configuration

The application server reaches vLLM via `VLLM_BASE_URL` (`.env.example`,
default `http://localhost:8000/v1`) and `VLLM_MODEL`
(`qwen3.6-27b-translate`) -- point `VLLM_BASE_URL` at the translation GPU
host's address once vLLM is confirmed healthy.

## faster-whisper (ASR) model download and verification

Same manual-workflow constraints as vLLM above: run on the ASR GPU host,
never by Claude, per `GPU_MANUAL_WORKFLOW.md`.

1. Download the `large-v3` weights to the ASR GPU host (`WHISPER_MODEL` in
   `.env.example`; matches `GPU-ASR-004`'s confirmed revision
   `edaa852ec7e145841d8ffdb056a99866b5f0a478`, ~2.88 GiB). Record the
   revision and size alongside deployment records (not source control),
   same as the vLLM step above.
2. Confirm `ctranslate2` can enumerate the GPU
   (`ctranslate2.get_cuda_device_count() >= 1`) before assuming a model
   load will succeed -- `GPU-ASR-003` found this passes even when
   `libcudnn` doesn't appear in a plain `ldconfig -p` grep (bundled
   differently, or resolved at model-load time instead); only a real
   `model.transcribe()` call (`GPU-ASR-004`) definitively confirms
   decoding works.
3. `WHISPER_DEVICE=cuda`/`WHISPER_COMPUTE_TYPE=float16` are the baseline
   (`docs/ARCHITECTURE.md`); `server/asr/whisper.py`'s `WhisperAsrModel`
   loads the model lazily on first use, so a configuration error surfaces
   on the first real request, not at process startup -- run a manual smoke
   decode after any redeploy, not just a liveness check.

## Prerequisites and GPU compatibility

- Both GPU hosts (ASR and translation) need: an NVIDIA GPU with a CUDA
  driver compatible with the pinned `ctranslate2`/vLLM builds (`nvidia-smi`
  driver version, `nvcc --version`), Python 3.11+, and enough disk for the
  model weights (`large-v3` ~3 GB, `Qwen3.6-27B-FP8` ~30 GB) plus KV cache
  headroom.
- **Do not assume `large-v3` and `Qwen3.6-27B-FP8` safely coexist on one
  GPU under production load** (`docs/ARCHITECTURE.md`'s GPU allocation
  guidance recommends separate GPUs). This project's own reference
  deployment ended up co-located on a single 80 GB H100 (`GPU-TRANSLATE-001`,
  `USER_RESULTS.md`) after the originally-planned second GPU wasn't
  available; that specific case had comfortable headroom (weights + KV
  cache measured at ~72/81 GB used, no OOM observed in `GPU-TRANSLATE-005`),
  but this is capacity planning, not a verified-safe-under-concurrent-load
  guarantee -- re-check actual combined VRAM usage under real concurrent
  ASR+translation load before treating co-location as settled for a
  different GPU/model combination.
- The application server container itself (`deployment/Dockerfile`) is
  CPU-only -- it never builds or runs GPU inference; confirm this before
  assuming the app container needs GPU scheduling in your orchestrator.
- A known third-party issue: `vllm==0.27.1`'s `flashinfer` dependency has a
  real bug (`array.array[int]` used as a type annotation, which raises
  `TypeError` at import time on every code path that imports
  `flashinfer.comm`, even for models/features that don't need it -- see
  `GPU-TRANSLATE-003`/`GPU-TRANSLATE-004`/`GPU-TRANSLATE-005` in
  `USER_RESULTS.md` for the full root cause). The workaround applied there
  (patching the one invalid line directly in the installed package) is
  venv-scoped and does not survive a `flashinfer`/`vllm` reinstall --
  re-check whether a fixed upstream `flashinfer` release is available
  before every fresh vLLM environment setup, rather than re-discovering
  this same bug.

## Application start and readiness verification

- Local/dev: `uvicorn server.app:app --host 0.0.0.0 --port 8080` (or
  `docker compose -f deployment/docker-compose.yml up`).
- Production-like: `docker compose -f deployment/docker-compose.prod.yml up -d`
  (application server + Redis + Prometheus + Grafana; see
  `docs/DEPLOYMENT.md`).
- **Liveness**: `GET /health/live` -- process is up. Returns
  `{"status": "alive", "app_env": ...}` unconditionally once the process
  is running; does not imply the server is ready for real traffic.
- **Readiness**: `GET /health/ready` -- reflects settings having loaded,
  whether graceful shutdown has begun, and (only if
  `READINESS_CHECK_TRANSLATION_BACKEND=true`) a bounded reachability probe
  against the translation backend. Returns HTTP 503 with
  `{"status": "not_ready", "checks": {...}}` (booleans only, never raw
  error/hostname detail -- `docs/SECURITY.md`) when any check fails. Point
  your orchestrator's readiness probe here, not at `/health/live`.
- **Before declaring the server "up" in production**: confirm
  `JWT_PUBLIC_KEY_PATH` is actually set (`docs/SECURITY.md`'s checklist --
  `APP_ENV=production` alone does not enable JWT auth), and that
  `/metrics` returns real Prometheus text output
  (`curl http://localhost:8080/metrics`).

## Windows client installation

See `docs/DEPLOYMENT.md`'s "Windows client packaging" for how the
distributable is built (`scripts/build_windows_client.py`,
PyInstaller). To install on an end user's machine:

1. Copy `dist/MeetingTranslator-<version>/` (or the single `--onefile`
   `.exe`) to the target Windows machine. No installer/MSI is provided --
   this is a copy-and-run distribution.
2. First launch creates the settings file at
   `%APPDATA%\MeetingTranslator\client_settings.json`
   (`client/ui/settings_store.py`) -- device selection, per-source enabled
   flags and language preset only, provably no token/secret field (see its
   own test coverage).
3. Point the client at the real server: either edit `CLIENT_SERVER_URL`
   via the environment the client reads settings from, or -- since there
   is no in-UI server-URL/token field yet (a documented Phase 09 gap, see
   `IMPLEMENTATION_STATUS.md`'s "Known limitations") -- set
   `CLIENT_SERVER_URL` before launch. A `wss://` URL is required whenever
   a reverse proxy/TLS is in front of the server (`docs/DEPLOYMENT.md`).
4. Grant microphone/loopback capture permission if Windows prompts for it
   (PyAudioWPatch/WASAPI); no special install-time driver step is needed
   beyond what's already bundled by PyInstaller's PySide6/PyAudioWPatch
   hooks.

## Metrics and alert interpretation

All metrics below are real `prometheus_client` series exposed at
`/metrics` (`server/observability/metrics.py`, Phase 10); a fresh
deployment's dashboard should start from `deployment/monitoring/prometheus.yml`
(`docker-compose.prod.yml`).

| Metric | What it means | Watch for |
|---|---|---|
| `meeting_translator_sessions_active` | Current live WebSocket sessions. | A sustained value near `WS_MAX_SESSIONS` -- new sessions will start being rejected with `OVERLOADED`. |
| `meeting_translator_packets_lost_total{source=...}` | Jitter-buffer forced-advance count (a gap was never filled). | A rising rate under normal network conditions suggests client-side network trouble, not a server bug. |
| `meeting_translator_packets_duplicate_total{source=...}` | Stale/duplicate packets ignored. | High values usually mean a client reconnected and resent already-acked frames -- expected after a reconnect, not itself an alert condition. |
| `meeting_translator_translation_requests_total{priority,status}` | Translation attempts by priority (`final`/`retry`/`completeness`) and outcome (`completed`/`failed`). | A rising `failed` rate relative to `completed`, especially `priority="final"`, indicates backend or validation trouble -- see "Queue pressure response" below. |
| `meeting_translator_translation_latency_seconds{priority}` / `meeting_translator_asr_latency_seconds{stage}` | Real backend latency histograms. | Compare p95/p99 (via a `histogram_quantile` PromQL query) against `docs/PRODUCT_REQUIREMENTS.md` section 5's objectives. |
| `meeting_translator_translation_queue_depth{priority}` | Current queue depth per priority, **per orchestrator instance** (see the caveat below). | A depth persistently at/near `TRANSLATION_QUEUE_CAPACITY_PER_PRIORITY` means the backend can't keep up. |
| `meeting_translator_circuit_breaker_state{backend="translation"\|"asr"}` | `0`=closed (normal), `1`=half_open (recovering), `2`=open (failing fast). | Any time spent at `2` means that backend was unavailable/overloaded enough to trip `CIRCUIT_BREAKER_FAILURE_THRESHOLD` consecutive failures -- check the backend directly. |

**Known limitation, found while writing `tests/test_load_concurrent_meetings.py`
(Phase 11)**: `translation_queue_depth` is a `Gauge`, not a `Counter` --
when multiple concurrent sessions in the same process share one `Metrics`
instance (the normal production case once `UtteranceOrchestrator` is wired
into the live gateway), each session's own queue-depth reading overwrites
the gauge rather than aggregating, so this metric is **not** a reliable
system-wide total across concurrent sessions today, only a same-process
per-update snapshot. `translation_requests_total` (a `Counter`) does not
have this problem -- it accumulates correctly regardless of how many
concurrent sessions share the `Metrics` instance. Treat
`translation_queue_depth` as informational, not alertable, until this is
revisited.

## Queue pressure response

1. Check `meeting_translator_translation_queue_depth{priority="final"}`
   and `{priority="retry"}` first -- these always take priority over
   `{priority="completeness"}` (`docs/ARCHITECTURE.md`'s vLLM scheduler
   priority policy). Completeness checks are auto-skipped once queue depth
   crosses `COMPLETENESS_SKIP_QUEUE_DEPTH`
   (`server/translation/queue.py`'s `should_skip_completeness`) -- this is
   already automatic, not something to intervene on manually.
2. Check `meeting_translator_circuit_breaker_state{backend="translation"}`.
   If it's open (`2`), the backend itself is failing, not just slow --
   go to "Whisper or vLLM OOM response" below.
3. If the backend is healthy but genuinely saturated (real request volume
   exceeds `TRANSLATION_MAX_CONCURRENCY`), that's a capacity question:
   scale the vLLM deployment, or reduce `WS_MAX_SESSIONS` on the
   application server to cap how many concurrent meetings it will accept
   in the first place.
4. `TRANSLATION_QUEUE_CAPACITY_PER_PRIORITY` overflow on the `final` lane
   causes a translation request to be dropped before even reaching the
   backend (`TranslationQueue.put` returns `False`) -- this is a
   configuration/capacity signal (lane too small for real burst size), not
   a bug to patch around by silently retrying.

## Whisper or vLLM OOM response

- **ASR (`AsrOutOfMemoryError`, `server/asr/errors.py`)**: retryable by
  design (`retryable = True`) -- the immediate effect is a typed `error`
  event with `code=ASR_FAILED`, not a crashed process. Sustained OOM means
  real concurrent ASR load exceeds the GPU's VRAM budget for `large-v3` --
  reduce concurrent sessions, or move ASR to its own GPU if it's currently
  co-located with translation (see "Prerequisites and GPU compatibility").
- **Translation (`TranslationOverloadedError`/vLLM 429/503,
  `server/translation/errors.py`)**: maps to `ErrorCode.OVERLOADED`,
  retryable. vLLM itself typically degrades via request queuing/rejection
  before a hard OOM kill; a hard vLLM process crash requires a manual
  restart (`GPU_MANUAL_WORKFLOW.md` -- Claude never restarts a GPU-hosted
  process; this is an operator action) followed by the health-verification
  steps above.
- Either way, the circuit breaker (`server/reliability/circuit_breaker.py`,
  wired into `FinalTranslator`/`FinalTranscriber`) trips after
  `CIRCUIT_BREAKER_FAILURE_THRESHOLD` consecutive failures and fails fast
  for `CIRCUIT_BREAKER_RESET_TIMEOUT_MS` before trying one recovery call --
  so a struggling backend does not get hammered with more load while an
  operator investigates.

## Client reconnect and device-change troubleshooting

- `AudioSender`'s reconnect loop (`client/transport/sender.py`) resends
  only still-unacked buffered frames on every reconnect
  (`OutboundBuffer`), with exponential backoff (`ReconnectBackoff`,
  `RECONNECT_BACKOFF_*` settings) -- a client that keeps cycling
  `CONNECTING`/`RECONNECTING` in its UI state almost always means the
  server is unreachable or rejecting the handshake (check `WS_MAX_SESSIONS`
  and auth config first), not a client-side bug.
- A stuck "Disconnect" button or a UI freeze on disconnect was a real,
  now-fixed bug class (`WINDOWS-UI-005`/`WINDOWS-UI-006`,
  `IMPLEMENTATION_STATUS.md`'s "Known limitations") -- if it recurs on a
  build older than that fix, that is the first thing to check (client
  version).
- Device removal/reconfiguration mid-session: the client is not expected
  to silently recover mid-stream; the documented behavior is to finalize
  the in-progress utterance (`FinalReason.DEVICE_RECONFIGURED`) and expect
  the user to reselect a device, not an automatic hot-swap.
- Loopback capturing zero frames is expected WASAPI behavior when nothing
  is actively playing on that output device, not a bug
  (`WINDOWS-UI-003`/`WINDOWS-UI-004` root-caused this exact symptom) --
  confirm audio is actually playing before treating "loopback stream open
  but silent" as an incident.

## Safe shutdown

- Send the process a normal termination signal (`SIGTERM` / container
  stop, not `SIGKILL`) so FastAPI's `lifespan` shutdown handler
  (`server/app.py`) runs: `/health/ready` flips to not-ready immediately
  (`ShutdownCoordinator.begin_shutdown()`), so a load balancer stops
  routing new connections right away, then the handler waits up to
  `SHUTDOWN_DRAIN_TIMEOUT_MS` for active sessions to finish/disconnect on
  their own before the process actually exits.
- A logged warning ("shutdown drain timed out with N session(s) still
  active") means real in-flight sessions were cut off -- this is reported
  with a session count only, never content, and is a signal to consider a
  longer drain timeout for that deployment's typical meeting length, not
  evidence of a bug.
- Never `SIGKILL`/hard-stop the application server as routine practice --
  it skips the drain entirely and every active session's connection is
  simply severed.
- Stopping the GPU-hosted vLLM/faster-whisper processes is a separate,
  manual, operator-only action (`GPU_MANUAL_WORKFLOW.md`) -- confirm the
  application server's circuit breaker has already marked that backend
  degraded (or that no sessions are relying on it) before intentionally
  taking it down for maintenance.

## Privacy-preserving diagnostics

- Default logging never contains raw audio, transcript, prompt or
  translation content (`docs/SECURITY.md`'s "Privacy" section,
  `shared/logging.py`'s `RedactionFilter`, proven end-to-end by
  `tests/test_logging_no_content_leak.py`) -- collecting and sharing a log
  file for troubleshooting does not require manual redaction first, by
  design.
- `STORE_RAW_AUDIO`, `LOG_TRANSCRIPT_CONTENT`, `LOG_TRANSLATION_CONTENT`
  (`.env.example`) all default to `false`. If a genuinely content-level
  bug requires temporarily enabling one to reproduce, treat that as a
  time-boxed, explicitly-approved debugging exception
  (`docs/SECURITY.md`'s checklist), not a standing configuration -- turn
  it back off immediately after.
- Correlation ids (`session_id`/`stream_id`/`utterance_id`/`request_id`,
  `server/observability/correlation.py`) are opaque identifiers, not
  content -- use them to correlate a user-reported incident ("session
  sess-abc123 around 14:32 UTC") across logs and metrics without ever
  needing the actual meeting content.
- When a user reports an incident, ask for the correlation id(s) from
  their client logs (if the client logs them) or the approximate
  time/session rather than asking them to describe or paste meeting
  content.

## Backup and restore for non-content configuration only

This project stores no meeting content by default (`docs/SECURITY.md`),
so "backup" here means configuration and operational state, never audio,
transcripts, prompts or translations:

- **Application configuration**: `.env` (never committed --
  `.env.example` documents every key with a safe placeholder). Back this
  up via whatever secret-management mechanism the deployment already
  uses; it is out of scope for this project's own tooling to manage
  production secrets.
- **Grafana dashboards/settings**: the `grafana-data` named volume in
  `docker-compose.prod.yml` -- back up via a standard volume snapshot, or
  export dashboards as JSON and keep those under version control
  separately (dashboards are configuration, not content).
- **Prometheus data**: the `prometheus-data` volume is a metrics time
  series (counts/latencies/labels, never content) -- back up if
  historical metrics retention matters for this deployment; losing it
  does not affect the running system's correctness, only observability
  history.
- **Client settings**: `%APPDATA%\MeetingTranslator\client_settings.json`
  per user machine -- device selection, enabled flags, language preset
  only, provably no secret (`client/ui/settings_store.py`'s own test
  coverage). Not centrally backed up; each user's machine holds its own.
- **`scripts/local_backup.py`/`.local_backups/`** is this *repository's*
  own local, Git-free development-workflow snapshot tool
  (`LOCAL_WORKFLOW.md`) -- it snapshots source code before each
  implementation phase, not a production backup mechanism, and already
  excludes model weights, caches, logs, audio recordings and secrets by
  design (`scripts/backup_common.py`). Do not repurpose it as a
  production backup tool; it was never designed or reviewed for that.
- There is no database/durable-state migration concern today: Redis is
  declared in settings/compose (`REDIS_URL`) but not yet used for any
  durable state by server code (grep confirms no `import redis` in
  `server/`) -- if a later phase adds durable use of Redis, this section
  should be revisited.
