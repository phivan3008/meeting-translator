"""Pydantic schemas for JSON control and result messages.

All models are versioned and independent of FastAPI and PySide6. Timestamps are
UTC-aware ``datetime`` values and serialize to ISO-8601 with a ``Z`` suffix and
millisecond precision, matching ``docs/PROTOCOL.md``.
"""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, Field, field_serializer, field_validator

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

# Baseline audio format required by the protocol.
REQUIRED_SAMPLE_RATE = 16000
REQUIRED_CHANNELS = 1


def _iso_z(value: datetime) -> str:
    """Serialize a datetime to ISO-8601 UTC with millisecond precision + Z."""
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    value = value.astimezone(UTC)
    return value.strftime("%Y-%m-%dT%H:%M:%S.") + f"{value.microsecond // 1000:03d}Z"


class ProtocolModel(BaseModel):
    """Base model providing shared config and timestamp serialization."""

    model_config = ConfigDict(extra="forbid", use_enum_values=False)

    @field_serializer("timestamp", when_used="json", check_fields=False)
    def _serialize_timestamp(self, value: datetime) -> str:
        return _iso_z(value)


class StreamConfig(ProtocolModel):
    """Per-stream declaration in ``session.start``."""

    stream_number: int = Field(ge=1, le=255)
    stream_id: str = Field(min_length=1, max_length=128)
    source: StreamSource
    source_language: Language
    target_language: Language
    sample_rate: int = REQUIRED_SAMPLE_RATE
    channels: int = REQUIRED_CHANNELS
    encoding: Encoding = Encoding.PCM_S16LE

    @field_validator("sample_rate")
    @classmethod
    def _check_sample_rate(cls, value: int) -> int:
        if value != REQUIRED_SAMPLE_RATE:
            raise ValueError(f"sample_rate must be {REQUIRED_SAMPLE_RATE}")
        return value

    @field_validator("channels")
    @classmethod
    def _check_channels(cls, value: int) -> int:
        if value != REQUIRED_CHANNELS:
            raise ValueError("channels must be 1 (mono)")
        return value


class SessionStart(ProtocolModel):
    """Client-to-server session initialization."""

    protocol_version: int = PROTOCOL_VERSION
    type: EventType = EventType.SESSION_START
    session_id: str = Field(min_length=1, max_length=128)
    client_id: str = Field(min_length=1, max_length=128)
    timestamp: datetime
    streams: list[StreamConfig] = Field(min_length=1)

    @field_validator("type")
    @classmethod
    def _check_type(cls, value: EventType) -> EventType:
        if value is not EventType.SESSION_START:
            raise ValueError("type must be session.start")
        return value

    @field_validator("streams")
    @classmethod
    def _unique_streams(cls, value: list[StreamConfig]) -> list[StreamConfig]:
        numbers = [s.stream_number for s in value]
        ids = [s.stream_id for s in value]
        if len(set(numbers)) != len(numbers):
            raise ValueError("stream_number values must be unique")
        if len(set(ids)) != len(ids):
            raise ValueError("stream_id values must be unique")
        return value


class AudioAck(ProtocolModel):
    """Server acknowledgement of contiguous audio receipt."""

    protocol_version: int = PROTOCOL_VERSION
    type: EventType = EventType.AUDIO_ACK
    session_id: str
    stream_id: str
    last_contiguous_sequence: int = Field(ge=0)
    timestamp: datetime


class TranscriptionPartial(ProtocolModel):
    """In-progress transcription hint with stable/unstable segments."""

    protocol_version: int = PROTOCOL_VERSION
    type: EventType = EventType.TRANSCRIPTION_PARTIAL
    session_id: str
    stream_id: str
    utterance_id: str
    revision: int = Field(ge=0)
    source_language: Language
    stable_text: str
    unstable_text: str
    display_text: str
    start_ms: int = Field(ge=0)
    end_ms: int = Field(ge=0)
    timestamp: datetime

    @field_validator("end_ms")
    @classmethod
    def _end_after_start(cls, value: int, info: object) -> int:
        data = getattr(info, "data", {})
        start = data.get("start_ms")
        if start is not None and value < start:
            raise ValueError("end_ms must be >= start_ms")
        return value


class LatencyInfo(ProtocolModel):
    """Optional per-stage latency breakdown for a final utterance."""

    asr_final_ms: int | None = Field(default=None, ge=0)
    translation_queue_ms: int | None = Field(default=None, ge=0)
    translation_ms: int | None = Field(default=None, ge=0)
    end_to_end_ms: int | None = Field(default=None, ge=0)


class UtteranceFinal(ProtocolModel):
    """Final, authoritative transcription and translation for an utterance."""

    protocol_version: int = PROTOCOL_VERSION
    type: EventType = EventType.UTTERANCE_FINAL
    session_id: str
    stream_id: str
    utterance_id: str
    revision: int = Field(ge=0)
    source: StreamSource
    source_language: Language
    target_language: Language
    transcription: str
    translation: str | None = None
    translation_status: TranslationStatus
    start_ms: int = Field(ge=0)
    end_ms: int = Field(ge=0)
    final_reason: FinalReason
    latency: LatencyInfo | None = None
    timestamp: datetime

    @field_validator("end_ms")
    @classmethod
    def _end_after_start(cls, value: int, info: object) -> int:
        data = getattr(info, "data", {})
        start = data.get("start_ms")
        if start is not None and value < start:
            raise ValueError("end_ms must be >= start_ms")
        return value


class TranslationUpdated(ProtocolModel):
    """A later translation update (e.g. after a retry)."""

    protocol_version: int = PROTOCOL_VERSION
    type: EventType = EventType.TRANSLATION_UPDATED
    session_id: str
    stream_id: str
    utterance_id: str
    translation: str
    translation_status: TranslationStatus
    timestamp: datetime


class ErrorEvent(ProtocolModel):
    """A typed, optionally retryable error event."""

    protocol_version: int = PROTOCOL_VERSION
    type: EventType = EventType.ERROR
    session_id: str
    code: ErrorCode
    message: str
    retryable: bool = False
    utterance_id: str | None = None
    timestamp: datetime
