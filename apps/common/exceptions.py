"""Project-wide exceptions and a DRF exception handler for uniform errors.

Every error response has the shape::

    {"error": {"code": "not_found", "message": "...", "details": {...}}}
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_exception_handler

logger = logging.getLogger("apps.common")


class ServiceError(Exception):
    """Base class for domain/service-layer errors.

    Service layers raise these instead of returning HTTP responses, keeping
    business logic decoupled from the web layer.
    """

    default_message = "An unexpected error occurred."
    default_code = "error"
    status_code = status.HTTP_400_BAD_REQUEST

    def __init__(
        self,
        message: Optional[str] = None,
        *,
        code: Optional[str] = None,
        details: Optional[dict[str, Any]] = None,
    ) -> None:
        self.message = message or self.default_message
        self.code = code or self.default_code
        self.details = details or {}
        super().__init__(self.message)


class ValidationError(ServiceError):
    default_message = "The submitted data is invalid."
    default_code = "validation_error"
    status_code = status.HTTP_400_BAD_REQUEST


class NotFoundError(ServiceError):
    default_message = "The requested resource was not found."
    default_code = "not_found"
    status_code = status.HTTP_404_NOT_FOUND


class PermissionDeniedError(ServiceError):
    default_message = "You do not have permission to perform this action."
    default_code = "permission_denied"
    status_code = status.HTTP_403_FORBIDDEN


class AuthenticationFailedError(ServiceError):
    default_message = "Authentication failed."
    default_code = "authentication_failed"
    status_code = status.HTTP_401_UNAUTHORIZED


class IntegrationError(ServiceError):
    """A downstream integration (e.g. GoHighLevel) failed."""

    default_message = "An upstream integration error occurred."
    default_code = "integration_error"
    status_code = status.HTTP_502_BAD_GATEWAY


def _error_body(code: str, message: str, details: Any = None) -> dict[str, Any]:
    body: dict[str, Any] = {"error": {"code": code, "message": message}}
    if details:
        body["error"]["details"] = details
    return body


def api_exception_handler(exc: Exception, context: dict) -> Optional[Response]:
    """Return a uniform error envelope for both DRF and service errors."""
    if isinstance(exc, ServiceError):
        logger.info("ServiceError %s: %s", exc.code, exc.message)
        return Response(
            _error_body(exc.code, exc.message, exc.details),
            status=exc.status_code,
        )

    response = drf_exception_handler(exc, context)
    if response is None:
        logger.exception("Unhandled exception in %s", context.get("view"))
        return Response(
            _error_body("server_error", "An unexpected server error occurred."),
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    detail = response.data
    code = "error"
    message = "Request failed."
    if isinstance(detail, dict) and "detail" in detail and len(detail) == 1:
        message = str(detail["detail"])
        code = getattr(detail["detail"], "code", None) or code
        response.data = _error_body(code, message)
    else:
        # Field validation errors: keep the field map under details.
        code = "validation_error"
        message = "The submitted data is invalid."
        response.data = _error_body(code, message, detail)
    return response
