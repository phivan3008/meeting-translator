# Protocol Specification

## General rules

- Protocol version starts at `1`.
- Control and result messages are UTF-8 JSON text frames.
- Audio is sent as binary WebSocket frames.
- Integer fields in the binary header use network byte order, big-endian.
- Server limits must reject oversized payloads before allocation where practical.
- Every event includes `protocol_version`, `type`, `session_id` and a UTC timestamp.

## Session start

```json
{
  "protocol_version": 1,
  "type": "session.start",
  "session_id": "meeting-20260810-001",
  "client_id": "client-vn-01",
  "timestamp": "2026-08-10T03:45:00.000Z",
  "streams": [
    {
      "stream_number": 1,
      "stream_id": "mic-01",
      "source": "microphone",
      "source_language": "vi",
      "target_language": "ja",
      "sample_rate": 16000,
      "channels": 1,
      "encoding": "pcm_s16le"
    },
    {
      "stream_number": 2,
      "stream_id": "loopback-01",
      "source": "loopback",
      "source_language": "ja",
      "target_language": "vi",
      "sample_rate": 16000,
      "channels": 1,
      "encoding": "pcm_s16le"
    }
  ]
}
```

## Binary audio frame

Header layout:

```text
Offset  Size  Field
0       1     protocol_version uint8
1       1     stream_number uint8
2       2     flags uint16 big-endian
4       8     sequence_number uint64 big-endian
12      8     client_timestamp_ms uint64 big-endian
20      4     payload_length uint32 big-endian
24      N     PCM payload
```

Rules:

- Header size is 24 bytes.
- Payload must be PCM S16LE, mono, 16 kHz.
- Normal packet duration is 20 ms and payload is normally 640 bytes.
- Parser must verify actual payload length equals declared length.
- Duplicate sequence numbers are idempotently ignored.
- Small gaps may be represented as silence by policy; large gaps are reported.

## Audio acknowledgement

```json
{
  "protocol_version": 1,
  "type": "audio.ack",
  "session_id": "meeting-20260810-001",
  "stream_id": "loopback-01",
  "last_contiguous_sequence": 18420,
  "timestamp": "2026-08-10T03:45:05.123Z"
}
```

## Partial transcription

```json
{
  "protocol_version": 1,
  "type": "transcription.partial",
  "session_id": "meeting-20260810-001",
  "stream_id": "loopback-01",
  "utterance_id": "utt-00081",
  "revision": 5,
  "source_language": "ja",
  "stable_text": "来週のリリースについて",
  "unstable_text": "確認",
  "display_text": "来週のリリースについて確認",
  "start_ms": 128420,
  "end_ms": 130880,
  "timestamp": "2026-08-10T03:45:06.000Z"
}
```

Rules:

- Revision must strictly increase within an utterance.
- Client ignores revisions less than or equal to the currently applied revision.
- `display_text` is the normalized concatenation intended for simple clients.

## Final utterance

```json
{
  "protocol_version": 1,
  "type": "utterance.final",
  "session_id": "meeting-20260810-001",
  "stream_id": "loopback-01",
  "utterance_id": "utt-00081",
  "revision": 6,
  "source": "loopback",
  "source_language": "ja",
  "target_language": "vi",
  "transcription": "来週のリリースについて確認したいです。",
  "translation": "Tôi muốn xác nhận về đợt phát hành vào tuần tới.",
  "translation_status": "completed",
  "start_ms": 128420,
  "end_ms": 132700,
  "final_reason": "vad_hard_silence",
  "latency": {
    "asr_final_ms": 610,
    "translation_queue_ms": 25,
    "translation_ms": 420,
    "end_to_end_ms": 1375
  },
  "timestamp": "2026-08-10T03:45:07.000Z"
}
```

## Translation retry update

```json
{
  "protocol_version": 1,
  "type": "translation.updated",
  "session_id": "meeting-20260810-001",
  "stream_id": "loopback-01",
  "utterance_id": "utt-00081",
  "translation": "Tôi muốn xác nhận về đợt phát hành vào tuần tới.",
  "translation_status": "completed",
  "timestamp": "2026-08-10T03:45:08.000Z"
}
```

## Error event

```json
{
  "protocol_version": 1,
  "type": "error",
  "session_id": "meeting-20260810-001",
  "code": "TRANSLATION_TIMEOUT",
  "message": "Translation did not complete within the configured timeout.",
  "retryable": true,
  "utterance_id": "utt-00081",
  "timestamp": "2026-08-10T03:45:08.000Z"
}
```

## Required final reasons

- `vad_hard_silence`
- `semantic_complete`
- `max_utterance`
- `client_flush`
- `session_end`
- `device_reconfigured`

## Required translation statuses

- `pending`
- `completed`
- `retrying`
- `failed`
