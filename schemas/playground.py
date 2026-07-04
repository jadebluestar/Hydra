"""
Schemas for the request playground (the Postman-like "try it" console).

The playground executes arbitrary HTTP requests on behalf of an authenticated
developer, server-side, so the browser never has to fight CORS to hit
third-party or internal upstreams.
"""

from __future__ import annotations

from pydantic import BaseModel, Field, HttpUrl


class PlaygroundRequest(BaseModel):
    method: str = Field(pattern="^(GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS)$")
    url: HttpUrl
    headers: dict[str, str] = Field(default_factory=dict)
    query_params: dict[str, str] = Field(default_factory=dict)
    body: str | None = None
    timeout_seconds: int = Field(default=30, ge=1, le=120)


class PlaygroundResponse(BaseModel):
    status_code: int
    headers: dict[str, str]
    body: str
    elapsed_ms: int
    size_bytes: int
