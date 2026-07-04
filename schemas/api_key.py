from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from security.scopes import validate_requested_scopes


class CreateAPIKeyRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    scopes: list[str] = Field(default_factory=list)
    expires_at: datetime | None = None

    @field_validator("scopes")
    @classmethod
    def validate_scopes(cls, v: list[str]) -> list[str]:
        return validate_requested_scopes(v)


class APIKeyResponse(BaseModel):
    """Returned for list/get operations — never includes the plaintext key."""

    id: uuid.UUID
    name: str
    key_prefix: str
    scopes: list[str]
    is_active: bool
    is_revoked: bool
    expires_at: datetime | None
    last_used_at: datetime | None
    revoked_at: datetime | None
    created_at: datetime

    model_config = {"from_attributes": True}


class APIKeyCreatedResponse(APIKeyResponse):
    """
    Returned ONLY on key creation. Includes the full plaintext key.

    The `key` field is available exactly once. The user must copy it now —
    it cannot be recovered later because only the SHA-256 hash is stored.

    This pattern is identical to GitHub personal access tokens.
    """

    key: str
