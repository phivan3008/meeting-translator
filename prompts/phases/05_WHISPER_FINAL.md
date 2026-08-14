# Phase 05: Final Whisper ASR

Implement final-only ASR before partial streaming.

Required outcomes:

- ASR interface and typed result/error models.
- faster-whisper large-v3 adapter with lazy loading and configuration.
- Source language supplied from stream configuration as `vi` or `ja`.
- Dedicated executor/worker so inference does not block the event loop.
- Final reconciliation over the completed utterance audio.
- Final beam size, temperature and previous-text configuration.
- Model unavailability, timeout and OOM mapping to typed errors.
- Fake ASR test double.
- Integration from utterance finalization to final transcription event without translation.
- GPU tests marked `gpu` and no implicit weight download in CPU tests.

Run available checks and update status. Do not claim GPU inference was tested unless it actually was.
## Mandatory manual checkpoint

After local mock tests pass, prepare `GPU-ASR-001` to inspect the user-managed ASR GPU environment. Do not install or run anything on the GPU server yourself. Stop and wait for the user's output before preparing model installation or inference actions. Each later GPU step must have a separate action ID.
