"""RBAC service layer: seeding and permission resolution."""
from __future__ import annotations

import logging

from django.db import transaction
from django.utils.text import slugify

from .constants import (
    DEFAULT_ROLE_PERMISSIONS,
    PERMISSION_LABELS,
    ROLE_LABELS,
    Roles,
)
from .models import Permission, Role

logger = logging.getLogger("apps.rbac")


@transaction.atomic
def seed_rbac() -> None:
    """Idempotently create/update the default permission + role catalog."""
    perm_objs: dict[str, Permission] = {}
    for codename, label in PERMISSION_LABELS.items():
        perm, _ = Permission.objects.update_or_create(
            codename=codename, defaults={"name": label}
        )
        perm_objs[codename] = perm

    for slug, codenames in DEFAULT_ROLE_PERMISSIONS.items():
        role, _ = Role.objects.update_or_create(
            slug=slug,
            defaults={
                "name": ROLE_LABELS.get(slug, slug.replace("_", " ").title()),
                "is_system": True,
                "is_superuser_role": slug == Roles.SUPER_ADMIN,
            },
        )
        role.permissions.set([perm_objs[c] for c in codenames])
    logger.info("RBAC seed complete: %d permissions, %d roles",
                len(perm_objs), len(DEFAULT_ROLE_PERMISSIONS))


def get_role(slug: str) -> Role | None:
    return Role.objects.filter(slug=slug).first()


def get_or_create_custom_role(name: str, codenames: list[str]) -> Role:
    slug = slugify(name)
    role, _ = Role.objects.get_or_create(
        slug=slug, defaults={"name": name, "is_system": False}
    )
    perms = Permission.objects.filter(codename__in=codenames)
    role.permissions.set(perms)
    return role


def permissions_for_role(role: Role | None) -> set[str]:
    if role is None:
        return set()
    if role.is_superuser_role:
        return set(PERMISSION_LABELS.keys())
    return role.permission_codenames()
