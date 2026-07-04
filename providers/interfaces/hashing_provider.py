"""
Hashing Provider interface.

Defines the contract for password hashing and verification. The current
implementation uses Argon2id (Milestone 4). Argon2id is the winner of the
2015 Password Hashing Competition and is OWASP's recommended algorithm.

Why async?
  Argon2id is intentionally slow and memory-intensive — that's what makes
  it resistant to brute-force attacks. In a production async application,
  a slow CPU operation like password hashing WILL block the event loop
  and freeze all concurrent requests unless run in a thread pool executor.

  Making the interface async means all callers are already prepared for
  this async behavior, and implementations can use asyncio.run_in_executor()
  transparently.

Why not bcrypt?
  bcrypt is limited to 72-byte passwords (longer inputs are silently
  truncated), doesn't support memory-hardening, and has known timing
  vulnerabilities in some implementations. Argon2id is strictly better.
"""

from typing import Protocol, runtime_checkable


@runtime_checkable
class HashingProvider(Protocol):
    async def hash(self, plaintext: str) -> str:
        """
        Hash a plaintext password.

        Returns a self-contained string that includes the algorithm,
        parameters, salt, and hash. The format is opaque to callers —
        pass it directly to verify().

        Example output (Argon2id):
            $argon2id$v=19$m=65536,t=3,p=4$<salt>$<hash>
        """
        ...

    async def verify(self, plaintext: str, hashed: str) -> bool:
        """
        Verify a plaintext password against a stored hash.

        Returns True if the password matches, False otherwise.
        Never raises on a mismatch — raise only on internal errors.

        Implementations should use constant-time comparison to prevent
        timing attacks that could leak information about the hash.
        """
        ...

    async def needs_rehash(self, hashed: str) -> bool:
        """
        Return True if the hash should be upgraded.

        Called after a successful login to detect outdated hash parameters
        (e.g., increased memory cost). If True, rehash and update the
        stored hash transparently during this login.
        """
        ...
