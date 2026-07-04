from __future__ import annotations

import uuid
from datetime import datetime
from urllib.parse import urlparse

from pydantic import BaseModel, Field, field_validator


class CreateUpstreamRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    base_url: str = Field(min_length=1, max_length=2048)
    timeout_seconds: int = Field(default=30, ge=1, le=300)
    retries: int = Field(default=3, ge=0, le=10)

    @field_validator("base_url")
    @classmethod
    def validate_base_url(cls, v: str) -> str:
        parsed = urlparse(v)
        if parsed.scheme not in ("http", "https"):
            raise ValueError("base_url must use http:// or https://")
        if not parsed.netloc:
            raise ValueError("base_url must include a hostname")
        return v.rstrip("/")


class UpdateUpstreamRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    base_url: str | None = Field(default=None, min_length=1, max_length=2048)
    timeout_seconds: int | None = Field(default=None, ge=1, le=300)
    retries: int | None = Field(default=None, ge=0, le=10)

    @field_validator("base_url")
    @classmethod
    def validate_base_url(cls, v: str | None) -> str | None:
        if v is None:
            return None
        parsed = urlparse(v)
        if parsed.scheme not in ("http", "https"):
            raise ValueError("base_url must use http:// or https://")
        if not parsed.netloc:
            raise ValueError("base_url must include a hostname")
        return v.rstrip("/")


class UpstreamResponse(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    name: str
    base_url: str
    timeout_seconds: int
    retries: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
