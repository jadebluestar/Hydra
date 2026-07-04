from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from utils.slugify import is_valid_slug


class CreateProjectRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    slug: str | None = Field(default=None)
    description: str | None = Field(default=None, max_length=2000)

    @field_validator("slug")
    @classmethod
    def slug_must_be_valid(cls, v: str | None) -> str | None:
        if v is not None and not is_valid_slug(v):
            raise ValueError("Slug must be 3-63 characters, lowercase alphanumeric and hyphens")
        return v


class UpdateProjectRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=2000)


class ProjectResponse(BaseModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    name: str
    slug: str
    description: str | None
    created_at: datetime

    model_config = {"from_attributes": True}
