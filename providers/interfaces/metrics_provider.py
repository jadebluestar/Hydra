"""
Metrics Provider interface.

Defines the contract for emitting application metrics. The current
implementation uses Prometheus (Milestone 21). A future implementation
could emit to StatsD, OpenTelemetry, Datadog, etc.

Metric types:
  Counter   — monotonically increasing value (request count, error count)
  Histogram — distribution of observed values (request duration, payload size)
  Gauge     — current value that can go up or down (active connections, queue size)

All operations are synchronous because Prometheus metrics are in-memory
operations — they update an atomic counter in the local process. The
Prometheus server scrapes the /metrics endpoint; the app never pushes.
"""

from typing import Protocol, runtime_checkable


@runtime_checkable
class MetricsProvider(Protocol):
    def increment_counter(
        self,
        name: str,
        *,
        labels: dict[str, str] | None = None,
        amount: float = 1.0,
    ) -> None:
        """
        Increment a counter metric.

        Example:
            metrics.increment_counter(
                "hydra_http_requests_total",
                labels={"method": "GET", "status_code": "200"},
            )
        """
        ...

    def record_histogram(
        self,
        name: str,
        value: float,
        *,
        labels: dict[str, str] | None = None,
    ) -> None:
        """
        Record an observation in a histogram.

        Example:
            metrics.record_histogram(
                "hydra_request_duration_seconds",
                value=0.034,
                labels={"route_id": "abc123"},
            )
        """
        ...

    def set_gauge(
        self,
        name: str,
        value: float,
        *,
        labels: dict[str, str] | None = None,
    ) -> None:
        """
        Set a gauge to the given value.

        Example:
            metrics.set_gauge(
                "hydra_db_pool_connections",
                value=float(pool.size()),
                labels={"state": "active"},
            )
        """
        ...
