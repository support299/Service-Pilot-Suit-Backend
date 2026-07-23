"""Data-access for :class:`Membership`."""
from __future__ import annotations

from typing import Optional

from django.db.models import QuerySet

from ..models import Location, Membership


class MembershipRepository:
    @staticmethod
    def get(user, location: Location) -> Optional[Membership]:
        return (
            Membership.objects.select_related("role", "location", "location__agency")
            .filter(user=user, location=location, is_active=True)
            .first()
        )

    @staticmethod
    def for_user(user) -> QuerySet[Membership]:
        return (
            Membership.objects.select_related("role", "location", "location__agency")
            .filter(user=user, is_active=True, location__is_active=True)
        )

    @staticmethod
    def for_location(location: Location) -> QuerySet[Membership]:
        return (
            Membership.objects.select_related("role", "user")
            .filter(location=location, is_active=True)
        )

    @staticmethod
    def upsert(user, location: Location, role) -> tuple[Membership, bool]:
        return Membership.objects.update_or_create(
            user=user,
            location=location,
            defaults={"role": role, "is_active": True},
        )
