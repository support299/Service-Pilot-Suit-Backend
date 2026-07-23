"""Access-resolution service: which locations can a user operate in, and how.

Membership rows are the source of truth. Agency-level GHL users additionally get
access to every active location of their company (matching the reference
platform), which is materialised into an Agency Admin membership on first login.
"""
from __future__ import annotations

import logging
from typing import Optional

from django.db.models import QuerySet

from apps.rbac.constants import Roles
from apps.rbac.services import get_role

from ..models import Location, Membership
from ..repositories import LocationRepository, MembershipRepository

logger = logging.getLogger("apps.tenancy")


def accessible_locations_for_user(user) -> QuerySet[Location]:
    """All active locations the user may access (superuser → all)."""
    if user.is_superuser:
        return Location.objects.filter(is_active=True).select_related("agency")

    location_ids = list(
        MembershipRepository.for_user(user).values_list(
            "location__ghl_location_id", flat=True
        )
    )

    # Agency users implicitly see their company's locations.
    if user.is_agency_user and user.ghl_company_id:
        agency_qs = LocationRepository.for_agency(user.ghl_company_id)
        if user.ghl_restrict_sub_account and user.ghl_location_ids:
            agency_qs = agency_qs.filter(ghl_location_id__in=user.ghl_location_ids)
        location_ids.extend(agency_qs.values_list("ghl_location_id", flat=True))

    return (
        Location.objects.filter(ghl_location_id__in=set(location_ids), is_active=True)
        .select_related("agency")
        .distinct()
    )


def _agency_user_can_access(user, location: Location) -> bool:
    company_id = (user.ghl_company_id or "").strip()
    loc_company = (location.agency.ghl_company_id if location.agency else "").strip()
    if company_id and loc_company and company_id != loc_company:
        return False
    if user.ghl_restrict_sub_account:
        return location.ghl_location_id in (user.ghl_location_ids or [])
    return True


def user_can_access_location(user, location: Location) -> bool:
    """Return True if the user may operate in ``location``."""
    if not user or not getattr(user, "is_authenticated", False):
        return False
    if user.is_superuser:
        return True
    if MembershipRepository.get(user, location) is not None:
        return True
    if user.is_agency_user:
        return _agency_user_can_access(user, location)
    return False


def resolve_membership_for_login(user, location: Location) -> Optional[Membership]:
    """Resolve the membership to use at login, materialising agency access.

    Returns ``None`` for superusers (they bypass per-location membership) and for
    users with no legitimate access to the location.
    """
    if user.is_superuser:
        return None

    membership = MembershipRepository.get(user, location)
    if membership is not None:
        return membership

    # Materialise implicit agency access into a concrete membership.
    if user.is_agency_user and _agency_user_can_access(user, location):
        role = get_role(Roles.AGENCY_ADMIN)
        if role is None:
            logger.error("Agency Admin role missing; run seed_rbac.")
            return None
        membership, _ = MembershipRepository.upsert(user, location, role)
        logger.info("Materialised agency membership user=%s location=%s", user.pk, location.pk)
        return membership

    return None
