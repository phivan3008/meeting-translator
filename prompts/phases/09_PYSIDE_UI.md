# Phase 09: PySide6 Client UI

Build the Windows desktop experience around the completed transport.

Required outcomes:

- Main window with connect/disconnect state.
- Microphone and loopback device selectors.
- Language mapping presets for Vietnamese-side and Japanese-side clients.
- Independent source enable/disable controls.
- Caption timeline keyed by utterance ID.
- Partial hint is gray; stable and unstable text are visually distinct.
- Newer revision replaces prior partial in place.
- Final transcription is bold and replaces partial.
- Translation is normal weight below transcription.
- Source, direction, timestamp, retry and failure state are visible.
- Thread-safe bridge from network worker to Qt signals.
- Settings persistence without secrets.
- UI state tests where practical plus view-model tests independent of Qt rendering.
- Accessibility-conscious font sizing and keyboard navigation.

Run Linux-compatible tests and document manual Windows UI verification. Update status.
