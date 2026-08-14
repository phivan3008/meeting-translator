# Development Guide (Local, Git-free)

This project is developed entirely in the local project directory and does not
use Git. See `CLAUDE.md`, `LOCAL_WORKFLOW.md` and `GPU_MANUAL_WORKFLOW.md` for
the mandatory workflow rules.

## Requirements

- Python 3.11 or newer (3.12 is fine for local CPU work).
- Windows 10/11 for client audio; GPU host is operated manually.

## Environment setup

```powershell
py -3.11 -m venv .venv           # or: python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -e ".[dev]"          # CPU dev tooling: ruff, mypy, pytest, fastapi
```

Optional dependency groups (install only where applicable):

```powershell
pip install -e ".[server]"          # FastAPI transport server
pip install -e ".[client]"          # PySide6 Windows client UI
pip install -e ".[windows-audio]"   # PyAudioWPatch (Windows only)
pip install -e ".[gpu]"             # faster-whisper / vLLM (GPU host, manual)
```

Copy the example environment file and adjust as needed:

```powershell
Copy-Item .env.example .env
```

## Local quality checks

```powershell
ruff format --check .
ruff check .
mypy client server shared
pytest -q -m "not gpu and not windows_audio"
```

## Local snapshots (backup / restore)

Create a timestamped snapshot before starting a new phase:

```powershell
python scripts/local_backup.py --label phase-01
```

Restore a snapshot into a separate directory (never overwrites the working
tree by default) and verify checksums:

```powershell
python scripts/local_restore.py --snapshot <name> --verify
```

Snapshots live under `.local_backups/` and exclude virtual environments,
model weights, caches, logs, recordings and secrets.

## Running the server locally

```powershell
uvicorn server.app:app --host 0.0.0.0 --port 8080
# Liveness:  GET http://localhost:8080/health/live
# Readiness: GET http://localhost:8080/health/ready
```

## Running the client bootstrap (Windows, manual)

```powershell
pip install -e ".[client]"
python -m client.ui.bootstrap
```

## Test markers

- `gpu`: requires a GPU host and model weights. Run manually.
- `windows_audio`: requires Windows audio hardware. Run manually.

The default CPU test command above excludes both.
