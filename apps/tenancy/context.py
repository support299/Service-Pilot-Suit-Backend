"""Request-scoped tenant resolution helpers.

The current tenant (``Location``) is derived from, in priority order:
    1. a JWT ``location_id`` claim (set at login), then
    2. the ``X-Location-Id`` request header, then
    3. a ``location_id`` query parameter.

Membership is resolved once per request against the authenticated user and
cached on the request object. All values are exposed as ``request.location``,
``request.location_id`` and ``request.membership``.
"""
from __future__ import annotations

from typing import Optional

from .models import Location, Membership

LOCATION_HEADER = "HTTP_X_LOCATION_ID"


def extract_location_id(request) -> Optional[str]:
    """Return the requested location id from header or query (not JWT)."""
    header = request.META.get(LOCATION_HEADER)
    if header:
        return header.strip()
    query = request.GET.get("location_id") if hasattr(request, "GET") else None
    return query.strip() if query else None


def get_location(location_id: Optional[str]) -> Optional[Location]:
    location_id = (location_id or "").strip()
    if not location_id:
        return None
    return (
        Location.objects.select_related("agency")
        .filter(ghl_location_id=location_id, is_active=True)
        .first()
    )


def set_current_location(request, location_id: Optional[str]) -> Optional[Location]:
    """Resolve and cache the current Location on the request."""
    location = get_location(location_id)
    request.location_id = location.ghl_location_id if location else (location_id or None)
    request.location = location
    # A change of location invalidates any cached membership.
    if getattr(request, "_membership_cached", False):
        request._membership_cached = False
        request.membership = None
    return location


def get_current_membership(request) -> Optional[Membership]:
    """Resolve (and cache) the membership for the authenticated user + location."""
    if getattr(request, "_membership_cached", False):
        return getattr(request, "membership", None)

    membership: Optional[Membership] = None
    user = getattr(request, "user", None)
    location = getattr(request, "location", None)
    if user is not None and getattr(user, "is_authenticated", False) and location is not None:
        membership = (
            Membership.objects.select_related("role", "location")
            .filter(user=user, location=location, is_active=True)
            .first()
        )

    request.membership = membership
    request._membership_cached = True
    return membership
