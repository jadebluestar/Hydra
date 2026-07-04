"""
Sliding window rate limiter using Redis sorted sets.

Algorithm (Lua script — executes atomically):
  1. ZREMRANGEBYSCORE key -inf (now_ms - window_ms)  — evict expired entries
  2. ZCARD key                                        — count requests in window
  3. If count >= limit: return -1 (over limit, caller raises 429)
  4. ZADD key now_ms unique_member                    — record this request
  5. EXPIRE key ceil(window_ms/1000) + 1              — auto-cleanup
  6. Return new count

Why sorted set instead of INCR+EXPIRE (fixed window)?
  Fixed window has a boundary burst problem: a client can fire 2×limit requests
  by hammering the last seconds of window N and the first of window N+1.
  The sorted set gives us a true sliding window — the limit applies to
  "requests in the last 60 seconds," not "requests since :00 of the current minute."

Why Lua?
  ZREMRANGEBYSCORE → ZCARD → ZADD → EXPIRE must be atomic. Without Lua, two
  concurrent requests that both read count=limit-1 can both proceed, exceeding
  the limit. Redis executes Lua scripts as a single atomic unit.

Key format: hydra:rl:apikey:{api_key_id}:{route_id}
  Per-API-key per-route: the same key used on different routes has separate
  counters, which is the right granularity for route-level rate limits.
"""

from __future__ import annotations

import secrets
import time

from redis.asyncio import Redis

from cache.keys import rate_limit_key
from core.exceptions import RateLimitError

_WINDOW_MS = 60_000  # 1-minute sliding window for RPM limits

# Lua script: atomic sliding window check-and-record.
# KEYS[1]  = the sorted set key
# ARGV[1]  = limit (int) — max requests per window
# ARGV[2]  = now in milliseconds (int)
# ARGV[3]  = window size in milliseconds (int)
# ARGV[4]  = unique request id (prevents duplicate members in the sorted set)
# Returns: new count (>= 1), or -1 if the limit was already reached
_SLIDING_WINDOW_LUA = """
local key       = KEYS[1]
local limit     = tonumber(ARGV[1])
local now       = tonumber(ARGV[2])
local window_ms = tonumber(ARGV[3])
local req_id    = ARGV[4]
local cutoff    = now - window_ms

redis.call('ZREMRANGEBYSCORE', key, '-inf', cutoff)
local count = tonumber(redis.call('ZCARD', key))
if count >= limit then
    return -1
end
redis.call('ZADD', key, now, now .. ':' .. req_id)
redis.call('EXPIRE', key, math.ceil(window_ms / 1000) + 1)
return count + 1
"""


async def check_rate_limit(
    redis: Redis,  # type: ignore[type-arg]
    *,
    api_key_id: str,
    route_id: str,
    limit: int,
) -> None:
    """
    Verify the API key hasn't exceeded the route's rate limit.

    Raises RateLimitError (HTTP 429) if the sliding window is full.
    No-op if limit <= 0 (defensive guard; callers should check route_match.rate_limit_rpm).
    """
    if limit <= 0:
        return

    key = rate_limit_key("apikey", f"{api_key_id}:{route_id}")
    now_ms = int(time.time() * 1000)
    req_id = secrets.token_hex(4)  # unique sorted-set member suffix

    result: int = await redis.eval(
        _SLIDING_WINDOW_LUA,
        1,  # numkeys
        key,  # KEYS[1]
        str(limit),  # ARGV[1]
        str(now_ms),  # ARGV[2]
        str(_WINDOW_MS),  # ARGV[3]
        req_id,  # ARGV[4]
    )

    if result == -1:
        raise RateLimitError(
            f"Rate limit exceeded: {limit} requests per minute",
            details={"limit": limit, "window_seconds": 60},
        )
