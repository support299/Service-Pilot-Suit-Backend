"""Location-scoped membership permission edits."""
from __future__ import annotations

from apps.common.exceptions import NotFoundError, PermissionDeniedError
from apps.rbac.constants import Permissions, Roles
from apps.rbac.services import permissions_for_membership
from apps.tenancy.models import Membership

from .agency_portal import serialize_membership_permissions, set_membership_permissions

# Who a given actor role may edit at the location level.
_MANAGER_TARGETS = frozenset({Roles.MANAGER, Roles.STAFF, Roles.READ_ONLY})
_AGENCY_ADMIN_BLOCKED_TARGETS = frozenset({Roles.SUPER_ADMIN})

# Managers cannot grant these (agency / platform ops).
_MANAGER_FORBIDDEN_PERMS = frozenset(
    {
        Permissions.AGENCY_VIEW,
        Permissions.AGENCY_MANAGE,
        Permissions.ROLE_MANAGE,
        Permissions.FEATURE_MANAGE,
        Permissions.ACADEMY_MANAGE,
    }
)


def get_location_membership(location, membership_id: str) -> Membership:
    membership = (
        Membership.objects.select_related("user", "role", "location")
        .filter(pk=membership_id, location=location)
        .first()
    )
    if membership is None:
        raise NotFoundError("Membership not found.", code="membership_not_found")
    return membership


def actor_membership_for_location(request) -> Membership | None:
    membership = getattr(request, "membership", None)
    if membership is not None:
        return membership
    user = getattr(request, "user", None)
    location = getattr(request, "location", None)
    if not user or not location:
        return None
    return (
        Membership.objects.select_related("role")
        .filter(user=user, location=location, is_active=True)
        .first()
    )


def can_edit_location_membership_permissions(
    *,
    actor,
    actor_membership: Membership | None,
    target: Membership,
) -> bool:
    if getattr(actor, "is_superuser", False):
        return True
    if actor_membership is None or not actor_membership.is_active:
        return False

    held = permissions_for_membership(actor_membership)
    if Permissions.MEMBER_MANAGE not in held and not getattr(actor, "is_superuser", False):
        return False

    actor_slug = actor_membership.role.slug
    target_slug = target.role.slug

    if target_slug == Roles.SUPER_ADMIN:
        return False

    if actor_slug == Roles.AGENCY_ADMIN:
        return target_slug not in _AGENCY_ADMIN_BLOCKED_TARGETS

    if actor_slug == Roles.MANAGER:
        return target_slug in _MANAGER_TARGETS

    return False


def assert_can_edit_location_membership_permissions(
    *,
    actor,
    actor_membership: Membership | None,
    target: Membership,
) -> None:
    if not can_edit_location_membership_permissions(
        actor=actor,
        actor_membership=actor_membership,
        target=target,
    ):
        raise PermissionDeniedError(
            "You cannot edit permissions for this member.",
            code="membership_permission_forbidden",
        )


def filter_enabled_for_actor(
    *,
    actor,
    actor_membership: Membership | None,
    enabled: list[str] | None,
) -> list[str] | None:
    """Managers may only grant permissions they themselves hold (minus forbidden)."""
    if enabled is None:
        return None
    if getattr(actor, "is_superuser", False):
        return enabled
    if actor_membership is None:
        return enabled
    if actor_membership.role.slug == Roles.AGENCY_ADMIN:
        return enabled

    held = permissions_for_membership(actor_membership) - _MANAGER_FORBIDDEN_PERMS
    return [c for c in enabled if c in held]


def catalog_for_actor(*, actor, actor_membership: Membership | None) -> list[dict[str, str]]:
    from apps.rbac.services import permission_catalog

    catalog = permission_catalog()
    if getattr(actor, "is_superuser", False):
        return catalog
    if actor_membership and actor_membership.role.slug == Roles.AGENCY_ADMIN:
        return catalog

    held: set[str] = set()
    if actor_membership is not None:
        held = permissions_for_membership(actor_membership) - _MANAGER_FORBIDDEN_PERMS
    return [row for row in catalog if row["codename"] in held]


def serialize_location_membership_permissions(
    membership: Membership,
    *,
    actor,
    actor_membership: Membership | None,
) -> dict:
    data = serialize_membership_permissions(membership)
    data["catalog"] = catalog_for_actor(actor=actor, actor_membership=actor_membership)
    data["can_edit"] = can_edit_location_membership_permissions(
        actor=actor,
        actor_membership=actor_membership,
        target=membership,
    )
    return data


def update_location_membership_permissions(
    membership: Membership,
    *,
    actor,
    actor_membership: Membership | None,
    enabled: list[str] | None = None,
    grants: list[str] | None = None,
    denies: list[str] | None = None,
) -> dict:
    assert_can_edit_location_membership_permissions(
        actor=actor,
        actor_membership=actor_membership,
        target=membership,
    )
    filtered = filter_enabled_for_actor(
        actor=actor,
        actor_membership=actor_membership,
        enabled=enabled,
    )
    data = set_membership_permissions(
        membership,
        enabled=filtered,
        grants=grants,
        denies=denies,
    )
    data["catalog"] = catalog_for_actor(actor=actor, actor_membership=actor_membership)
    data["can_edit"] = True
    return data
