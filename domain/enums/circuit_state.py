"""
Circuit breaker states.

The circuit breaker pattern prevents a failing upstream from causing
cascading failures throughout the gateway. The state machine works as follows:

    CLOSED ──(error_count >= threshold)──► OPEN
      ▲                                      │
      │                           (timeout expires)
      │                                      ▼
      └──(probe succeeds)────── HALF_OPEN ◄──┘
              (probe fails)──────────► OPEN

CLOSED:    Normal operation. Requests flow through to the upstream.
           Error count is tracked. If errors exceed the threshold within
           a rolling window, the breaker trips to OPEN.

OPEN:      Circuit is open — all requests are rejected immediately with
           503 Service Unavailable. No upstream calls are made. This gives
           the upstream time to recover without being hammered.

HALF_OPEN: After the timeout period, exactly ONE probe request is allowed
           through. If it succeeds, the circuit closes. If it fails, the
           circuit reopens and the timeout resets.

This state machine is implemented in gateway/circuit_breaker.py.
"""

from enum import StrEnum


class CircuitState(StrEnum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"
