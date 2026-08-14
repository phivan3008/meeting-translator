# Security

Security posture of the application server and Windows client: what is
enforced, where it lives in the codebase, the checklist to run before a
deployment, and the dependency-pinning strategy. TLS termination and
reverse-proxy configuration are documented separately in
`docs/DEPLOYMENT.md`; this file covers everything else.

## Authentication

- Production authentication is JWT (`server/transport/auth.py`,
  `JwtAuthenticator`), verified with `PyJWT[crypto]` against an
  **asymmetric** public key only. Construction rejects `HS*` (symmetric)
  algorithms outright -- a symmetric secret configured as if it were a
  "public" key would let anyone who can read the server's config forge
  tokens, so that misconfiguration is refused at startup rather than
  silently accepted.
- Verification checks signature, `iss` (issuer), `aud` (audience), `exp`
  (expiry, with `JWT_LEEWAY_SECONDS` clock-skew tolerance) and requires a
  non-empty string `sub` claim. `algorithms=[...]` is passed explicitly to
  `jwt.decode`, which is what defeats the classic `alg: none` /
  algorithm-confusion attacks (an attacker-supplied `alg` header can never
  widen what the server will accept).
- Failure messages are generic (`"token rejected: <ExceptionClassName>"`)
  and never include the raw token or claim values, so a leaked server log
  cannot be used to fingerprint why a specific token was rejected.
- `server/app.py`'s `_build_authenticator` selects `JwtAuthenticator` only
  when `JWT_PUBLIC_KEY_PATH` is set, and **fails fast** (raises at app
  construction, not on first request) if that path is set but unreadable --
  a misconfigured deployment refuses to start rather than silently falling
  back to no auth.
- Without `JWT_PUBLIC_KEY_PATH` set, the server falls back to
  `StaticTokenAuthenticator` (`AUTH_DEV_TOKEN`), which allows anonymous
  connections only when `APP_ENV != production` (`Settings.is_production`).
  **`JWT_PUBLIC_KEY_PATH` must be set for any production deployment** --
  there is no separate "production mode" flag that enforces this; an
  operator who deploys with `APP_ENV=production` but forgets to set
  `JWT_PUBLIC_KEY_PATH` gets a server that requires the (still-blank)
  static dev token instead, which is not a real access control. Verify
  `JWT_PUBLIC_KEY_PATH` is set as part of the deployment checklist below.

## Transport

- The application server itself does not terminate TLS; it is deployed
  behind a reverse proxy that does (`docs/DEPLOYMENT.md`). Do not expose
  the plain `ws://`/`http://` port directly to untrusted networks.
- Binary audio frames and JSON control/event messages share one WebSocket
  connection per `docs/PROTOCOL.md`; both are subject to the same
  authenticated session before any frame is processed.

## Request, packet, session and queue limits

Enforced in `shared/settings.py` (validated at load) and
`server/transport/`:

| Limit | Setting | Enforcement point |
|---|---|---|
| Max WebSocket frame size | `WS_MAX_PACKET_BYTES` | `gateway.py` rejects with `PAYLOAD_TOO_LARGE` |
| Max concurrent streams per session | `WS_MAX_STREAMS_PER_SESSION` | `session.py` (`SessionManager`) |
| Max concurrent sessions, server-wide | `WS_MAX_SESSIONS` | `session.py`; pre-checked in `gateway._handshake` and re-enforced in `SessionManager.create_session`, both returning `OVERLOADED`/retryable rather than a bare connection drop |
| Idle connection timeout | `WS_IDLE_TIMEOUT_MS` | `gateway.py` closes with policy-violation on timeout |
| Per-connection rate limiting | `WS_RATE_LIMIT_PACKETS_PER_SEC` / `WS_RATE_LIMIT_BURST` | `server/transport/limits.py` (`TokenBucket`) |
| Translation queue capacity | `TRANSLATION_QUEUE_CAPACITY_PER_PRIORITY` | `server/translation/queue.py` (`TranslationQueue`), bounded per priority lane so low-priority completeness work cannot starve final/retry capacity |

A server-wide session cap is distinct from the per-session stream cap: the
former bounds total resource usage across all clients, the latter bounds
one client's fan-out (microphone + loopback, plus any future stream types).

## Privacy: no raw content logged by default

- `shared/logging.py`'s `RedactionFilter` is attached to every configured
  handler (`configure_logging`, idempotent) and masks both structured log
  extras whose *key* matches a sensitive-content hint (`transcript`,
  `translation`, `prompt`, `audio`, plus credential-family keys) and
  secret-like `key=value` patterns embedded directly in free-form message
  text.
