"""
Structured logging configuration using structlog.

Every log line is a single JSON object written to stdout. In production, a log
aggregator (Loki, Datadog, CloudWatch, etc.) ingests these lines directly.

In development (json_logs=False), structlog renders colorized human-readable
output instead.

Context variables — request_id, correlation_id, user_id — are propagated
automatically via structlog.contextvars across the full async call stack without
threading them through every function signature.

Usage:
    from core.logging import get_logger
    logger = get_logger(__name__)
    logger.info("user.registered", user_id=str(user.id), email=user.email)
"""

import logging
import sys
from typing import Any

import structlog


def configure_logging(*, debug: bool = False, json_logs: bool = True) -> None:
    log_level = logging.DEBUG if debug else logging.INFO

    # Processors shared between structlog-native loggers and stdlib-bridged loggers
    # (uvicorn, sqlalchemy, etc.). Order matters — each processor receives the
    # event dict from the previous one.
    shared_processors: list[Any] = [
        structlog.contextvars.merge_contextvars,  # inject request_id, user_id, etc.
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.ExceptionRenderer(),
    ]

    renderer: Any = (
        structlog.processors.JSONRenderer()
        if json_logs
        else structlog.dev.ConsoleRenderer(colors=True)
    )

    structlog.configure(
        processors=shared_processors
        + [structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared_processors,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            renderer,
        ],
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(log_level)

    # Reduce noise from libraries in production
    if not debug:
        logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
        logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)
