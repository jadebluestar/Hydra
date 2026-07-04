"""
Circuit breaker for gateway upstreams.

Protects the gateway from upstream failures cascading into request pile-up.
Instead of waiting for every request to time out against a dead upstream, the
breaker trips to OPEN after a failure threshold is reached and returns 503
immediately — no upstream call, no timeout, no resource exhaustion.

State machine:
    CLOSED ──(failures >= threshold in window)──► OPEN
      ▲                                              │
      │                              (recovery timeout passes)
      │                                              ▼
      └──(probe succeeds)────────── HALF_OPEN ◄─────┘
              (probe fails)──────────────────► OPEN (timer reset)

Redis keys (per upstream_id):
    hydra:cb:{id}:failures  — INCR counter; TTL = window_seconds
    hydra:cb:{id}:open_at   — float timestamp; present when circuit is OPEN
    hydra:cb:{id}:probe     — SET NX flag; present when a probe is in flight

Probe exclusivity: when the circuit enters HALF_OPEN, the first request to
check() claims the probe slot atomically via SET NX. Subsequent requests see
the slot taken and are rejected (503) until either the probe succeeds (all
keys deleted → CLOSED) or the probe fails (open_at reset, probe key deleted).

Configuration defaults (module-level constants — can be overridden via kwargs):
    FAILURE_THRESHOLD  = 5  failures before tripping
    WINDOW_SECONDS     = 60 rolling window for failure count
    RECOVERY_TIMEOUT_SECONDS = 30 seconds before allowing a probe
"""

from __future__ import annotations

import time

from redis.asyncio import Redis

from cache.keys import cb_failure_key, cb_open_at_key, cb_probe_key
from core.exceptions import ServiceUnavailableError
from domain.enums.circuit_state import CircuitState

FAILURE_THRESHOLD: int = 5
WINDOW_SECONDS: int = 60
RECOVERY_TIMEOUT_SECONDS: int = 30
UPSTREAM_ERROR_CODES: frozenset[int] = frozenset({502, 503, 504})

# Auto-expiry on the open_at key — prevents orphaned keys if the process dies
# while a circuit is open and no subsequent request ever resets it.
_OPEN_KEY_TTL = 24 * 3600

# Atomically increment failure counter and set TTL on first write.
# Using Lua prevents a race where two concurrent requests both see count=1
# and both try to EXPIRE — both would succeed anyway (idempotent), but the
# Lua version is cleaner and consistent with our rate limiter approach.
# KEYS[1]  = failure counter key
# ARGV[1]  = window in seconds
_INCREMENT_LUA = """
local count = redis.call('INCR', KEYS[1])
if count == 1 then
    redis.call('EXPIRE', KEYS[1], tonumber(ARGV[1]))
end
return count
"""


class CircuitBreaker:
    def __init__(
        self,
        redis: Redis,  # type: ignore[type-arg]
        *,
        failure_threshold: int = FAILURE_THRESHOLD,
        window_seconds: int = WINDOW_SECONDS,
        recovery_timeout_seconds: int = RECOVERY_TIMEOUT_SECONDS,
    ) -> None:
        self._redis = redis
        self._failure_threshold = failure_threshold
        self._window_seconds = window_seconds
        self._recovery_timeout = recovery_timeout_seconds

    async def check(self, upstream_id: str) -> CircuitState:
        """
        Determine the circuit state for this upstream.

        Returns CircuitState.CLOSED or CircuitState.HALF_OPEN when the request
        should proceed to the upstream.

        Raises ServiceUnavailableError (503) when the circuit is OPEN, so the
        caller can let the exception propagate without any special handling.
        """
        open_at_raw = await self._redis.get(cb_open_at_key(upstream_id))
        if open_at_raw is None:
            return CircuitState.CLOSED

        open_at = float(open_at_raw)
        elapsed = time.time() - open_at

        if elapsed < self._recovery_timeout:
            remaining = int(self._recovery_timeout - elapsed)
            raise ServiceUnavailableError(
                "Upstream circuit breaker is open",
                details={"retry_after_seconds": remaining},
            )

        # Recovery timeout has passed — try to claim the probe slot atomically.
        # SET NX ensures only one concurrent request becomes the probe.
        claimed = await self._redis.set(
            cb_probe_key(upstream_id),
            "1",
            nx=True,
            ex=self._recovery_timeout,
        )
        if claimed:
            return CircuitState.HALF_OPEN

        # Another request already owns the probe — this request waits.
        raise ServiceUnavailableError(
            "Upstream circuit breaker is open (probe in flight)",
            details={"retry_after_seconds": 0},
        )

    async def record_success(
        self,
        upstream_id: str,
        *,
        was_half_open: bool,
    ) -> None:
        """
        Record a successful upstream response.

        Only acts when was_half_open=True: deletes all circuit breaker keys to
        transition back to CLOSED. In CLOSED state a success is a no-op —
        the failure counter has its own TTL and expires naturally.
        """
        if was_half_open:
            await self._redis.delete(
                cb_open_at_key(upstream_id),
                cb_failure_key(upstream_id),
                cb_probe_key(upstream_id),
            )

    async def record_failure(
        self,
        upstream_id: str,
        *,
        was_half_open: bool,
    ) -> None:
        """
        Record a failed upstream response (502/503/504 or connection error).

        HALF_OPEN probe failed:
            Reset open_at to now (restart the recovery timer) and release the
            probe slot so the next probe can be claimed after the timeout.

        CLOSED state failure:
            Increment the failure counter. If the count reaches the threshold,
            set open_at to trip the circuit to OPEN.
        """
        if was_half_open:
            # Probe failed — extend the open period and free the probe slot
            await self._redis.set(
                cb_open_at_key(upstream_id),
                str(time.time()),
                ex=_OPEN_KEY_TTL,
            )
            await self._redis.delete(cb_probe_key(upstream_id))
            return

        count: int = await self._redis.eval(
            _INCREMENT_LUA,
            1,
            cb_failure_key(upstream_id),
            str(self._window_seconds),
        )
        if count >= self._failure_threshold:
            await self._redis.set(
                cb_open_at_key(upstream_id),
                str(time.time()),
                ex=_OPEN_KEY_TTL,
            )
