# Phase 07: Qwen3.6-27B-FP8 Translation via vLLM

Implement finalized-text translation with the fixed model and runtime.

Required outcomes:

- Async OpenAI-compatible vLLM client.
- Served model name `qwen3.6-27b-translate` configurable but defaulted correctly.
- Request uses non-thinking mode, temperature 0, top-p 1, bounded tokens and no output streaming.
- Japanese-to-Vietnamese and Vietnamese-to-Japanese prompt builders matching `docs/TRANSLATION.md`.
- Relevant glossary support and at most two prior final sentences as context.
- Priority queue for final translation, retry and completeness work.
- Bounded concurrency, timeout, cancellation and one retry.
- Translation validator for empty output, explanations, repetition, target-language plausibility, number/date/URL/version/identifier preservation and extreme length ratio.
- `utterance.final` can contain completed translation.
- On timeout or failure, publish final transcription with translation status, then support `translation.updated` after retry.
- Unit tests with a local mock HTTP server. No real vLLM requirement for CPU tests.
- Docker and operator documentation for local model download and vLLM launch.

Do not translate partial ASR. Do not expose reasoning. Run checks and update status.
## Mandatory staged GPU checkpoints

After the vLLM client, prompts, validators and mock tests pass locally, create only the next applicable manual action. Begin with environment inspection, then model download, vLLM launch, health check and two-direction translation tests as distinct actions. Stop after each action and wait for user feedback. Never operate the GPU server directly.
