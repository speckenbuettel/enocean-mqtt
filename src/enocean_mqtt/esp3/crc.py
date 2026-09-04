"""CRC-8 helpers for ESP3 frames."""

from __future__ import annotations


def crc8(data: bytes) -> int:
    """Return ESP3 CRC-8 for the supplied bytes."""

    crc = 0

    for byte in data:
        crc ^= byte

        for _ in range(8):
            if crc & 0x80:
                crc = ((crc << 1) ^ 0x07) & 0xFF
            else:
                crc = (crc << 1) & 0xFF

    return crc
