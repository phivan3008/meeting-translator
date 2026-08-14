"""Protocol enumerations and constants.

Mirrors the required vocabularies in ``docs/PROTOCOL.md``. String enums are
used so values serialize directly to their documented wire form.
"""

from __future__ import annotations

from enum import StrEnum

# The protocol version starts at 1 (see docs/PROTOCOL.md).
PROTOCOL_VERSION = 1


class EventType(StrEnum):
    """Message ``type`` discriminator values."""

    SESSION_START = "session.start"
    AUDIO_ACK = "audio.ack"
    TRANSCRIPTION_PARTIAL = "transcription.partial"
    UTTERANCE_FINAL = "utterance.final"
    TRANSLATION_UPDATED = "translation.updated"
    ERROR = "error"


class Language(StrEnum):
    """Supported source/target languages for the Vi-Ja MVP."""

    VIETNAMESE = "vi"
    JAPANESE = "ja"


class StreamSource(StrEnum):
    """Audio stream source."""

    MICROPHONE = "microphone"
    LOOPBACK = "loopback"


class Encoding(StrEnum):
    """Supported PCM encoding."""

    PCM_S16LE = "pcm_s16le"


class FinalReason(StrEnum):
    """Reason an utterance was finalized (docs/PROTOCOL.md)."""

    VAD_HARD_SILENCE = "vad_hard_silence"
    SEMANTIC_COMPLETE = "semantic_complete"
    MAX_UTTERANCE = "max_utterance"
    CLIENT_FLUSH = "client_flush"
    SESSION_END = "session_end"
    DEVICE_RECONFIGURED = "device_reconfigured"


class TranslationStatus(StrEnum):
    """Translation lifecycle status (docs/PROTOCOL.md)."""

    PENDING = "pending"
    COMPLETED = "completed"
    RETRYING = "retrying"
    FAILED = "failed"


class ErrorCode(StrEnum):
    """Typed error codes for the ``error`` event."""

    PROTOCOL_VERSION_UNSUPPORTED = "PROTOCOL_VERSION_UNSUPPORTED"
    MALFORMED_MESSAGE = "MALFORMED_MESSAGE"
    MALFORMED_PACKET = "MALFORMED_PACKET"
    PAYLOAD_TOO_LARGE = "PAYLOAD_TOO_LARGE"
    INVALID_STREAM = "INVALID_STREAM"
    SEQUENCE_ERROR = "SEQUENCE_ERROR"
    AUTH_FAILED = "AUTH_FAILED"
    ASR_FAILED = "ASR_FAILED"
    TRANSLATION_TIMEOUT = "TRANSLATION_TIMEOUT"
    TRANSLATION_FAILED = "TRANSLATION_FAILED"
    OVERLOADED = "OVERLOADED"
    INTERNAL_ERROR = "INTERNAL_ERROR"
