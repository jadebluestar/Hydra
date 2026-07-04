from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, EmailStr, Field, field_validator

from domain.enums.role import Role
from utils.slugify import is_valid_slug


class CreateOrgRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    # Slug is optional — auto-generated from name if not provided.
    # If provided, must be lowercase alphanumeric with hyphens (3-63 chars).
    slug: str | None = Field(default=None)

    @field_validator("slug")
    @classmethod
    def slug_must_be_valid(cls, v: str | None) -> str | None:
        if v is not None and not is_valid_slug(v):
            raise ValueError(
                "Slug must be 3-63 characters, lowercase alphanumeric and hyphens, "
                "starting and ending with a letter or digit"
            )
        return v


class UpdateOrgRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)


class OrgResponse(BaseModel):
    id: uuid.UUID
    name: str
    slug: str
    plan: str
    created_at: datetime

    model_config = {"from_attributes": True}


class InviteMemberRequest(BaseModel):
    email: EmailStr
    role: str = Field(default="member")

    @field_validator("role")
    @classmethod
    def role_must_be_valid(cls, v: str) -> str:
        try:
            Role(v)
        except ValueError:
            valid = [r.value for r in Role]
            raise ValueError(f"Invalid role '{v}'. Must be one of: {valid}")
        return v


class UpdateMemberRoleRequest(BaseModel):
    role: str

    @field_validator("role")
    @classmethod
    def role_must_be_valid_and_not_owner(cls, v: str) -> str:
        try:
            role = Role(v)
        except ValueError:
            valid = [r.value for r in Role]
            raise ValueError(f"Invalid role '{v}'. Must be one of: {valid}")
        # OWNER can only be set via transfer_ownership, not a role update.
        if role == Role.OWNER:
            raise ValueError(
                "Cannot assign owner role via role update. Use transfer ownership."
            )
        return v


class MemberResponse(BaseModel):
    user_id: uuid.UUID
    email: str
    full_name: str | None
    role: str
    joined_at: datetime | None
    member_since: datetime
