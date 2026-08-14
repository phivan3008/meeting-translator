# Phase 04: VAD and Utterance State Machine

Implement VAD and utterance segmentation behind clean interfaces.

Required outcomes:

- VAD protocol and Silero adapter with lazy model initialization.
- Test VAD implementation using deterministic probability frames.
- Per-stream VAD state machine: IDLE, SPEECH_STARTING, SPEAKING, POSSIBLE_END, FINALIZING.
- Configurable speech start, minimum speech, soft silence, hard silence, padding and maximum utterance.
- Ring buffer supporting pre-roll.
- Utterance state with IDs, timestamps, audio buffer and finalization reason.
- Events for speech start, soft silence, resumed speech and forced finalization.
- No blocking VAD work on the asyncio event loop.
- Extensive state-transition and boundary tests.

Do not implement Whisper yet. Run checks and update status.
