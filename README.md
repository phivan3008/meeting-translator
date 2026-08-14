# Meeting Translator

Near-real-time Vietnamese-Japanese meeting transcription and translation:
a Windows desktop client (PySide6, WASAPI microphone + loopback capture)
streaming to a GPU-backed application server (FastAPI WebSocket gateway,
Silero VAD, faster-whisper large-v3, Qwen3.6-27B-FP8 via vLLM). See
`docs/PRODUCT_REQUIREMENTS.md` and `docs/ARCHITECTURE.md` for the full
design, and `docs/FINAL_IMPLEMENTATION_REPORT.md` for exactly what is
verified today versus still hardware-pending.

## Quick start: CPU mocked development

No GPU, no Windows, no PySide6/PyAudioWPatch, no model weights required.
This is how the whole project is built and tested day to day.

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate    |    Linux/macOS: source .venv/bin/activate
pip install -e ".[dev]"

ruff format --check .
ruff check .
mypy client server shared
pytest -m "not gpu and not windows_audio"
```

That last command runs the full domain-logic test suite (protocol codec,
VAD state machine, ASR/translation worker logic, the orchestration
pipeline, transport/gateway, auth, reliability, observability, and the
end-to-end mocked pipeline test) against `Scripted*` fakes -- no model
weights are ever downloaded implicitly (`docs/ACCEPTANCE_CRITERIA.md`).

Run the real (CPU-only) FastAPI dev server against those same fakes:

```bash
pip install -e ".[server]"
uvicorn server.app:app --reload
curl http://localhost:8080/health/live
```

Useful local tools (also CPU-only, no GPU required):

```bash
python scripts/latency_report.py --count 20          # measured p50/p95/p99, fake backends
python scripts/load_test.py --sessions 10 --duration-s 10   # real WS load against a running server
python scripts/local_backup.py --label my-change      # timestamped local snapshot (see LOCAL_WORKFLOW.md)
```

## Quick start: Windows client development

Requires Windows (WASAPI loopback capture is Windows-only,
`docs/PRODUCT_REQUIREMENTS.md` "Out of scope") and real audio hardware to
actually exercise capture.

```powershell
pip install -e ".[client,windows-audio,dev]"
python -m client.ui.bootstrap
```

`client/ui/main_window.py` (the real PySide6 window) is intentionally
excluded from the CPU test suite; the Qt-independent state layer it
renders from (`client/ui/view_model.py`, `client/ui/settings_store.py`,
`client/ui/session_controller.py`) is fully unit-tested without Qt. See
`IMPLEMENTATION_STATUS.md`'s `WINDOWS-UI-*` history for what has actually
been hardware-verified on real Windows hardware.

To build a distributable executable, see `docs/DEPLOYMENT.md`'s "Windows
client packaging" section (`scripts/build_windows_client.py`, PyInstaller).

## Quick start: GPU deployment

The GPU-hosted pieces (faster-whisper, vLLM) are never installed, started
or operated by an automated agent in this project -- every GPU-server step
is manual, per `GPU_MANUAL_WORKFLOW.md`. See:

- `docs/OPERATOR_RUNBOOK_SEED.md` -- prerequisites, model download, vLLM
  launch, health verification, metrics/alerting, OOM response, safe
  shutdown, backup/restore.
- `docs/DEPLOYMENT.md` -- TLS/reverse-proxy configuration (nginx/Caddy
  examples), Docker Compose (`deployment/docker-compose.prod.yml`: app
  server + Redis + Prometheus + Grafana), version/upgrade strategy.
- `docs/SECURITY.md` -- authentication (JWT), limits, privacy/redaction
  guarantees, dependency-pinning strategy, pre-deployment checklist.

Minimal path once vLLM and faster-whisper are confirmed healthy on their
GPU host(s) (`GPU_MANUAL_WORKFLOW.md`'s staged `GPU-*` action sequence):

```bash
cp .env.example .env
# edit .env: VLLM_BASE_URL, JWT_PUBLIC_KEY_PATH, APP_ENV=production, ...
docker compose -f deployment/docker-compose.prod.yml up -d
curl http://localhost:8080/health/ready
```

## Repository layout

```text
client/       Windows client: audio capture, transport, PySide6 UI
server/       Application server: transport gateway, VAD, ASR, translation,
              orchestration, reliability, observability
shared/       Protocol (wire format + Pydantic schemas), settings, logging,
              version -- imported by both client and server, no Qt/FastAPI/
              CUDA coupling
tests/        CPU test suite (pytest, no GPU/Windows hardware required by
              default) plus gpu-/windows_audio-marked hardware tests
scripts/      local_backup.py/local_restore.py (dev snapshots),
              latency_report.py/load_test.py (measurement tooling),
              build_windows_client.py (PyInstaller packaging)
deployment/   Dockerfile, docker-compose.yml (local dev),
              docker-compose.prod.yml (app + Redis + monitoring), Prometheus/
              Grafana config
docs/         Architecture, protocol, product requirements, security,
              deployment, operator runbook, acceptance criteria, final
              implementation report
```

## Project status and verification

`IMPLEMENTATION_STATUS.md` is the authoritative, continuously-updated
record of what's implemented, what's `LOCAL_VERIFIED` versus
`HARDWARE_VERIFIED` versus still pending, and every manual GPU/Windows
action's result. `docs/FINAL_IMPLEMENTATION_REPORT.md` (Phase 11) is a
point-in-time acceptance-criteria walkthrough separating what's verified
from what still needs hardware.

## Development workflow

This project is tracked in Git (`origin` at
`https://github.com/phivan3008/meeting-translator.git`, branch `master`).
Changes are also protected by timestamped local snapshots
(`scripts/local_backup.py` -> `.local_backups/`, excluding virtual
environments, model weights, caches, logs, audio recordings and secrets)
taken before editing -- git history and local snapshots are both kept, one
does not replace the other. GPU-server operations are never executed
automatically -- every one is prepared as an exact, reviewable command set
in `MANUAL_ACTIONS.md` for the operator to run and report back, per
`GPU_MANUAL_WORKFLOW.md`. The full phase-by-phase implementation prompts
used to build this project are in `prompts/phases/`; `CLAUDE.md` is the
binding rule set for how work here is done.
