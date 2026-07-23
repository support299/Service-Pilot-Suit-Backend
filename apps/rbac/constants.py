"""Canonical RBAC definitions.

Roles and permissions are seeded into the database from these constants (see
``services.seed_rbac``) so checks are data-driven, but the source of truth for
the *default* catalog lives here in version control.
"""
from __future__ import annotations


class Roles:
    SUPER_ADMIN = "super_admin"
    AGENCY_ADMIN = "agency_admin"
    MANAGER = "manager"
    STAFF = "staff"
    READ_ONLY = "read_only"


ROLE_LABELS: dict[str, str] = {
    Roles.SUPER_ADMIN: "Super Admin",
    Roles.AGENCY_ADMIN: "Agency Admin",
    Roles.MANAGER: "Manager",
    Roles.STAFF: "Staff",
    Roles.READ_ONLY: "Read Only",
}


class Permissions:
    # Tenant / org management
    AGENCY_VIEW = "agency.view"
    AGENCY_MANAGE = "agency.manage"
    LOCATION_VIEW = "location.view"
    LOCATION_MANAGE = "location.manage"
    # People
    MEMBER_VIEW = "member.view"
    MEMBER_MANAGE = "member.manage"
    USER_VIEW = "user.view"
    USER_MANAGE = "user.manage"
    # RBAC
    ROLE_VIEW = "role.view"
    ROLE_MANAGE = "role.manage"
    # Reporting (ROI Center)
    REPORT_VIEW = "report.view"
    REPORT_MANAGE = "report.manage"
    # Success Center — Support
    SUPPORT_VIEW = "support.view"
    SUPPORT_MANAGE = "support.manage"
    # Success Center — Academy
    ACADEMY_VIEW = "academy.view"
    ACADEMY_MANAGE = "academy.manage"
    # Settings
    SETTINGS_VIEW = "settings.view"
    SETTINGS_MANAGE = "settings.manage"


PERMISSION_LABELS: dict[str, str] = {
    Permissions.AGENCY_VIEW: "View agencies",
    Permissions.AGENCY_MANAGE: "Manage agencies",
    Permissions.LOCATION_VIEW: "View locations",
    Permissions.LOCATION_MANAGE: "Manage locations",
    Permissions.MEMBER_VIEW: "View members",
    Permissions.MEMBER_MANAGE: "Manage members",
    Permissions.USER_VIEW: "View users",
    Permissions.USER_MANAGE: "Manage users",
    Permissions.ROLE_VIEW: "View roles",
    Permissions.ROLE_MANAGE: "Manage roles",
    Permissions.REPORT_VIEW: "View reports",
    Permissions.REPORT_MANAGE: "Manage reports",
    Permissions.SUPPORT_VIEW: "View support tickets",
    Permissions.SUPPORT_MANAGE: "Manage support tickets",
    Permissions.ACADEMY_VIEW: "View Academy training",
    Permissions.ACADEMY_MANAGE: "Manage Academy content",
    Permissions.SETTINGS_VIEW: "View settings",
    Permissions.SETTINGS_MANAGE: "Manage settings",
}

ALL_PERMISSIONS: tuple[str, ...] = tuple(PERMISSION_LABELS.keys())

_READ_ONLY_PERMS: tuple[str, ...] = (
    Permissions.AGENCY_VIEW,
    Permissions.LOCATION_VIEW,
    Permissions.MEMBER_VIEW,
    Permissions.USER_VIEW,
    Permissions.ROLE_VIEW,
    Permissions.REPORT_VIEW,
    Permissions.SUPPORT_VIEW,
    Permissions.ACADEMY_VIEW,
    Permissions.SETTINGS_VIEW,
)

_STAFF_PERMS: tuple[str, ...] = _READ_ONLY_PERMS + (
    Permissions.REPORT_MANAGE,
    Permissions.SUPPORT_MANAGE,
    Permissions.ACADEMY_MANAGE,
)

_MANAGER_PERMS: tuple[str, ...] = _STAFF_PERMS + (
    Permissions.MEMBER_MANAGE,
    Permissions.USER_MANAGE,
    Permissions.LOCATION_MANAGE,
    Permissions.SETTINGS_MANAGE,
)

_AGENCY_ADMIN_PERMS: tuple[str, ...] = _MANAGER_PERMS + (
    Permissions.AGENCY_MANAGE,
    Permissions.ROLE_MANAGE,
)

# Super Admin implicitly holds every permission (see ``services``), but we still
# grant the full catalog for explicitness.
DEFAULT_ROLE_PERMISSIONS: dict[str, tuple[str, ...]] = {
    Roles.SUPER_ADMIN: ALL_PERMISSIONS,
    Roles.AGENCY_ADMIN: _AGENCY_ADMIN_PERMS,
    Roles.MANAGER: _MANAGER_PERMS,
    Roles.STAFF: _STAFF_PERMS,
    Roles.READ_ONLY: _READ_ONLY_PERMS,
}
