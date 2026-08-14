# Acceptance Criteria

## Repository and quality

- Project installs from documented commands.
- Formatting, linting, type checks and CPU test suite pass.
- GPU and Windows-only tests are separately marked.
- No model is downloaded implicitly during unit tests.
- No production path contains placeholder behavior.

## Client audio

- Microphone and WASAPI loopback are selectable independently.
- Both can be captured concurrently without mixing.
- Captured server-side fixtures decode as mono 16 kHz PCM S16LE.
- Audio callback does not execute network or resampling work.
- Queue overflow behavior is bounded, measured and tested.

## Protocol

- Binary packet round-trip tests pass.
- Truncated, oversized and length-mismatched packets are rejected.
- Duplicate revisions and packets are idempotently ignored.
- JSON events validate against versioned Pydantic schemas.

## VAD and utterance

- Per-stream state is independent.
- Pre-roll and post-roll behavior is covered by tests.
- Soft silence may trigger a completeness decision.
- Hard silence forces finalization.
- Maximum utterance duration forces a safe boundary.

## ASR

- Source language is passed from stream configuration.
- Partial revisions strictly increase.
- Stable-prefix logic does not duplicate committed text.
- Final ASR is run against the completed utterance.
- Test doubles allow CPU CI without model weights.

## Translation

- Requests target `qwen3.6-27b-translate` through an OpenAI-compatible client.
- Thinking is disabled.
- Only finalized transcription enters translation.
- Japanese-to-Vietnamese and Vietnamese-to-Japanese prompt paths are tested.
- Validation detects number or identifier corruption.
- Translation failure still publishes final transcription.

## UI

- Partial text is shown as a gray hint.
- Stable and unstable parts are visually distinguishable.
- Newer revision replaces older partial in place.
- Final transcription is bold and replaces partial.
- Translation appears below in normal weight.
- Retry and failure states are visible.

## Integration

- An in-memory or mocked flow demonstrates:
  audio packets -> VAD -> partial -> final ASR -> translation -> final event.
- WebSocket reconnect does not duplicate final utterances.
- Metrics expose stage latency and queue depth.
- Sensitive content is not present in default production logs.
