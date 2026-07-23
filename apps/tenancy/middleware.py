"""Tenant middleware.

Resolves the current location from the ``X-Location-Id`` header (or
``location_id`` query param) early in the request lifecycle so ``request.location``
is always available. When the user authenticates via JWT, the JWT ``location_id``
claim takes precedence and is applied by
:class:`apps.authentication.jwt.TenantJWTAuthentication`.
"""
from __future__ import annotations

from .context import extract_location_id, set_current_location


class TenantMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Defaults; may be overridden after JWT auth resolves a claim.
        request.location = None
        request.location_id = None
        request.membership = None
        request._membership_cached = False

        location_id = extract_location_id(request)
        if location_id:
            set_current_location(request, location_id)

        return self.get_response(request)
