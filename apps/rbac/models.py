"""Model-based RBAC: Permissions grouped into Roles.

Membership (in the ``tenancy`` app) assigns a Role to a User for a specific
Location, so the same user can hold different roles across tenants.
"""
from __future__ import annotations

from django.db import models

from apps.common.models import BaseModel


class Permission(BaseModel):
    """A single, atomic capability identified by a stable ``codename``."""

    codename = models.CharField(max_length=100, unique=True)
    name = models.CharField(max_length=150)
    description = models.TextField(blank=True, default="")

    class Meta:
        ordering = ["codename"]
        verbose_name = "permission"
        verbose_name_plural = "permissions"

    def __str__(self) -> str:
        return self.codename


class Role(BaseModel):
    """A named bundle of permissions."""

    slug = models.SlugField(max_length=60, unique=True)
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True, default="")
    permissions = models.ManyToManyField(
        Permission, related_name="roles", blank=True
    )
    # System roles are seeded and protected from deletion via the API.
    is_system = models.BooleanField(default=False)
    # Super admin roles bypass per-permission checks (full access).
    is_superuser_role = models.BooleanField(default=False)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name

    def permission_codenames(self) -> set[str]:
        return set(self.permissions.values_list("codename", flat=True))
