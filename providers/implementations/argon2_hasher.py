"""
Argon2id Password Hasher.

Argon2id won the 2015 Password Hashing Competition. OWASP recommends it
over bcrypt and PBKDF2 for all new systems. The "id" variant combines:
  - Argon2i (data-independent, side-channel resistant)
  - Argon2d (GPU/ASIC resistant via data-dependent memory access)

Parameters (OWASP minimums as of 2024):
  memory_cost = 64 MB  — each hash consumes 64 MB of RAM
  time_cost   = 3      — 3 passes over that memory
  parallelism = 4      — uses 4 CPU threads

Why does this make brute-force hard?
  A GPU can check billions of MD5 hashes/second because MD5 is cheap.
  Argon2id forces the attacker to use 64 MB of RAM per guess — GPUs have
  limited RAM bandwidth relative to compute. At these parameters, a
  top-tier GPU cluster can check maybe ~1000 guesses/second vs. 10^9 for MD5.

Why async?
  ph.hash() takes ~80ms on typical hardware. If you call it on the event loop
  thread, that thread is blocked and serves zero requests for 80ms per login.
  asyncio.to_thread() offloads it to a thread pool thread so the event loop
  stays free to serve other requests.
"""

from __future__ import annotations

import asyncio
from functools import partial

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError


class Argon2Hasher:
    """
    Concrete password hasher using Argon2id, offloaded to a thread pool.
    """

    def __init__(
        self,
        *,
        time_cost: int = 3,
        memory_cost: int = 65536,  # 64 MB in KiB
        parallelism: int = 4,
    ) -> None:
        self._ph = PasswordHasher(
            time_cost=time_cost,
            memory_cost=memory_cost,
            parallelism=parallelism,
        )

    async def hash(self, plaintext: str) -> str:
        """
        Hash a plaintext password.

        The returned string is self-contained: it embeds the algorithm,
        parameters, and salt. Example:
            $argon2id$v=19$m=65536,t=3,p=4$<salt>$<hash>

        This means you can change hash parameters in the future and still
        verify old passwords (the old params are in the stored string).
        """
        # partial() creates a callable with pre-filled args for to_thread()
        return await asyncio.to_thread(partial(self._ph.hash, plaintext))

    async def verify(self, plaintext: str, hashed: str) -> bool:
        """
        Verify a plaintext against a stored Argon2id hash.

        Returns False on mismatch — never raises. Callers check the bool.

        Uses constant-time comparison internally (argon2-cffi handles this),
        so the response time does not leak information about how close the
        guess was.
        """

        def _verify() -> bool:
            try:
                return self._ph.verify(hashed, plaintext)
            except VerifyMismatchError:
                return False

        return await asyncio.to_thread(_verify)

    async def needs_rehash(self, hashed: str) -> bool:
        """
        Check whether the hash was created with outdated parameters.

        Call this after a successful verify(). If True, re-hash the plaintext
        (which you have because the user just logged in) and update the DB.
        This upgrades all user passwords transparently as they log in.

        Example:
            if await hasher.verify(password, stored_hash):
                if await hasher.needs_rehash(stored_hash):
                    new_hash = await hasher.hash(password)
                    await user_repo.update_password_hash(user.id, new_hash)
        """
        return await asyncio.to_thread(partial(self._ph.check_needs_rehash, hashed))
