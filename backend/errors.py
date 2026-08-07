"""Typed error contract — BACKEND_PLAN.md §4.6.

The frontend renders three of these differently, so the class survives
past the HTTP status code rather than collapsing into a bare exception.
"""

from __future__ import annotations


class ServiceError(Exception):
    """Base for typed errors the API translates to a specific status."""

    http_status: int = 500
    error_class: str = "INTERNAL"

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class InvalidRequestError(ServiceError):
    http_status = 400
    error_class = "INVALID_REQUEST"


class ToolchainMissingError(ServiceError):
    http_status = 503
    error_class = "TOOLCHAIN_MISSING"


class InferenceUnavailableError(ServiceError):
    http_status = 503
    error_class = "INFERENCE_UNAVAILABLE"


class RunNotFoundError(ServiceError):
    http_status = 404
    error_class = "RUN_NOT_FOUND"


class OfflineViolationError(ServiceError):
    """Raised when the service is asked to bind or call off loopback.

    Not in the plan's error-class table (it aborts startup, it does not
    answer a request), but it shares the same typed-exception shape so
    __main__ can print a clear reason and exit non-zero.
    """

    http_status = 500
    error_class = "OFFLINE_VIOLATION"
