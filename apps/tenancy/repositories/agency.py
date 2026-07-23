"""Data-access for :class:`Agency`. Keeps ORM queries out of services/views."""
from __future__ import annotations

from typing import Optional

from ..models import Agency


class AgencyRepository:
    @staticmethod
    def get_by_company_id(company_id: str) -> Optional[Agency]:
        return Agency.objects.filter(ghl_company_id=company_id).first()

    @staticmethod
    def upsert(company_id: str, *, defaults: dict) -> tuple[Agency, bool]:
        return Agency.objects.update_or_create(
            ghl_company_id=company_id, defaults=defaults
        )
