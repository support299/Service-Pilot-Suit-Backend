"""Celery tasks for GoHighLevel token refresh (mirrors Snapshot JobTracker).

Schedule: every 10 hours via ``CELERY_BEAT_SCHEDULE``.
Run worker:  ``celery -A config worker -l info``
Run beat:    ``celery -A config beat -l info``
"""
from __future__ import annotations

import logging

from celery import shared_task

from apps.tenancy.models import Agency, Location
from apps.tenancy.services import ProvisioningService

from .services.oauth import GHLOAuthService
from .services.user_sync import sync_location_users

logger = logging.getLogger("apps.authentication")


@shared_task(name="apps.authentication.tasks.refresh_ghl_tokens")
def refresh_ghl_tokens() -> dict:
    """Refresh agency tokens, then mint fresh location tokens for each subaccount."""
    service = GHLOAuthService()
    agencies = Agency.objects.filter(is_active=True).exclude(refresh_token="")
    logger.info("refresh_ghl_tokens: processing %s agency row(s)", agencies.count())

    agency_ok = 0
    agency_err = 0
    loc_ok = 0
    loc_err = 0

    for agency in agencies:
        refresh = (agency.refresh_token or "").strip()
        if not refresh:
            agency_err += 1
            continue
        try:
            payload = service.refresh_token(refresh)
            access = (payload.get("access_token") or "").strip()
            if not access:
                agency_err += 1
                logger.warning(
                    "refresh_ghl_tokens: no access_token for company_id=%s",
                    agency.ghl_company_id,
                )
                continue
            ProvisioningService.upsert_agency(
                company_id=agency.ghl_company_id, tokens=payload
            )
            agency_ok += 1
            logger.info(
                "refresh_ghl_tokens: refreshed company_id=%s", agency.ghl_company_id
            )

            # Re-mint location tokens from the fresh agency token.
            locations = Location.objects.filter(agency=agency, is_active=True)
            for location in locations:
                try:
                    loc_tokens = service.exchange_location_token(
                        company_id=agency.ghl_company_id,
                        company_token=access,
                        location_id=location.ghl_location_id,
                    )
                    ProvisioningService.upsert_location(
                        location_id=location.ghl_location_id,
                        agency=agency,
                        tokens=loc_tokens,
                    )
                    loc_ok += 1
                except Exception:
                    loc_err += 1
                    logger.exception(
                        "refresh_ghl_tokens: location token failed location_id=%s",
                        location.ghl_location_id,
                    )
        except Exception:
            agency_err += 1
            logger.exception(
                "refresh_ghl_tokens: failed company_id=%s", agency.ghl_company_id
            )

    # Also refresh locations that have their own refresh_token (location-level OAuth)
    # and are not covered by an agency refresh.
    orphan_locations = Location.objects.filter(is_active=True).exclude(refresh_token="")
    for location in orphan_locations:
        # Skip if we already refreshed via agency above.
        if location.agency_id and (location.agency.refresh_token or "").strip():
            continue
        refresh = (location.refresh_token or "").strip()
        if not refresh:
            continue
        try:
            payload = service.refresh_token(refresh)
            ProvisioningService.upsert_location(
                location_id=location.ghl_location_id, tokens=payload
            )
            loc_ok += 1
        except Exception:
            loc_err += 1
            logger.exception(
                "refresh_ghl_tokens: location refresh failed location_id=%s",
                location.ghl_location_id,
            )

    result = {
        "agency_success": agency_ok,
        "agency_errors": agency_err,
        "location_success": loc_ok,
        "location_errors": loc_err,
    }
    logger.info("refresh_ghl_tokens: done %s", result)
    return result


@shared_task(name="apps.authentication.tasks.sync_location_users_task")
def sync_location_users_task(location_id: str) -> dict:
    """Re-sync GHL users for a single location (by ghl_location_id)."""
    location = (
        Location.objects.select_related("agency")
        .filter(ghl_location_id=location_id, is_active=True)
        .first()
    )
    if location is None:
        return {"error": "location_not_found"}
    access = (location.access_token or "").strip()
    if not access and location.agency_id:
        access = (location.agency.access_token or "").strip()
    if not access:
        return {"error": "no_access_token"}
    return sync_location_users(location=location, access_token=access)
