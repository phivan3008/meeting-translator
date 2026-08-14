# Product Requirements

## 1. Product goal

Provide near-real-time transcription and bidirectional translation for online meetings between Vietnamese and Japanese participants.

## 2. Users

- Vietnamese participant using a Windows meeting client.
- Japanese participant using a Windows meeting client.
- System operator managing the GPU server.

## 3. Primary flows

### Vietnamese-side client

- Microphone is assumed Vietnamese and translates to Japanese.
- Meeting loopback is assumed Japanese and translates to Vietnamese.

### Japanese-side client

- Microphone is assumed Japanese and translates to Vietnamese.
- Meeting loopback is assumed Vietnamese and translates to Japanese.

The user may change language mapping in settings. Automatic detection is optional but not used by default for short chunks.

## 4. Functional requirements

### Audio client

- Enumerate microphone devices.
- Enumerate WASAPI loopback devices through PyAudioWPatch.
- Allow selecting microphone and meeting output loopback independently.
- Capture both sources concurrently as separate streams.
- Normalize each source to mono 16 kHz PCM S16LE.
- Use bounded queues and report overrun/drop metrics.
- Handle device removal and reconfiguration.
- Send heartbeat even during silence.
- Reconnect automatically with bounded local buffering.

### Server ingestion

- Authenticate the WebSocket session.
- Validate protocol versions and stream declarations.
- Decode binary audio packets.
- Maintain one independent processing context per stream.
- Reorder within a small jitter window and detect gaps.
- Reject malformed, stale, duplicate and oversized packets safely.

### VAD

- Run per stream on CPU.
- Preserve speech pre-roll and post-roll.
- Emit speech start, soft silence, hard silence and finalization signals.
- Force boundaries for excessively long utterances.

### ASR

- Use faster-whisper large-v3.
- Fix source language from stream configuration.
- Generate partial transcription periodically while speaking.
- Separate stable and unstable text.
- Reconcile a final transcription over the complete utterance.
- Do not treat the last partial as the authoritative final result.

### Finalization

- Use deterministic heuristics first.
- Hard silence always permits forced finalization.
- Optional Qwen completeness checks occur only at soft silence and ambiguous boundaries.
- Completeness checks are low-priority and have short timeouts.
- Under load, skip LLM completeness and fall back to VAD and heuristics.

### Translation

- Use Qwen/Qwen3.6-27B-FP8 through a local vLLM OpenAI-compatible endpoint.
- Use text-only and non-thinking operation.
- Translate finalized utterances only.
- Support Japanese to Vietnamese and Vietnamese to Japanese.
- Preserve names, numbers, dates, versions, URLs, identifiers and technical terms.
- Use short relevant glossary and no more than two prior finalized sentences as context.
- Return translation only, with no commentary or reasoning.
- Validate output and retry once when appropriate.
- Never suppress final transcription when translation fails.

### Client display

- Render an active partial transcription as a gray hint.
- Distinguish stable and unstable partial text visually.
- Update in place by utterance ID and increasing revision.
- On final, replace the hint with bold transcription.
- Render translation below in normal weight.
- Show direction, source, timestamp and retry/error state.

## 5. Initial latency objectives

- VAD speech-start p95: below 250 ms.
- First partial p95: below 1.8 seconds.
- Partial update target: every 500 ms while speaking.
- Final ASR p95: below 1.2 seconds after finalization begins.
- Translation p95: below 1.2 seconds under target load.
- End-to-end final p95: below 3.5 seconds.

These are objectives to measure, not values to fake in tests.

## 6. Non-functional requirements

- Secure WebSocket and HTTPS in production.
- Short-lived authentication tokens.
- No raw audio storage by default.
- No full transcript, prompt or translation in production logs by default.
- Graceful degradation during model overload.
- Bounded memory and request concurrency.
- Metrics for every processing stage.
- Unit tests runnable without GPU and without Windows audio hardware.

## 7. Out of scope for initial MVP

- Speech synthesis.
- Automatic speaker diarization.
- macOS and Linux client audio loopback.
- Translation of every partial ASR revision.
- Full meeting recording and archival.
- Guaranteed support for overlapping speakers.
- Enterprise SSO integration beyond an initial JWT interface.
