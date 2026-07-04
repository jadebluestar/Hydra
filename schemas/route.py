from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from domain.enums.scope import APIKeyScope
from domain.value_objects.route_path import RoutePath

_VALID_METHODS = frozenset({"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"})
_VALID_SCOPES = frozenset(s.value for s in APIKeyScope)


class CreateRouteRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    path_prefix: str
    upstream_id: uuid.UUID
    methods: list[str] = Field(default_factory=list)
    required_scope: str | None = None
    strip_prefix: bool = True
    rate_limit_rpm: int | None = Field(default=None, ge=1)
    is_active: bool = True

    @field_validator("path_prefix")
    @classmethod
    def validate_path(cls, v: str) -> str:
        return RoutePath(v).value

    @field_validator("methods")
    @classmethod
    def validate_methods(cls, v: list[str]) -> list[str]:
        upper = [m.upper() for m in v]
        invalid = set(upper) - _VALID_METHODS
        if invalid:
            raise ValueError(f"Invalid HTTP methods: {sorted(invalid)}")
        return upper

    @field_validator("required_scope")
    @classmethod
    def validate_scope(cls, v: str | None) -> str | None:
        if v is None:
            return None
        if v not in _VALID_SCOPES:
            raise ValueError(f"Invalid scope {v!r}. Valid: {sorted(_VALID_SCOPES)}")
        return v


class UpdateRouteRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    path_prefix: str | None = None
    upstream_id: uuid.UUID | None = None
    methods: list[str] | None = None
    required_scope: str | None = None
    strip_prefix: bool | None = None
    rate_limit_rpm: int | None = Field(default=None, ge=1)
    is_active: bool | None = None

    @field_validator("path_prefix")
    @classmethod
    def validate_path(cls, v: str | None) -> str | None:
        if v is None:
            return None
        return RoutePath(v).value

    @field_validator("methods")
    @classmethod
    def validate_methods(cls, v: list[str] | None) -> list[str] | None:
        if v is None:
            return None
        upper = [m.upper() for m in v]
        invalid = set(upper) - _VALID_METHODS
        if invalid:
            raise ValueError(f"Invalid HTTP methods: {sorted(invalid)}")
        return upper

    @field_validator("required_scope")
    @classmethod
    def validate_scope(cls, v: str | None) -> str | None:
        if v is None:
            return None
        if v not in _VALID_SCOPES:
            raise ValueError(f"Invalid scope {v!r}. Valid: {sorted(_VALID_SCOPES)}")
        return v


class RouteResponse(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    upstream_id: uuid.UUID
    name: str
    path_prefix: str
    methods: list[str]
    required_scope: str | None
    strip_prefix: bool
    rate_limit_rpm: int | None
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
