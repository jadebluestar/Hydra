"""
API key generation and verification utilities.

Key format:  hk_{env}_{32 random hex chars}
Examples:    hk_live_a3f8c2b1e9d4a7f0c5b8e2d1a4f7c0b3
             hk_test_00ff11aa22bb33cc44dd55ee66ff7700

Why SHA-256 (not Argon2)?
  API keys contain 128 bits of cryptographic randomness. Brute-forcing 2^128
  possibilities is computationally infeasible regardless of hash speed — even
  SHA-1 would be safe here. SHA-256 gives us microsecond verification vs.
  Argon2's intentional 80ms delay.

  Argon2 is for passwords (low-entropy, human-chosen secrets). SHA-256 is for
  high-entropy random tokens. This is the approach used by Stripe, GitHub, and
  Twilio for their API keys.

Prefix lookup:
  The gateway receives the full key as a Bearer token. Instead of hashing and
  doing a full table scan, we extract the prefix and use the indexed `key_prefix`
  column to narrow to a tiny candidate set, then do an exact SHA-256 comparison.
"""

from __future__ import annotations

import hashlib
import secrets

# Number of prefix characters stored and indexed for lookup.
# "hk_live_" = 8 chars + 8 random chars = 16 chars total.
# 8 random hex chars = 32 bits of prefix entropy → negligible collision probability
# among typical API key counts.
KEY_PREFIX_LENGTH = 16


def generate_api_key(*, env: str = "live") -> tuple[str, str, str]:
    """
    Generate a new API key.

    Returns:
        (full_key, key_prefix, key_hash)

        full_key:   The complete key string. Return this to the user ONCE.
                    It is never stored — only the hash is.
        key_prefix: First KEY_PREFIX_LENGTH chars. Stored in DB for prefix lookup.
        key_hash:   SHA-256 hex digest of the full key. Stored in DB for verification.
    """
    random_part = secrets.token_hex(16)  # 32 hex chars = 128 bits
    full_key = f"hk_{env}_{random_part}"
    key_prefix = full_key[:KEY_PREFIX_LENGTH]
    key_hash = _hash_key(full_key)
    return full_key, key_prefix, key_hash


def _hash_key(key: str) -> str:
    """Compute the SHA-256 hex digest of an API key string."""
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def verify_key(raw_key: str, stored_hash: str) -> bool:
    """
    Return True if the raw key matches the stored SHA-256 hash.

    Uses secrets.compare_digest for constant-time comparison to prevent
    timing attacks. Even though the full key must be guessed (not the hash),
    constant-time comparison is cheap insurance.
    """
    computed = _hash_key(raw_key)
    return secrets.compare_digest(computed, stored_hash)


def extract_prefix(raw_key: str) -> str:
    """Extract the prefix used for DB lookup from a raw key string."""
    return raw_key[:KEY_PREFIX_LENGTH]
