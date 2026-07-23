"""Centralized DRF permission classes.

These read the tenant membership resolved by the tenancy layer
(``request.membership``, set by :class:`apps.tenancy.context.TenantContext`) and
the RBAC role attached to it. Keep *all* permission logic here rather than
scattering ``if user.role == ...`` checks across views.
"""
from __future__ import annotations

from typing import Iterable

from rest_framework.permissions import BasePermission

from .constants import ALL_PERMISSIONS
from .services import permissions_for_membership, permissions_for_role


def _resolve_membership(request):
    # Lazy import avoids a circular import (tenancy models import rbac).
    from apps.tenancy.context import get_current_membership

    return get_current_membership(request)


def effective_permissions(request) -> set[str]:
    """Return the set of permission codenames the request currently holds."""
    user = getattr(request, "user", None)
    if not user or not user.is_authenticated:
        return set()
    if user.is_superuser:
        return set(ALL_PERMISSIONS)
    membership = _resolve_membership(request)
    if membership is None:
        return set()
    return permissions_for_membership(membership)


class IsSuperAdmin(BasePermission):
    message = "Super admin access is required."

    def has_permission(self, request, view) -> bool:
        user = getattr(request, "user", None)
        return bool(user and user.is_authenticated and user.is_superuser)


class HasTenantContext(BasePermission):
    """Require a resolved current location (tenant)."""

    message = "A location context is required (X-Location-Id header or JWT claim)."

    def has_permission(self, request, view) -> bool:
        return getattr(request, "location", None) is not None


class IsTenantMember(BasePermission):
    """Require the user to be a member of the current location (or superuser)."""

    message = "You are not a member of this location."

    def has_permission(self, request, view) -> bool:
        user = getattr(request, "user", None)
        if not user or not user.is_authenticated:
            return False
        if user.is_superuser:
            return True
        return _resolve_membership(request) is not None


class HasPermission(BasePermission):
    """Factory-style permission: ``HasPermission.require("member.manage")``.

    Views set ``required_permissions`` (iterable of codenames) or use the
    factory. All listed permissions must be present.
    """

    required: tuple[str, ...] = ()
    message = "You do not have permission to perform this action."

    @classmethod
    def require(cls, *codenames: str) -> type["HasPermission"]:
        name = "HasPermission_" + "_".join(c.replace(".", "_") for c in codenames)
        return type(name, (cls,), {"required": tuple(codenames)})

    def _required_for(self, view) -> Iterable[str]:
        return self.required or getattr(view, "required_permissions", ())

    def has_permission(self, request, view) -> bool:
        user = getattr(request, "user", None)
        if not user or not user.is_authenticated:
            return False
        if user.is_superuser:
            return True
        held = effective_permissions(request)
        return all(code in held for code in self._required_for(view))
