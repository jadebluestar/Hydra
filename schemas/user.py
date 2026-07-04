from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, EmailStr


class UserResponse(BaseModel):
    """Public user representation — never includes password_hash."""

    id: uuid.UUID
    email: EmailStr
    full_name: str | None
    is_active: bool
    is_email_verified: bool
    created_at: datetime

    model_config = {"from_attributes": True}
