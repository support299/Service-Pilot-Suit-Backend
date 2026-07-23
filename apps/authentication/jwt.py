"""JWT issuance + tenant-aware authentication.

Tokens embed the ``location_id`` chosen at login / switch. On every authenticated
request, :class:`TenantJWTAuthentication` resolves the tenant from:

1. ``X-Location-Id`` header or ``location_id`` query param (explicit client choice)
2. else the JWT ``location_id`` claim

and attaches ``request.location`` / ``request.membership``.
"""
from __future__ import annotations

from typing import Optional

from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.tokens import RefreshToken

from apps.tenancy.context import extract_location_id, set_current_location
from apps.tenancy.models import Location

LOCATION_CLAIM = "location_id"


def issue_tokens_for_user(user, *, location: Optional[Location] = None) -> dict[str, str]:
    """Create an access/refresh pair, embedding the location claim when present."""
    refresh = RefreshToken.for_user(user)
    if location is not None:
        refresh[LOCATION_CLAIM] = location.ghl_location_id
    return {"access": str(refresh.access_token), "refresh": str(refresh)}


def _django_request(request):
    """Prefer the underlying Django HttpRequest (DRF wraps it)."""
    return getattr(request, "_request", request)


class TenantJWTAuthentication(JWTAuthentication):
    def authenticate(self, request):
        result = super().authenticate(request)
        if result is None:
            return None

        user, validated_token = result

        # Read the header/query from the raw Django request — do not trust a
        # previously cached request.location_id (may still be the JWT claim).
        django_request = _django_request(request)
        explicit_location_id = extract_location_id(django_request)
        claim_location_id = validated_token.get(LOCATION_CLAIM)
        location_id = explicit_location_id or claim_location_id

        if location_id:
            # Set on both wrappers so views and middleware-era code see the same tenant.
            set_current_location(django_request, location_id)
            set_current_location(request, location_id)
        # Membership is resolved lazily by the permission layer once ``request.user``
        # is populated, avoiding recursion during authentication itself.
        return user, validated_token
