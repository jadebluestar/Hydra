"""
API Key scopes — the authorization model for gateway traffic.

Every API key carries a list of scopes. Every route requires a minimum scope.
Before proxying a request, the gateway plugin checks:

    required_scope ∈ key.scopes

This is structurally identical to OAuth 2.0 scopes. The colon-separated
format ("gateway:read") is the standard convention for hierarchical scopes
and is also used by GitHub, Stripe, and most modern API platforms.

Scope hierarchy (broadest to narrowest access):
    admin > keys:manage > gateway:write > gateway:read
    admin > analytics:read
"""

from enum import StrEnum


class APIKeyScope(StrEnum):
    # Proxy GET requests through this key
    GATEWAY_READ = "gateway:read"

    # Proxy all HTTP methods (GET, POST, PUT, PATCH, DELETE)
    GATEWAY_WRITE = "gateway:write"

    # Query analytics and logs endpoints
    ANALYTICS_READ = "analytics:read"

    # Create, rotate, and revoke API keys programmatically
    KEYS_MANAGE = "keys:manage"

    # Full access — reserved for internal tooling and superuser operations
    ADMIN = "admin"
