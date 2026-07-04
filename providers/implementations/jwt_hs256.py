"""
HS256 JWT Provider.

Uses python-jose to sign and verify JWTs with HMAC-SHA256.
HS256 = shared-secret signing: the same key both creates and verifies tokens.
This is fine when only one service issues tokens (our auth service).

If you ever need multiple services to VERIFY tokens without being able to
ISSUE them, switch to RS256 (asymmetric). The RSA public key is distributed;
only the holder of the private key can sign. With HS256 any service holding
the secret can also issue tokens, which is a security risk in multi-service
architectures.

JWT claims we include:
  sub  — subject: the user's UUID as a string
  jti  — JWT ID: a fresh UUID per token, used for revocation
  exp  — expiry: Unix timestamp (seconds). jose enforces this automatically.
  iat  — issued at: Unix timestamp, useful for audit logs
  type — "access": distinguishes from refresh or email-verification tokens

The caller controls the payload; we only ADD claims, never overwrite sub.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from jose import JWTError, jwt

from core.config import get_settings
from core.exceptions import UnauthorizedError


class HS256JWTProvider:
    """
    Concrete JWT provider using HMAC-SHA256.

    Settings are read once at construction so the provider is independent
    of get_settings() during encode/decode hot paths.
    """

    _ALGORITHM = "HS256"

    def __init__(self) -> None:
        settings = get_settings()
        self._secret = settings.JWT_SECRET_KEY
        self._access_ttl = timedelta(minutes=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES)

    def encode(self, payload: dict[str, Any]) -> str:
        """
        Encode a payload into a signed JWT, adding standard claims.

        The caller provides at minimum {"sub": "<user_uuid>"}.
        We bolt on exp, iat, jti, and type automatically.

        Generating jti here (not in the caller) is intentional:
        the provider owns the token lifecycle. The caller doesn't
        need to know how revocation works — just that it does.
        """
        now = datetime.now(timezone.utc)
        claims = {
            "iat": now,
            "exp": now + self._access_ttl,
            "jti": str(uuid.uuid4()),
            "type": "access",
            **payload,  # caller's claims last so sub cannot be shadowed
        }
        return jwt.encode(claims, self._secret, algorithm=self._ALGORITHM)

    def decode(self, token: str) -> dict[str, Any]:
        """
        Decode and verify a JWT string.

        jose.jwt.decode() validates:
          - Signature (wrong secret → JWTError)
          - Expiry (past exp → ExpiredSignatureError, a JWTError subclass)
          - Algorithm (algorithm confusion attacks)

        We catch all JWTError and re-raise as UnauthorizedError so
        the caller never needs to import jose.
        """
        try:
            payload: dict[str, Any] = jwt.decode(
                token,
                self._secret,
                algorithms=[self._ALGORITHM],
            )
        except JWTError as exc:
            raise UnauthorizedError(f"Invalid or expired token: {exc}") from exc

        return payload