- This is defense in depth, not the primary guarantee: the primary
  guarantee is that production call sites (`server/asr/worker.py`,
  `server/translation/worker.py`, `server/orchestration/pipeline.py`,
  `server/transport/gateway.py`) simply never pass transcript, translation,
  prompt or raw audio content into a log call in the first place -- logging
  only opaque identifiers (`session_id`, `stream_id`, `utterance_id`,
  sizes, counts, sequence numbers).
- `tests/test_logging_no_content_leak.py` proves this end-to-end: it drives
  the real `FinalTranscriber`, `FinalTranslator` and full
  `UtteranceOrchestrator` pipeline with marker text standing in for
  transcript/translation content, captures every log record emitted
  anywhere in the process during the run, and asserts the marker never
  appears -- including a negative-control test that proves the harness
  really would catch a leak if one occurred.
- `STORE_RAW_AUDIO`, `LOG_TRANSCRIPT_CONTENT` and `LOG_TRANSLATION_CONTENT`
  (`.env.example`) all default to `false`. Do not enable them in a
  production deployment without a documented, time-boxed debugging reason.

## Correlation IDs are not content

`server/observability/correlation.py` binds `session_id`, `stream_id`,
`utterance_id` and a per-request `request_id` via `contextvars` and injects
them into every log record through `CorrelationFilter`. These are opaque
identifiers (UUIDs / protocol-assigned ids), never derived from or
containing transcript/translation/audio content, so they compose safely
with `RedactionFilter` without needing any redaction of their own.

## Readiness must not leak internal detail

`/health/ready` (`server/app.py`) reports only booleans per dependency
check (`settings`, `not_shutting_down`, and -- only when
`READINESS_CHECK_TRANSLATION_BACKEND` is enabled -- `translation_backend`).
`_check_translation_backend` catches every exception from the reachability
probe and returns `False`; it never surfaces the exception message,
hostname or URL into the response body
(`tests/test_health.py::test_readiness_translation_backend_check_enabled_failure`
asserts neither `"vllm"` nor `"http"` appears in the response).

## Overload and backend-failure behavior

- `server/reliability/circuit_breaker.py`'s `CircuitBreaker` (CLOSED /
  OPEN / HALF_OPEN, time-injected and pure) is wired into both
  `FinalTranslator` and `FinalTranscriber` (optional constructor params,
  `circuit_breaker=`). When open, a call is skipped before it ever reaches
  the backend (fail fast instead of piling more load onto an
  already-struggling GPU host) and reported as `issue="circuit_open"`
  (translation) or a retryable `AsrCircuitOpenError` mapping to
  `ErrorCode.OVERLOADED` (ASR).
- Current circuit and queue-depth state is exported via
  `/metrics` (`circuit_breaker_state{backend="translation"|"asr"}`,
  `translation_queue_depth{priority="final"|"retry"|"completeness"}`), so
  an operator dashboard sees degradation before it becomes a full outage.
- `CIRCUIT_BREAKER_FAILURE_THRESHOLD` / `CIRCUIT_BREAKER_RESET_TIMEOUT_MS`
  are the only tunables; there is deliberately no per-request retry-storm
  behavior beyond the single documented translation retry
  (`docs/TRANSLATION.md`).

## Graceful shutdown

`server/reliability/shutdown.py`'s `ShutdownCoordinator` flips
`/health/ready` to not-ready the instant shutdown begins (so a load
balancer stops routing new connections immediately), then the FastAPI
`lifespan` handler waits, bounded by `SHUTDOWN_DRAIN_TIMEOUT_MS`, for
active sessions to finish before the process actually exits. A timeout is
logged (session count only, no content) rather than silently killing
in-flight work.

## Secrets

- No secret (JWT signing key, `VLLM_API_KEY`, `AUTH_DEV_TOKEN`) is ever
  committed to source or written into `IMPLEMENTATION_STATUS.md`,
  `MANUAL_ACTIONS.md` or `USER_RESULTS.md` -- per `CLAUDE.md`'s "Never
  store secrets in source or status documents."
- `JWT_PUBLIC_KEY_PATH` points at a public key file on disk; the
  corresponding private signing key is never held by this application
  server at all (it belongs to whatever identity provider issues tokens).
