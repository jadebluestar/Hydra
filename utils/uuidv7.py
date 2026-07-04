"""
UUIDv7 generator.

UUIDv7 (RFC 9562) is a time-ordered UUID standard. Unlike UUID4 (random),
UUIDv7 encodes a Unix millisecond timestamp in its top 48 bits, making new
UUIDs sort after old ones.

Why this matters for databases:
  - PostgreSQL (and most databases) store primary keys in B-tree indexes.
  - B-trees stay balanced when new keys are inserted near the end — like
    auto-increment integers or time-ordered UUIDs.
  - Random UUID4s scatter inserts across the entire tree, causing frequent
    page splits, index bloat, and slower writes at scale.
  - UUIDv7 gives you the uniqueness of a UUID with the insert performance of
    an integer sequence.

Python 3.13 does not include a native uuid7() — that arrives in 3.14.
This implementation follows RFC 9562 Section 5.7:

    0                   1                   2                   3
    0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1
   +-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
   |                           unix_ts_ms                          |
   +-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
   |          unix_ts_ms           |  ver  |       rand_a          |
   +-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
   |var|                        rand_b                             |
   +-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
   |                            rand_b                             |
   +-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+

  unix_ts_ms : 48 bits — milliseconds since Unix epoch
  ver        :  4 bits — 0x7
  rand_a     : 12 bits — random
  var        :  2 bits — 0b10 (RFC 4122 variant)
  rand_b     : 62 bits — random

Total: 128 bits.
"""

import os
import time
import uuid


def uuid7() -> uuid.UUID:
    ms = int(time.time() * 1000)

    # 10 random bytes = 80 bits; we need 12 + 62 = 74 usable bits
    rand = int.from_bytes(os.urandom(10), "big")
    rand_a = (rand >> 62) & 0x0FFF       # top 12 bits
    rand_b = rand & 0x3FFFFFFFFFFFFFFF    # bottom 62 bits

    # High 64 bits: [48-bit timestamp][4-bit version=7][12-bit rand_a]
    high = ((ms & 0xFFFFFFFFFFFF) << 16) | (0x7 << 12) | rand_a

    # Low 64 bits: [2-bit variant=10][62-bit rand_b]
    low = (0b10 << 62) | rand_b

    return uuid.UUID(int=(high << 64) | low)
