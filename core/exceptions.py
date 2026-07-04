"""
Centralized exception hierarchy and FastAPI exception handlers.

Every domain error in Hydra is a subclass of HydraError. This gives us:
  - A single place to define error codes and HTTP status codes
  - Consistent JSON error responses across every endpoint
  - The ability to raise business errors from service/repository layers
    without those layers knowing anything about HTTP

Error response shape:
    {
        "error": "not_found",
        "message": "Resource not found",
        "details": {}
    }

The correlation_id is injected by the logging middleware and appears in every
log line, so callers can trace an error back to their original request.
"""

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from core.logging import get_logger

logger = get_logger(__name__)


# ── Base Exception ────────────────────────────────────────────────────────────


class HydraError(Exception):
    """
    Base class for all application-level errors.

    Subclass this to create domain-specific exceptions. The exception handler
    registered below converts any HydraError into a structured JSON response
    automatically.
    """

    status_code: int = status.HTTP_500_INTERNAL_SERVER_ERROR
    error_code: str = "internal_error"
    message: str = "An unexpected error occurred"

    def __init__(
        self,
        message: str | None = None,
        details: dict[str, object] | None = None,
    ) -> None:
        self.message = message or self.__class__.message
        self.details = details or {}
        super().__init__(self.message)


# ── Domain Exceptions ─────────────────────────────────────────────────────────


class NotFoundError(HydraError):
    status_code = status.HTTP_404_NOT_FOUND
    error_code = "not_found"
    message = "Resource not found"


class ConflictError(HydraError):
    status_code = status.HTTP_409_CONFLICT
    error_code = "conflict"
    message = "Resource already exists"


class UnauthorizedError(HydraError):
    status_code = status.HTTP_401_UNAUTHORIZED
    error_code = "unauthorized"
    message = "Authentication required"


class ForbiddenError(HydraError):
    status_code = status.HTTP_403_FORBIDDEN
    error_code = "forbidden"
    message = "Insufficient permissions"


class ValidationFailedError(HydraError):
    status_code = status.HTTP_422_UNPROCESSABLE_CONTENT
    error_code = "validation_failed"
    message = "Input validation failed"


class RateLimitError(HydraError):
    status_code = status.HTTP_429_TOO_MANY_REQUESTS
    error_code = "rate_limit_exceeded"
    message = "Rate limit exceeded"


class ServiceUnavailableError(HydraError):
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    error_code = "service_unavailable"
    message = "Service is temporarily unavailable"


# ── Handler Registration ──────────────────────────────────────────────────────


def configure_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(HydraError)
    async def hydra_error_handler(request: Request, exc: HydraError) -> JSONResponse:
        logger.warning(
            "request.error",
            error_code=exc.error_code,
            message=exc.message,
            status_code=exc.status_code,
            path=str(request.url.path),
        )
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": exc.error_code,
                "message": exc.message,
                "details": exc.details,
            },
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        # Pydantic validation errors from request bodies/query params
        errors = [
            {
                "field": ".".join(str(loc) for loc in err["loc"]),
                "message": err["msg"],
                "type": err["type"],
            }
            for err in exc.errors()
        ]
        logger.info(
            "request.validation_failed",
            path=str(request.url.path),
            error_count=len(errors),
        )
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            content={
                "error": "validation_failed",
                "message": "Request validation failed",
                "details": {"errors": errors},
            },
        )

    @app.exception_handler(Exception)
    async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.error(
            "request.unhandled_error",
            exc_info=True,
            path=str(request.url.path),
            error_type=type(exc).__name__,
        )
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "error": "internal_error",
                "message": "An unexpected error occurred",
                "details": {},
            },
        )
