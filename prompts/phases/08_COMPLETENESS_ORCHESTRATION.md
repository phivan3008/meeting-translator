# Phase 08: Completeness and Finalization Orchestration

Implement the full utterance decision pipeline.

Required outcomes:

- Deterministic heuristic checker for punctuation, stable duration, unstable tail and configurable language-specific ending signals.
- Soft silence triggers a decision, not automatic blocking.
- Hard silence, maximum utterance, client flush, session end and device reconfiguration force finalization.
- Optional low-priority Qwen completeness JSON request only for ambiguous soft-silence cases.
- Strict short timeout and JSON validation.
- Skip completeness under queue pressure.
- Timeout, invalid output or overload produce `unknown` and use deterministic fallback.
- Race-safe transition from speaking to finalizing so one utterance cannot finalize twice.
- Full orchestrator: VAD -> partial ASR -> final ASR -> translation -> final event.
- Integration tests for pause-resume, semantic completion, hard silence, timeout and concurrent streams.

Run checks and update status.
