"""Data-access for :class:`Location`."""
from __future__ import annotations

from typing import Iterable, Optional

from django.db.models import QuerySet

from ..models import Location


class LocationRepository:
    @staticmethod
    def get_by_location_id(location_id: str, *, only_active: bool = True) -> Optional[Location]:
        qs = Location.objects.select_related("agency").filter(ghl_location_id=location_id)
        if only_active:
            qs = qs.filter(is_active=True)
        return qs.first()

    @staticmethod
    def upsert(location_id: str, *, defaults: dict) -> tuple[Location, bool]:
        return Location.objects.update_or_create(
            ghl_location_id=location_id, defaults=defaults
        )

    @staticmethod
    def for_ids(location_ids: Iterable[str]) -> QuerySet[Location]:
        return Location.objects.filter(
            ghl_location_id__in=list(location_ids), is_active=True
        )

    @staticmethod
    def for_agency(company_id: str) -> QuerySet[Location]:
        return Location.objects.filter(
            agency__ghl_company_id=company_id, is_active=True
        )
