from __future__ import annotations

import struct
import zlib
from enum import IntEnum

import numpy as np

MAGIC = 0x534C
VERSION = 2
HEADER = struct.Struct("<HBBIIBH")
CRC = struct.Struct("<I")


class MessageType(IntEnum):
    HELLO = 1
    FRAME = 2
    PING = 4


def cobs_encode(data: bytes) -> bytes:
    output = bytearray([0])
    code_index = 0
    code = 1
    for byte in data:
        if byte == 0:
            output[code_index] = code
            code_index = len(output)
            output.append(0)
            code = 1
        else:
            output.append(byte)
            code += 1
            if code == 0xFF:
                output[code_index] = code
                code_index = len(output)
                output.append(0)
                code = 1
    output[code_index] = code
    return bytes(output)


def cobs_decode(data: bytes) -> bytes:
    if not data:
        raise ValueError("empty COBS payload")
    output = bytearray()
    index = 0
    while index < len(data):
        code = data[index]
        if code == 0:
            raise ValueError("zero byte inside COBS payload")
        index += 1
        end = index + code - 1
        if end > len(data):
            raise ValueError("truncated COBS payload")
        output.extend(data[index:end])
        index = end
        if code != 0xFF and index < len(data):
            output.append(0)
    return bytes(output)


def _packet(message_type: MessageType, sequence: int, delay_us: int,
            strips: int, leds: int, payload: bytes = b"") -> bytes:
    body = HEADER.pack(MAGIC, VERSION, message_type, sequence, delay_us, strips, leds) + payload
    body += CRC.pack(zlib.crc32(body) & 0xFFFFFFFF)
    return cobs_encode(body) + b"\x00"


def hello_packet(sequence: int = 0) -> bytes:
    return _packet(MessageType.HELLO, sequence, 0, 0, 0)


def ping_packet(sequence: int) -> bytes:
    return _packet(MessageType.PING, sequence, 0, 0, 0)


def frame_packet(sequence: int, presentation_delay_us: int, frame: np.ndarray) -> bytes:
    pixels = np.asarray(frame, dtype=np.uint8)
    if pixels.ndim != 3 or pixels.shape[2] != 3:
        raise ValueError("frame must have shape (strips, leds, 3)")
    strips, leds, _ = pixels.shape
    return _packet(MessageType.FRAME, sequence, presentation_delay_us,
                   strips, leds, pixels.tobytes(order="C"))


def decode_packet(encoded_with_delimiter: bytes) -> tuple[MessageType, int, int, int, int, bytes]:
    if not encoded_with_delimiter.endswith(b"\x00"):
        raise ValueError("missing packet terminator")
    encoded = encoded_with_delimiter[:-1]
    body = cobs_decode(encoded)
    if len(body) < HEADER.size + CRC.size:
        raise ValueError("packet too short")
    content, stored_crc = body[:-CRC.size], CRC.unpack(body[-CRC.size:])[0]
    if zlib.crc32(content) & 0xFFFFFFFF != stored_crc:
        raise ValueError("CRC mismatch")
    magic, version, kind, sequence, delay_us, strips, leds = HEADER.unpack(content[:HEADER.size])
    if magic != MAGIC or version != VERSION:
        raise ValueError("unsupported protocol")
    return MessageType(kind), sequence, delay_us, strips, leds, content[HEADER.size:]
