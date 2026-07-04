"""
JWT Provider interface.

Defines the contract for JWT operations. The current implementation is
HS256JWTProvider (Milestone 4). An RS256 provider can be added later
for asymmetric key signing — useful when multiple services need to
validate tokens without sharing the secret key.

JWT encode/decode are synchronous because they are pure CPU operations
(HMAC-SHA256 is fast) that never touch I/O.

Access tokens contain:
    sub  — subject (user UUID as string)
    jti  — JWT ID (UUID, used for revocation)
    exp  — expiry timestamp (Unix seconds)
    iat  — issued at timestamp (Unix seconds)
    type — "access" (distinguishes from future token types)
"""

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class JWTProvider(Protocol):
    """
    Interface for JWT access token operations.

    runtime_checkable allows isinstance() checks at test time:
        assert isinstance(concrete_impl, JWTProvider)

    Note: isinstance() only verifies method names exist, NOT signatures.
    Use mypy for full structural type checking.
    """

    def encode(self, payload: dict[str, Any]) -> str:
        """
        Encode a payload dict into a signed JWT string.

        The implementation is responsible for:
        - Adding 'exp' and 'iat' claims based on configured TTL
        - Adding 'jti' for revocation support
        - Signing with the configured algorithm and secret

        Args:
            payload: Claims to include. Must include 'sub' (subject).

        Returns:
            Signed JWT string.
        """
        ...

    def decode(self, token: str) -> dict[str, Any]:
        """
        Decode and verify a JWT string.

        The implementation must verify:
        - Signature validity
        - Token has not expired (exp claim)
        - Token uses the expected algorithm

        Args:
            token: Raw JWT string from Authorization header.

        Returns:
            Decoded payload dict.

        Raises:
            UnauthorizedError: If the token is invalid or expired.
        """
        ...
