# Phase 02: Windows Audio Capture

Implement Windows audio capture with an interface that remains testable on Linux.

Required outcomes:

- Audio capture protocol/interface.
- PyAudioWPatch adapter imported as `pyaudiowpatch` only inside the Windows adapter.
- Microphone enumeration and capture.
- WASAPI loopback enumeration and capture.
- Independent capture contexts for microphone and loopback.
- Callback performs only timestamping, sequence assignment and bounded enqueue.
- Worker converts channel count and sample rate to mono 16 kHz PCM S16LE.
- 20 ms output frame packetization.
- Queue overflow counters and explicit drop policy.
- Device loss and reconfiguration signals.
- WAV diagnostic CLI for manual Windows verification.
- Fake audio backend and deterministic unit tests runnable on Linux.
- Windows-only integration tests marked `windows_audio` and documented manual commands.

Do not use sounddevice. Do not mix microphone and loopback.

Run all available checks and update `IMPLEMENTATION_STATUS.md` truthfully.
## Mandatory manual checkpoint

After local fake-backend tests pass, create a `WINDOWS-AUDIO-001` action with exact Windows commands for device enumeration and short microphone/loopback WAV capture. Stop and wait for the user. Do not mark hardware verification complete before receiving results.
