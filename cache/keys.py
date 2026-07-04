"""
Centralized Redis key definitions.

Every Redis key in Hydra is constructed through a function in this module.
This prevents magic strings from scattering across the codebase and makes it
trivial to audit which keys exist, rename them, or add TTL documentation.

Namespace convention:  hydra:{subsystem}:{identifier}

Examples:
    hydra:rl:apikey:hk_live_abc123   → rate limit counter for an API key
    hydra:route:proj_uuid            → cached route config for a project
    hydra:perm:user_uuid:org_uuid    → cached RBAC role lookup
"""


def rate_limit_key(limit_type: str, identifier: str) -> str:
    """hydra:rl:{type}:{id}  —  sliding window sorted set"""
    return f"hydra:rl:{limit_type}:{identifier}"


def route_cache_key(project_id: str) -> str:
    """hydra:route:{project_id}  —  serialized route config for a project"""
    return f"hydra:route:{project_id}"


def api_key_cache_key(key_prefix: str) -> str:
    """hydra:apikey:{prefix}  —  cached API key metadata"""
    return f"hydra:apikey:{key_prefix}"


def permission_cache_key(user_id: str, org_id: str) -> str:
    """hydra:perm:{user_id}:{org_id}  —  cached role for a user in an org"""
    return f"hydra:perm:{user_id}:{org_id}"


def revoked_token_key(jti: str) -> str:
    """hydra:revoked:{jti}  —  revoked JWT allowlist entry"""
    return f"hydra:revoked:{jti}"


def cb_failure_key(upstream_id: str) -> str:
    """hydra:cb:{upstream_id}:failures  —  INCR failure counter (TTL = window_seconds)"""
    return f"hydra:cb:{upstream_id}:failures"


def cb_open_at_key(upstream_id: str) -> str:
    """hydra:cb:{upstream_id}:open_at  —  float timestamp; present means circuit is OPEN"""
    return f"hydra:cb:{upstream_id}:open_at"


def cb_probe_key(upstream_id: str) -> str:
    """hydra:cb:{upstream_id}:probe  —  NX flag; present means a HALF_OPEN probe is in flight"""
    return f"hydra:cb:{upstream_id}:probe"
