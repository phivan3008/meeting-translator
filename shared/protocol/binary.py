"""Binary audio frame header codec and packet validation.

Header layout (24 bytes, big-endian / network byte order), per
``docs/PROTOCOL.md``::

    Offset  Size  Field
    0       1     protocol_version uint8
    1       1     stream_number uint8
    2       2     flags uint16
    4       8     sequence_number uint64
    12      8     client_timestamp_ms uint64
    20      4     payload_length uint32
    24      N     PCM payload (S16LE, mono, 16 kHz)

The payload must be PCM S16LE, so its length must be a multiple of 2 bytes.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from enum import IntFlag

from shared.protocol.enums import PROTOCOL_VERSION

# ">" = big-endian; B=uint8, H=uint16, Q=uint64, I=uint32.
HEADER_FORMAT = ">BBHQQI"
HEADER_SIZE = struct.calcsize(HEADER_FORMAT)  # 24

# Unsigned integer bounds for range validation.
_UINT8_MAX = 0xFF
_UINT16_MAX = 0xFFFF
_UINT32_MAX = 0xFFFFFFFF
_UINT64_MAX = 0xFFFFFFFFFFFFFFFF

# Bytes per PCM S16LE sample (mono).
_BYTES_PER_SAMPLE = 2


class AudioFlags(IntFlag):
    """Bit flags carried in the header ``flags`` field."""

    NONE = 0
    SILENCE = 1 << 0
    LAST_IN_UTTERANCE = 1 << 1
    KEEPALIVE = 1 << 2


class ProtocolError(Exception):
    """Base class for protocol-level errors."""


class PacketValidationError(ProtocolError):
    """Raised when a binary packet or header fails validation."""


@dataclass(frozen=True)
class AudioFrameHeader:
    """Decoded binary audio frame header."""

    protocol_version: int
    stream_number: int
    flags: int
    sequence_number: int
    client_timestamp_ms: int
    payload_length: int

    def encode(self) -> bytes:
        """Encode this header to its 24-byte binary form."""
        self._validate_ranges()
        return struct.pack(
            HEADER_FORMAT,
            self.protocol_version,
            self.stream_number,
            self.flags,
            self.sequence_number,
            self.client_timestamp_ms,
            self.payload_length,
        )

    def _validate_ranges(self) -> None:
        checks = (
            ("protocol_version", self.protocol_version, _UINT8_MAX),
            ("stream_number", self.stream_number, _UINT8_MAX),
            ("flags", self.flags, _UINT16_MAX),
            ("sequence_number", self.sequence_number, _UINT64_MAX),
            ("client_timestamp_ms", self.client_timestamp_ms, _UINT64_MAX),
            ("payload_length", self.payload_length, _UINT32_MAX),
        )
        for name, value, maximum in checks:
            if not isinstance(value, int) or value < 0 or value > maximum:
                raise PacketValidationError(f"{name} out of range for uint field: {value!r}")

    @classmethod
    def decode(cls, data: bytes) -> AudioFrameHeader:
        """Decode a 24-byte header. ``data`` may be exactly the header bytes."""
        if len(data) < HEADER_SIZE:
            raise PacketValidationError(f"header requires {HEADER_SIZE} bytes, got {len(data)}")
        (
            protocol_version,
            stream_number,
            flags,
            sequence_number,
            client_timestamp_ms,
            payload_length,
        ) = struct.unpack(HEADER_FORMAT, data[:HEADER_SIZE])
        return cls(
            protocol_version=protocol_version,
            stream_number=stream_number,
            flags=flags,
            sequence_number=sequence_number,
            client_timestamp_ms=client_timestamp_ms,
            payload_length=payload_length,
        )


def validate_header(
    header: AudioFrameHeader,
    *,
    max_payload_bytes: int,
    expected_version: int = PROTOCOL_VERSION,
) -> None:
    """Validate a decoded header before allocating/reading the payload.

    Raises :class:`PacketValidationError` on any violation. This is intended to
    run against the header alone so oversized declared payloads can be rejected
    before allocation.
    """
    if header.protocol_version != expected_version:
        raise PacketValidationError(f"unsupported protocol_version {header.protocol_version}")
    if header.stream_number < 1:
        raise PacketValidationError("stream_number must be >= 1")
    if header.payload_length > max_payload_bytes:
        raise PacketValidationError(
            f"payload_length {header.payload_length} exceeds limit {max_payload_bytes}"
        )
    if header.payload_length % _BYTES_PER_SAMPLE != 0:
        raise PacketValidationError("payload_length must be a multiple of 2 (PCM S16LE alignment)")


def encode_packet(
    *,
    stream_number: int,
    sequence_number: int,
    client_timestamp_ms: int,
    payload: bytes,
    flags: int = AudioFlags.NONE,
    protocol_version: int = PROTOCOL_VERSION,
) -> bytes:
    """Encode a full binary packet (header + payload).

    The payload must be PCM S16LE (length a multiple of 2 bytes).
    """
    if len(payload) % _BYTES_PER_SAMPLE != 0:
        raise PacketValidationError("payload length must be a multiple of 2 (PCM S16LE alignment)")
    header = AudioFrameHeader(
        protocol_version=protocol_version,
        stream_number=stream_number,
        flags=int(flags),
        sequence_number=sequence_number,
        client_timestamp_ms=client_timestamp_ms,
        payload_length=len(payload),
    )
    return header.encode() + payload


def decode_packet(
    data: bytes,
    *,
    max_payload_bytes: int,
    expected_version: int = PROTOCOL_VERSION,
) -> tuple[AudioFrameHeader, bytes]:
    """Decode and validate a full binary packet.

    Returns the decoded header and payload bytes. Raises
    :class:`PacketValidationError` for truncated, oversized, mismatched-length
    or misaligned packets, or an unsupported version.
    """
    if len(data) < HEADER_SIZE:
        raise PacketValidationError(f"packet shorter than header ({len(data)} < {HEADER_SIZE})")
    header = AudioFrameHeader.decode(data)
    # Validate the header (version, stream, declared size, alignment) before
    # trusting the declared payload length.
    validate_header(
        header,
        max_payload_bytes=max_payload_bytes,
        expected_version=expected_version,
    )
    payload = data[HEADER_SIZE:]
    if len(payload) != header.payload_length:
        raise PacketValidationError(
            f"declared payload_length {header.payload_length} != actual {len(payload)}"
        )
    return header, payload