- `.env.example` documents every setting name with a safe placeholder or
  empty default; real values live only in an untracked `.env` (see
  `deployment/docker-compose.yml`'s `env_file:`).

## Dependency pinning strategy

All dependencies in `pyproject.toml` use a `>=X,<Y` range pinned to the
current major (or, for pre-1.0 packages, current minor) version, e.g.
`"fastapi>=0.110,<1"`, `"PyJWT[crypto]>=2.8,<3"`. Rationale:

- **Floor (`>=X`)** pins to the oldest version actually validated locally
  (via `pytest -m "not gpu and not windows_audio"` and `mypy`) -- not just
  "whatever happened to be latest when first added" -- so a fresh install
  cannot silently resolve to something older and untested.
- **Ceiling (`<Y`)** blocks the next major version (or next minor for
  pre-1.0 packages, since those commonly break on minor bumps) from being
  pulled in automatically. A major bump is a deliberate, reviewed action:
  bump the ceiling, re-run the full local check suite, and update this
  file's floor if the new version requires code changes -- never widen the
  ceiling as a side effect of an unrelated change.
- Security patches within an already-allowed range are picked up
  automatically by a routine `pip install -e .[dev,server]` /
  `uv sync`-style reinstall; this project does not vendor a lockfile, so
  "run the full local check suite after any dependency reinstall" is the
  enforcement mechanism, not a separate lockfile-diff review step.
- GPU-only dependencies (`faster-whisper`, `silero-vad`, `vllm`) are
  intentionally unpinned or loosely pinned in the `gpu` extra since they
  are installed and exercised manually on the GPU host per
  `GPU_MANUAL_WORKFLOW.md`, never by the CPU-only local check suite --
  pinning them tightly here would create false confidence about a
  environment this repository's automated checks never actually run in.
- `websockets>=12,<13` is pinned narrower than most other ranges because
  of a real incompatibility found during Phase 09 manual testing
  (`websockets.asyncio.client` does not exist before 13.0); the ceiling
  intentionally excludes 13.x until that's re-validated, not just as a
  matter of general policy.

## Pre-deployment security review checklist

Run through this before any non-development deployment:

- [ ] `APP_ENV=production` is set, **and** `JWT_PUBLIC_KEY_PATH` is set and
      points at a real, correct public key (production auth is not "on"
      just because `APP_ENV=production` -- see "Authentication" above).
- [ ] `AUTH_DEV_TOKEN` is unset/blank in production (it has no effect once
      JWT auth is configured, but leaving a real-looking value around
      invites confusion).
- [ ] TLS is terminated by the reverse proxy in front of this server
      (`docs/DEPLOYMENT.md`); the application port itself is not reachable
      from an untrusted network.
- [ ] `WS_MAX_SESSIONS`, `WS_MAX_STREAMS_PER_SESSION`,
      `WS_MAX_PACKET_BYTES`, `WS_RATE_LIMIT_PACKETS_PER_SEC` /
      `WS_RATE_LIMIT_BURST` are sized for the deployment's real capacity,
      not left at development defaults.
- [ ] `STORE_RAW_AUDIO`, `LOG_TRANSCRIPT_CONTENT`, `LOG_TRANSLATION_CONTENT`
      are all `false` unless a specific, time-boxed debugging exception has
      been explicitly approved and documented.
- [ ] `LOG_LEVEL` is not set to a verbosity that would defeat the
      redaction filter's assumptions (the filter redacts what it
      recognizes; it is not a substitute for not logging content in the
      first place -- see "Privacy" above).
- [ ] `/metrics` is not exposed to an untrusted network without its own
      access control at the reverse-proxy layer (it has no auth of its
      own; it exposes operational counts, not content, but counts alone
      can still be sensitive in some threat models -- e.g. session volume).
- [ ] `READINESS_CHECK_TRANSLATION_BACKEND` reachability, if enabled,
      points at the correct internal translation-GPU address (a wrong
      address would make `/health/ready` flap without a real backend
      problem).
- [ ] `pytest -m "not gpu and not windows_audio"`, `mypy client server
      shared` and `ruff check .` all pass on the exact commit being
      deployed (this repository has no CI; this is a manual gate --
      `CLAUDE.md`'s "Default local quality checks").
- [ ] Dependency versions actually installed match the pinned ranges in
      `pyproject.toml` (`pip list` / `uv pip list`); no ad hoc
      `pip install` outside those ranges on the deployment host.
- [ ] Secrets (JWT signing key held by the issuer, `VLLM_API_KEY` if the
      translation backend requires one) are supplied via the deployment
      environment's secret mechanism, never committed or placed in
      `IMPLEMENTATION_STATUS.md` / `MANUAL_ACTIONS.md` / `USER_RESULTS.md`.
