"""Agency portal helpers — company-wide locations and people access."""
from __future__ import annotations

import logging
from typing import Optional

from django.db.models import Count, QuerySet

from apps.rbac.constants import Permissions, Roles
from apps.rbac.models import Role
from apps.rbac.services import (
    permission_catalog,
    permissions_for_membership,
    permissions_for_role,
)

from ..models import Agency, Location, Membership
from .access import accessible_locations_for_user

logger = logging.getLogger("apps.tenancy")


def resolve_agency_for_request(request) -> Optional[Agency]:
    """Pick the agency for portal scope from current location or user company."""
    location = getattr(request, "location", None)
    if location is not None and location.agency_id:
        return location.agency

    user = getattr(request, "user", None)
    if user is None:
        return None

    company_id = (getattr(user, "ghl_company_id", None) or "").strip()
    if company_id:
        agency = Agency.objects.filter(ghl_company_id=company_id, is_active=True).first()
        if agency is not None:
            return agency

    # Superuser / multi-agency: use first accessible location's agency.
    if getattr(user, "is_superuser", False) or accessible_locations_for_user(user).exists():
        loc = (
            accessible_locations_for_user(user)
            .filter(agency__isnull=False)
            .select_related("agency")
            .first()
        )
        if loc is not None:
            return loc.agency
    return None


def user_can_view_agency_portal(user, agency: Optional[Agency] = None) -> bool:
    if not user or not getattr(user, "is_authenticated", False):
        return False
    if user.is_superuser:
        return True
    # Require agency.view on a membership (Manager/Staff roles do not include it).
    memberships = Membership.objects.filter(user=user, is_active=True).select_related(
        "role", "location", "location__agency"
    )
    if agency is not None:
        memberships = memberships.filter(location__agency=agency)
    for m in memberships:
        if Permissions.AGENCY_VIEW in permissions_for_membership(m):
            return True
    return False


def user_can_manage_agency_portal(user, agency: Optional[Agency] = None) -> bool:
    if not user or not getattr(user, "is_authenticated", False):
        return False
    if user.is_superuser:
        return True
    memberships = Membership.objects.filter(user=user, is_active=True).select_related(
        "role", "location__agency"
    )
    if agency is not None:
        memberships = memberships.filter(location__agency=agency)
    for m in memberships:
        perms = permissions_for_membership(m)
        if Permissions.AGENCY_MANAGE in perms or Permissions.MEMBER_MANAGE in perms:
            return True
    return False


def agency_locations_qs(agency: Agency) -> QuerySet[Location]:
    return (
        Location.objects.filter(agency=agency, is_active=True)
        .select_related("agency")
        .annotate(member_count=Count("memberships", distinct=True))
        .order_by("name")
    )


def agency_memberships_qs(agency: Agency) -> QuerySet[Membership]:
    return (
        Membership.objects.filter(location__agency=agency, location__is_active=True)
        .select_related("user", "role", "location", "location__agency")
        .order_by("user__email", "location__name")
    )


def agency_users_payload(agency: Agency) -> list[dict]:
    """Group memberships by user for the people × locations matrix."""
    memberships = list(agency_memberships_qs(agency))
    by_user: dict[str, dict] = {}
    for m in memberships:
        key = str(m.user_id)
        if key not in by_user:
            u = m.user
            by_user[key] = {
                "id": key,
                "email": u.email,
                "first_name": u.first_name,
                "last_name": u.last_name,
                "full_name": u.get_full_name() or u.email,
                "is_active": u.is_active,
                "ghl_user_type": u.ghl_user_type,
                "access": [],
            }
        by_user[key]["access"].append(
            {
                "membership_id": str(m.id),
                "location_id": str(m.location_id),
                "ghl_location_id": m.location.ghl_location_id,
                "location_name": m.location.name or m.location.ghl_location_id,
                "role_id": str(m.role_id),
                "role_slug": m.role.slug,
                "role_name": m.role.name,
                "is_active": m.is_active,
                "permission_grants": list(m.permission_grants or []),
                "permission_denies": list(m.permission_denies or []),
                "permissions": sorted(permissions_for_membership(m)),
                "role_permissions": sorted(permissions_for_role(m.role)),
            }
        )
    rows = list(by_user.values())
    rows.sort(key=lambda r: (r["full_name"] or r["email"]).lower())
    return rows


def serialize_membership_permissions(membership: Membership) -> dict:
    return {
        "membership_id": str(membership.id),
        "user_id": str(membership.user_id),
        "location_id": str(membership.location_id),
        "role_id": str(membership.role_id),
        "role_slug": membership.role.slug,
        "role_name": membership.role.name,
        "catalog": permission_catalog(),
        "role_permissions": sorted(permissions_for_role(membership.role)),
        "permission_grants": list(membership.permission_grants or []),
        "permission_denies": list(membership.permission_denies or []),
        "permissions": sorted(permissions_for_membership(membership)),
    }


def set_membership_permissions(
    membership: Membership,
    *,
    enabled: list[str] | None = None,
    grants: list[str] | None = None,
    denies: list[str] | None = None,
) -> dict:
    """Update overrides.

    Prefer ``enabled`` = full desired effective set (toggle UI). We derive
    grants/denies vs the role baseline.
    """
    from apps.rbac.constants import PERMISSION_LABELS

    valid = set(PERMISSION_LABELS.keys())
    role_base = permissions_for_role(membership.role)

    if enabled is not None:
        desired = {str(c).strip() for c in enabled if str(c).strip() in valid}
        membership.permission_grants = sorted(desired - role_base)
        membership.permission_denies = sorted(role_base - desired)
    else:
        if grants is not None:
            membership.permission_grants = sorted(
                {str(c).strip() for c in grants if str(c).strip() in valid}
            )
        if denies is not None:
            membership.permission_denies = sorted(
                {str(c).strip() for c in denies if str(c).strip() in valid}
            )

    membership.save(update_fields=["permission_grants", "permission_denies", "updated_at"])
    return serialize_membership_permissions(membership)


def assignable_roles_qs(user) -> QuerySet[Role]:
    qs = Role.objects.filter(is_system=True).order_by("name")
    if not getattr(user, "is_superuser", False):
        qs = qs.exclude(slug=Roles.SUPER_ADMIN)
    return qs
