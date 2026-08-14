# Phase 06: Partial Whisper ASR and Stable Prefix

Add streaming partial transcription without weakening final ASR.

Required outcomes:

- Per-utterance periodic decode scheduler, default 500 ms.
- Sliding audio window with configurable overlap.
- Stable-prefix/local-agreement component independent of Whisper.
- Committed/stable and unstable text state.
- Strictly increasing revisions.
- `transcription.partial` publication.
- Protection against duplicate committed text, regressing revisions and stale decode results.
- Fair scheduling across active streams.
- Tests for Japanese strings, Vietnamese strings, punctuation variation and hypothesis corrections.
- Final reconciliation remains authoritative.

Run checks and update status.
