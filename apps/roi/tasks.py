"""Celery tasks for Meta + Google ads ROI sync."""
from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Optional

from celery import shared_task
from django.utils import timezone

from apps.tenancy.models import Location

from .services.google_sync import (
    DEFAULT_LOOKBACK_DAYS as GOOGLE_DEFAULT_LOOKBACK_DAYS,
)
from .services.google_sync import (
    ONBOARD_LOOKBACK_DAYS as GOOGLE_ONBOARD_LOOKBACK_DAYS,
)
from .services.google_sync import (
    RECENT_REFRESH_DAYS as GOOGLE_RECENT_REFRESH_DAYS,
)
from .services.google_sync import (
    sync_location_google_ads,
    sync_location_google_ads_lookback,
)
from .services.meta_sync import (
    DEFAULT_LOOKBACK_DAYS,
    ONBOARD_LOOKBACK_DAYS,
    RECENT_REFRESH_DAYS,
    sync_location_meta_ads,
    sync_location_meta_ads_lookback,
)

logger = logging.getLogger("apps.roi")


@shared_task(name="apps.roi.tasks.sync_location_meta_ads_task")
def sync_location_meta_ads_task(
    location_uuid: str,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> dict:
    location = (
        Location.objects.select_related("agency")
        .filter(id=location_uuid, is_active=True)
        .first()
    )
    if location is None:
        return {"error": "location_not_found"}
    start = date.fromisoformat(start_date) if start_date else None
    end = date.fromisoformat(end_date) if end_date else None
    try:
        return sync_location_meta_ads(location, start_date=start, end_date=end)
    except Exception as exc:
        logger.exception(
            "sync_location_meta_ads_task failed location=%s", location.ghl_location_id
        )
        return {"error": str(exc), "location_id": location.ghl_location_id}


@shared_task(
    name="apps.roi.tasks.sync_location_meta_ads_onboard_task",
    soft_time_limit=60 * 30,
    time_limit=60 * 35,
)
def sync_location_meta_ads_onboard_task(
    ghl_location_id: str,
    lookback_days: int = ONBOARD_LOOKBACK_DAYS,
) -> dict:
    """Background 1-year Meta ads backfill after a location is onboarded."""
    location = (
        Location.objects.select_related("agency")
        .filter(ghl_location_id=ghl_location_id, is_active=True)
        .first()
    )
    if location is None:
        return {"error": "location_not_found", "location_id": ghl_location_id}
    try:
        return sync_location_meta_ads_lookback(
            location, lookback_days=lookback_days
        )
    except Exception as exc:
        logger.exception(
            "onboard meta ads sync failed location=%s", ghl_location_id
        )
        return {"error": str(exc), "location_id": ghl_location_id}


def enqueue_onboard_meta_ads_sync(location_ids: list[str]) -> int:
    """Fire-and-forget Celery jobs for each newly onboarded GHL location."""
    queued = 0
    for loc_id in location_ids:
        loc_id = (loc_id or "").strip()
        if not loc_id:
            continue
        try:
            sync_location_meta_ads_onboard_task.delay(loc_id)
            queued += 1
            logger.info("Queued 1-year Meta ads backfill for location=%s", loc_id)
        except Exception:
            logger.exception(
                "Failed to queue Meta ads backfill for location=%s", loc_id
            )
    return queued


@shared_task(name="apps.roi.tasks.sync_all_locations_meta_ads")
def sync_all_locations_meta_ads() -> dict:
    """Beat job: refresh recent daily windows + campaign lists for all locations."""
    end = timezone.localdate()
    start = end - timedelta(days=RECENT_REFRESH_DAYS - 1)
    locations = Location.objects.select_related("agency").filter(is_active=True)
    ok = 0
    err = 0
    skipped = 0

    for location in locations:
        token = (location.access_token or "").strip()
        if not token and location.agency_id:
            token = (location.agency.access_token or "").strip()
        if not token:
            skipped += 1
            continue
        from .models import MetaAdDailyStat

        has_history = MetaAdDailyStat.objects.filter(location=location).exists()
        window_start = (
            start if has_history else end - timedelta(days=DEFAULT_LOOKBACK_DAYS - 1)
        )
        try:
            sync_location_meta_ads(location, start_date=window_start, end_date=end)
            ok += 1
        except Exception:
            err += 1
            logger.exception(
                "sync_all_locations_meta_ads failed location=%s",
                location.ghl_location_id,
            )

    result = {"success": ok, "errors": err, "skipped": skipped}
    logger.info("sync_all_locations_meta_ads done %s", result)
    return result


@shared_task(name="apps.roi.tasks.sync_location_google_ads_task")
def sync_location_google_ads_task(
    location_uuid: str,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> dict:
    location = (
        Location.objects.select_related("agency")
        .filter(id=location_uuid, is_active=True)
        .first()
    )
    if location is None:
        return {"error": "location_not_found"}
    start = date.fromisoformat(start_date) if start_date else None
    end = date.fromisoformat(end_date) if end_date else None
    try:
        return sync_location_google_ads(location, start_date=start, end_date=end)
    except Exception as exc:
        logger.exception(
            "sync_location_google_ads_task failed location=%s",
            location.ghl_location_id,
        )
        return {"error": str(exc), "location_id": location.ghl_location_id}


@shared_task(
    name="apps.roi.tasks.sync_location_google_ads_onboard_task",
    soft_time_limit=60 * 30,
    time_limit=60 * 35,
)
def sync_location_google_ads_onboard_task(
    ghl_location_id: str,
    lookback_days: int = GOOGLE_ONBOARD_LOOKBACK_DAYS,
) -> dict:
    """Background 1-year Google Ads backfill after a location is onboarded."""
    location = (
        Location.objects.select_related("agency")
        .filter(ghl_location_id=ghl_location_id, is_active=True)
        .first()
    )
    if location is None:
        return {"error": "location_not_found", "location_id": ghl_location_id}
    try:
        return sync_location_google_ads_lookback(
            location, lookback_days=lookback_days
        )
    except Exception as exc:
        logger.exception(
            "onboard google ads sync failed location=%s", ghl_location_id
        )
        return {"error": str(exc), "location_id": ghl_location_id}


def enqueue_onboard_google_ads_sync(location_ids: list[str]) -> int:
    """Fire-and-forget Celery jobs for Google Ads backfill on onboard."""
    queued = 0
    for loc_id in location_ids:
        loc_id = (loc_id or "").strip()
        if not loc_id:
            continue
        try:
            sync_location_google_ads_onboard_task.delay(loc_id)
            queued += 1
            logger.info("Queued 1-year Google Ads backfill for location=%s", loc_id)
        except Exception:
            logger.exception(
                "Failed to queue Google Ads backfill for location=%s", loc_id
            )
    return queued


@shared_task(name="apps.roi.tasks.sync_all_locations_google_ads")
def sync_all_locations_google_ads() -> dict:
    """Beat job: refresh recent Google Ads windows for all locations."""
    end = timezone.localdate()
    start = end - timedelta(days=GOOGLE_RECENT_REFRESH_DAYS - 1)
    locations = Location.objects.select_related("agency").filter(is_active=True)
    ok = 0
    err = 0
    skipped = 0

    for location in locations:
        token = (location.access_token or "").strip()
        if not token and location.agency_id:
            token = (location.agency.access_token or "").strip()
        if not token:
            skipped += 1
            continue
        from .models import GoogleAdDailyStat

        has_history = GoogleAdDailyStat.objects.filter(location=location).exists()
        window_start = (
            start
            if has_history
            else end - timedelta(days=GOOGLE_DEFAULT_LOOKBACK_DAYS - 1)
        )
        try:
            sync_location_google_ads(location, start_date=window_start, end_date=end)
            ok += 1
        except Exception:
            err += 1
            logger.exception(
                "sync_all_locations_google_ads failed location=%s",
                location.ghl_location_id,
            )

    result = {"success": ok, "errors": err, "skipped": skipped}
    logger.info("sync_all_locations_google_ads done %s", result)
    return result


@shared_task(name="apps.roi.tasks.sync_location_opportunities_task")
def sync_location_opportunities_task(location_uuid: str) -> dict:
    from .services.crm_sync import sync_location_opportunities

    location = (
        Location.objects.select_related("agency")
        .filter(id=location_uuid, is_active=True)
        .first()
    )
    if location is None:
        return {"error": "location_not_found"}
    try:
        return sync_location_opportunities(location)
    except Exception as exc:
        logger.exception(
            "sync_location_opportunities_task failed location=%s",
            location.ghl_location_id,
        )
        return {"error": str(exc), "location_id": location.ghl_location_id}


@shared_task(name="apps.roi.tasks.sync_all_locations_opportunities")
def sync_all_locations_opportunities() -> dict:
    """Beat job: refresh CRM opportunities for locations with confirmed pipeline."""
    from .models import RoiCrmSetup
    from .services.crm_sync import sync_location_opportunities

    setups = (
        RoiCrmSetup.objects.select_related("location", "location__agency")
        .filter(
            setup_status=RoiCrmSetup.SetupStatus.CONFIRMED,
            location__is_active=True,
        )
        .exclude(pipeline_id="")
    )
    ok = 0
    err = 0
    skipped = 0
    for setup in setups:
        location = setup.location
        token = (location.access_token or "").strip()
        if not token and location.agency_id:
            token = (location.agency.access_token or "").strip()
        if not token:
            skipped += 1
            continue
        try:
            sync_location_opportunities(location)
            ok += 1
        except Exception:
            err += 1
            logger.exception(
                "sync_all_locations_opportunities failed location=%s",
                location.ghl_location_id,
            )
    result = {"success": ok, "errors": err, "skipped": skipped}
    logger.info("sync_all_locations_opportunities done %s", result)
    return result
