"""Tests for the binary audio frame codec, including boundary/fuzz cases."""

from __future__ import annotations

import os
import struct

import pytest

from shared.protocol.binary import (
    HEADER_FORMAT,
    HEADER_SIZE,
    AudioFlags,
    AudioFrameHeader,
    PacketValidationError,
    decode_packet,
    encode_packet,
    validate_header,
)

MAX_PACKET = 65536
# 20 ms of 16 kHz mono PCM S16LE = 640 bytes.
NORMAL_PAYLOAD = b"\x01\x02" * 320


def test_header_size_is_24() -> None:
    assert HEADER_SIZE == 24
    assert struct.calcsize(HEADER_FORMAT) == 24


def test_encode_decode_round_trip() -> None:
    packet = encode_packet(
        stream_number=2,
        sequence_number=18420,
        client_timestamp_ms=1_723_000_000_000,
        payload=NORMAL_PAYLOAD,
        flags=AudioFlags.SILENCE,
    )
    assert len(packet) == HEADER_SIZE + len(NORMAL_PAYLOAD)
    header, payload = decode_packet(packet, max_payload_bytes=MAX_PACKET)
    assert header.protocol_version == 1
    assert header.stream_number == 2
    assert header.sequence_number == 18420
    assert header.client_timestamp_ms == 1_723_000_000_000
    assert header.flags == int(AudioFlags.SILENCE)
    assert header.payload_length == len(NORMAL_PAYLOAD)
    assert payload == NORMAL_PAYLOAD


def test_big_endian_layout() -> None:
    packet = encode_packet(
        stream_number=1,
        sequence_number=1,
        client_timestamp_ms=0,
        payload=b"",
    )
    # protocol_version=1 at offset 0, stream_number=1 at offset 1.
    assert packet[0] == 1
    assert packet[1] == 1
    # sequence_number uint64 big-endian at offset 4.
    assert packet[4:12] == (1).to_bytes(8, "big")


def test_truncated_packet_rejected() -> None:
    packet = encode_packet(
        stream_number=1, sequence_number=1, client_timestamp_ms=0, payload=NORMAL_PAYLOAD
    )
    with pytest.raises(PacketValidationError):
        decode_packet(packet[:10], max_payload_bytes=MAX_PACKET)


def test_length_mismatch_rejected() -> None:
    packet = bytearray(
        encode_packet(
            stream_number=1, sequence_number=1, client_timestamp_ms=0, payload=NORMAL_PAYLOAD
        )
    )
    # Drop two payload bytes so actual length no longer matches declared length.
    truncated = bytes(packet[:-2])
    with pytest.raises(PacketValidationError):
        decode_packet(truncated, max_payload_bytes=MAX_PACKET)


def test_oversized_declared_payload_rejected_before_read() -> None:
    header = AudioFrameHeader(
        protocol_version=1,
        stream_number=1,
        flags=0,
        sequence_number=1,
        client_timestamp_ms=0,
        payload_length=MAX_PACKET + 2,
    )
    with pytest.raises(PacketValidationError):
        validate_header(header, max_payload_bytes=MAX_PACKET)


def test_unsupported_version_rejected() -> None:
    header = AudioFrameHeader(
        protocol_version=9,
        stream_number=1,
        flags=0,
        sequence_number=1,
        client_timestamp_ms=0,
        payload_length=0,
    )
    packet = header.encode()
    with pytest.raises(PacketValidationError):
        decode_packet(packet, max_payload_bytes=MAX_PACKET)


def test_odd_payload_length_rejected() -> None:
    # Craft a packet whose declared and actual payload length is odd (3 bytes).
    header = AudioFrameHeader(
        protocol_version=1,
        stream_number=1,
        flags=0,
        sequence_number=1,
        client_timestamp_ms=0,
        payload_length=3,
    )
    packet = header.encode() + b"\x01\x02\x03"
    with pytest.raises(PacketValidationError):
        decode_packet(packet, max_payload_bytes=MAX_PACKET)


def test_stream_number_zero_rejected() -> None:
    header = AudioFrameHeader(
        protocol_version=1,
        stream_number=0,
        flags=0,
        sequence_number=1,
        client_timestamp_ms=0,
        payload_length=0,
    )
    with pytest.raises(PacketValidationError):
        validate_header(header, max_payload_bytes=MAX_PACKET)


def test_encode_odd_payload_rejected() -> None:
    with pytest.raises(PacketValidationError):
        encode_packet(
            stream_number=1, sequence_number=1, client_timestamp_ms=0, payload=b"\x00\x01\x02"
        )


def test_field_out_of_range_rejected() -> None:
    header = AudioFrameHeader(
        protocol_version=1,
        stream_number=256,  # exceeds uint8
        flags=0,
        sequence_number=1,
        client_timestamp_ms=0,
        payload_length=0,
    )
    with pytest.raises(PacketValidationError):
        header.encode()


def test_fuzz_random_bytes_never_crash() -> None:
    # Random inputs must raise PacketValidationError, never an unhandled error.
    for _ in range(500):
        size = int.from_bytes(os.urandom(1), "big")
        data = os.urandom(size)
        try:
            decode_packet(data, max_payload_bytes=MAX_PACKET)
        except PacketValidationError:
            pass
