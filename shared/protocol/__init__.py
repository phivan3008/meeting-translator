"""Versioned wire protocol for the meeting translator.

This package implements the contracts defined in ``docs/PROTOCOL.md``:

- :mod:`shared.protocol.enums`: event types, languages, sources, final reasons,
  translation statuses and typed error codes.
- :mod:`shared.protocol.messages`: Pydantic schemas for JSON control/result
  messages.
- :mod:`shared.protocol.binary`: encoder/decoder and validation for the 24-byte
  big-endian binary audio frame header.
- :mod:`shared.protocol.sequence`: per-stream sequence tracking with duplicate
  detection and last-contiguous acknowledgement.

The package is independent of FastAPI, PySide6, GPU and audio libraries.
"""

from __future__ import annotations

from shared.protocol.binary import (
    HEADER_FORMAT,
    HEADER_SIZE,
    AudioFlags,
    AudioFrameHeader,
    PacketValidationError,
    ProtocolError,
    decode_packet,
    encode_packet,
    validate_header,
)
from shared.protocol.enums import (
    PROTOCOL_VERSION,
    Encoding,
    ErrorCode,
    EventType,
    FinalReason,
    Language,
    StreamSource,
    TranslationStatus,
)
from shared.protocol.messages import (
    AudioAck,
    ErrorEvent,
    LatencyInfo,
    SessionStart,
    StreamConfig,
    TranscriptionPartial,
    TranslationUpdated,
    UtteranceFinal,
)
from shared.protocol.sequence import ObserveResult, SequenceTracker

__all__ = [
    "PROTOCOL_VERSION",
    "HEADER_FORMAT",
    "HEADER_SIZE",
    "AudioFlags",
    "AudioFrameHeader",
    "PacketValidationError",
    "ProtocolError",
    "decode_packet",
    "encode_packet",
    "validate_header",
    "Encoding",
    "ErrorCode",
    "EventType",
    "FinalReason",
    "Language",
    "StreamSource",
    "TranslationStatus",
    "AudioAck",
    "ErrorEvent",
    "LatencyInfo",
    "SessionStart",
    "StreamConfig",
    "TranscriptionPartial",
    "TranslationUpdated",
    "UtteranceFinal",
    "ObserveResult",
    "SequenceTracker",
]
