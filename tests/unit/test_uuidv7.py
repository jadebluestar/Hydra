"""
Unit tests for the UUIDv7 generator.

These run with zero infrastructure — no database, no Redis, no HTTP.
"""

import time
import uuid

from utils.uuidv7 import uuid7


def test_uuid7_returns_uuid_instance() -> None:
    result = uuid7()
    assert isinstance(result, uuid.UUID)


def test_uuid7_version_is_7() -> None:
    result = uuid7()
    assert result.version == 7


def test_uuid7_is_time_ordered() -> None:
    # UUIDs generated later must sort after UUIDs generated earlier.
    # We generate two with a tiny sleep to guarantee different milliseconds.
    first = uuid7()
    time.sleep(0.002)  # 2ms — enough to advance the timestamp
    second = uuid7()
    assert str(first) < str(second)


def test_uuid7_uniqueness() -> None:
    ids = {uuid7() for _ in range(1000)}
    assert len(ids) == 1000


def test_uuid7_variant_bits() -> None:
    # RFC 4122 / RFC 9562 variant: top two bits of octet 8 must be 0b10
    result = uuid7()
    # uuid.UUID stores the int as a 128-bit value.
    # Bits 64-65 (from the left) are the variant bits.
    variant_bits = (result.int >> 62) & 0b11
    assert variant_bits == 0b10
