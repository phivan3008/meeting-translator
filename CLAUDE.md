# CLAUDE.md

## Mission

Build a production-oriented Windows desktop client and GPU-backed server for near-real-time Vietnamese-Japanese meeting transcription and translation.

## Mandatory local-and-git policy

- This project is tracked in Git, remote `origin` at `https://github.com/phivan3008/meeting-translator.git`, branch `master` (since 2026-08-14).
- Commit at logical checkpoints (e.g., finishing a phase, a manual-action tracking-file update, a bug fix) rather than after every single file edit.
- Push each commit to `origin/master` automatically once created, unless the user says otherwise for a specific change.
- Never force-push, rewrite history (`rebase`, `commit --amend` on already-pushed commits), delete branches, or skip hooks (`--no-verify`) without explicit user instruction for that specific action.
- Still take a timestamped local snapshot before editing, per `LOCAL_WORKFLOW.md` -- git history and local snapshots are both kept; neither replaces the other.
- Work only with files in the user's local project directory unless explicitly preparing instructions.
- Never directly access or operate the GPU server.
- For every GPU-server operation, follow `GPU_MANUAL_WORKFLOW.md`, write an action to `MANUAL_ACTIONS.md`, and stop for user feedback.
- Never assume a manual command succeeded.
- Never claim hardware verification from mocks.

## Required reading before each phase

1. `CLAUDE.md`
2. `LOCAL_WORKFLOW.md`
3. `GPU_MANUAL_WORKFLOW.md`
4. Relevant files under `docs/`
5. `IMPLEMENTATION_STATUS.md`
6. `MANUAL_ACTIONS.md`
7. `USER_RESULTS.md`
8. Existing source and tests

## Mandatory working method

1. Inspect the local project and current status.
2. List files to create or modify.
3. Create a timestamped local snapshot before editing after Phase 00 provides the backup tool.
4. Implement only the requested phase.
5. Run all safe local formatting, lint, type and CPU/mock tests.
6. Fix local failures.
7. If Windows hardware or GPU verification is needed, prepare exact manual instructions and stop.
8. Analyze user-provided output before continuing.
9. Update status and documentation truthfully.
10. Commit at a logical checkpoint and push to `origin/master`, per "Mandatory local-and-git policy".
11. Do not delete or weaken tests to obtain a pass.

## Fixed architecture

- Windows 10/11 client, Python 3.11+, PySide6.
- Audio capture through PyAudioWPatch imported as `pyaudiowpatch`.
- Never use sounddevice or audiodevice.
- Microphone and WASAPI loopback remain separate streams.
- Normalize to mono 16 kHz PCM S16LE.
- Binary audio plus JSON control/events over WebSocket.
- Silero VAD on CPU.
- faster-whisper large-v3 on a GPU selected by the user.
- Sliding-window partial ASR with stable-prefix/local-agreement behavior.
- Language is assigned by stream instead of repeatedly detected.
- Translation through local Qwen/Qwen3.6-27B-FP8 served by vLLM.
- Qwen runs text-only with thinking disabled.
- Translate finalized utterances only.
- Heuristics and VAD precede optional low-priority Qwen completeness checks.
- Partial updates are idempotent by utterance and revision.
- Final events replace partial display.
- ASR and translation support separate GPUs.

## Engineering rules

- Use ports/adapters around audio, VAD, ASR, translation, queue and transport dependencies.
- Keep domain logic testable without FastAPI, Qt, CUDA or model weights.
- All queues are bounded with explicit overload policy.
- No blocking audio or inference work on the asyncio event loop.
- Use monotonic time for durations and UTC wall time for external timestamps.
- Version and validate all messages.
- Do not log raw audio, transcript, prompt or translation by default.
- Never store secrets in source or status documents.
- Public Python APIs use meaningful type hints.
- No production-path fake results, pass statements or placeholders.

## GPU interaction protocol

When GPU work is required:

1. Generate local config/script first.
2. Assign a unique action ID.
3. Write exact commands, run location, prerequisites, safety notes, expected success indicators and rollback.
4. Ask the user to run them manually.
5. End the response with `WAITING_FOR_USER: <Action ID>`.
6. Do not continue dependent work until the user returns results.
7. Record non-sensitive results in `USER_RESULTS.md`.

## Testing

- Unit tests for protocol, state machines, stable prefix, prompts and validators.
- Boundary tests for packet parsing and sequence handling.
- WebSocket integration tests.
- Model tests use mocks locally.
- GPU tests use marker `gpu` and are executed only by the user on the appropriate environment.
- Windows audio tests use marker `windows_audio` and are executed manually by the user on Windows.
- Tests never download models implicitly.

## Default local quality checks

```bash
ruff format --check .
ruff check .
mypy client server shared
pytest -q -m "not gpu and not windows_audio"
```

## Definition of done

A phase can be `LOCAL_VERIFIED` when local checks pass. It can be `HARDWARE_VERIFIED` only after the user runs the documented manual checks and provides sufficient output. Hardware-dependent phases may remain `LOCAL_VERIFIED / HARDWARE_PENDING` without pretending to be complete.
