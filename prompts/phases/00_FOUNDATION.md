# Phase 00: Local Project Foundation

Create the initial local-only project foundation. Do not use Git.

Required outcomes:

- Python 3.11+ project configuration.
- Directories for `client`, `server`, `shared`, `tests`, `deployment` and `scripts`.
- Dependency groups for client, server, development, GPU and Windows audio.
- Ruff, mypy and pytest configuration.
- Validated environment-based settings.
- Privacy-preserving logging and redaction tests.
- Basic FastAPI liveness and readiness endpoints.
- Minimal PySide6 bootstrap isolated from Linux CPU test imports.
- Local Docker Compose skeleton, but do not run services on a remote GPU server.
- `.env.example`, ignored-local-file guidance and development commands.
- `scripts/local_backup.py` and `scripts/local_restore.py`.
- Backup excludes virtual environments, model files, caches, logs, recordings, secrets and `.local_backups` itself.
- Backup creates manifest and checksums.
- Unit tests for settings, health, logging redaction and backup selection/exclusion.

Do not download models. Do not create production fake transcription or translation. Run safe local checks, update status, and stop after Phase 00.
