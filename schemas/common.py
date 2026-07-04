"""
Shared Pydantic schemas used across multiple endpoints.
"""

from pydantic import BaseModel


class HealthResponse(BaseModel):
    status: str
    version: str
    environment: str


class ReadinessCheck(BaseModel):
    status: str
    checks: dict[str, str]


class LivenessResponse(BaseModel):
    status: str


class ErrorResponse(BaseModel):
    """Standard error envelope returned by all exception handlers."""

    error: str
    message: str
    details: dict[str, object] = {}


class PaginationMeta(BaseModel):
    total: int
    page: int
    per_page: int
    pages: int


class PaginatedResponse(BaseModel):
    """
    Generic paginated wrapper.

    Usage:
        class UserListResponse(PaginatedResponse):
            items: list[UserResponse]
    """

    meta: PaginationMeta
