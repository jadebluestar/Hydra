"""
API Key scope validation.

Scopes are the authorization model for gateway traffic. Each API key is
issued with a set of scopes. Each route requires a minimum scope. Before
proxying, the gateway checks that the required scope is present.

Scope expansion rules:
  - ADMIN implies all other scopes (a key with admin can do anything)
  - GATEWAY_WRITE implies GATEWAY_READ (write includes read)

These rules prevent needing to add GATEWAY_READ to every key that has
GATEWAY_WRITE. They mirror how OAuth scope hierarchies typically work.
"""

from domain.enums.scope import APIKeyScope


def has_scope(granted: list[str], required: APIKeyScope) -> bool:
    """
    Return True if the required scope is in the granted scopes,
    accounting for scope expansion rules.

    Args:
        granted:  List of scope strings from the API key record.
        required: The scope the gateway route demands.

    Examples:
        has_scope(["gateway:read"], APIKeyScope.GATEWAY_READ)   → True
        has_scope(["gateway:write"], APIKeyScope.GATEWAY_READ)  → True  (write ⊇ read)
        has_scope(["admin"], APIKeyScope.ANALYTICS_READ)        → True  (admin ⊇ all)
        has_scope(["gateway:read"], APIKeyScope.GATEWAY_WRITE)  → False
    """
    scope_set = set(granted)

    # Admin overrides everything
    if APIKeyScope.ADMIN in scope_set:
        return True

    # gateway:write implies gateway:read
    if required == APIKeyScope.GATEWAY_READ and APIKeyScope.GATEWAY_WRITE in scope_set:
        return True

    return required in scope_set


def validate_requested_scopes(requested: list[str]) -> list[str]:
    """
    Validate a list of scope strings against the known scope enum.

    Raises ValueError for any unrecognized scope string. Called when
    creating or updating an API key to reject typos early.

    Returns the validated list (same values, type confirmed).
    """
    valid_values = {s.value for s in APIKeyScope}
    invalid = [s for s in requested if s not in valid_values]

    if invalid:
        raise ValueError(f"Unrecognized scope(s): {invalid}. Valid scopes: {sorted(valid_values)}")

    return requested
