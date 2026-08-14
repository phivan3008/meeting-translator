# Phase 01: Contracts and Protocol

Implement the versioned protocol from `docs/PROTOCOL.md`.

Required outcomes:

- Pydantic schemas for all JSON client and server messages.
- Enums for event types, languages, stream sources, final reasons, translation statuses and typed error codes.
- Binary audio header encoder and decoder using the documented 24-byte big-endian layout.
- Packet validation for version, payload size, stream number, declared length and PCM alignment.
- Sequence tracking with duplicate detection and last-contiguous acknowledgement calculation.
- Protocol serialization helpers independent of FastAPI and PySide6.
- Unit tests and boundary/fuzz-like tests for malformed packets.
- Contract examples remain aligned with documentation.

Do not yet implement live WebSocket networking.

Run all quality checks and update `IMPLEMENTATION_STATUS.md`.
