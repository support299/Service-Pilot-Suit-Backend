"""GoHighLevel marketplace webhook router.

Mirrors Snapshot JobTracker ``accounts.views.webhook_handler``:
  INSTALL / UNINSTALL → provision or deactivate a location
  UserCreate / UserUpdate / UserDelete → membership sync
  Opportunity* → ROI CRM cache (delegated)
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from django.core.cache import cache
from django.db import transaction

from apps.common.exceptions import IntegrationError
from apps.tenancy.models import Agency, Location, Membership

logger = logging.getLogger("apps.authentication.webhooks")

USER_UPSERT_TYPES = frozenset({"UserCreate", "UserUpdate"})
USER_DELETE_TYPES = frozenset({"UserDelete"})

PRIMARY_LOCATION_CACHE_TTL = 300


def handle_ghl_webhook(payload: dict[str, Any]) -> dict[str, Any]:
    """Route a marketplace webhook body. Always safe from an AllowAny view."""
    if not isinstance(payload, dict):
        return {"ok": False, "action": "ignored", "reason": "invalid_payload"}

    event_type = str(payload.get("type") or payload.get("event") or "").strip()
    if not event_type:
        return {"ok": True, "action": "ignored", "reason": "missing_type"}

    event_upper = event_type.upper()
    if event_upper == "INSTALL":
        return handle_install_webhook(payload)
    if event_upper == "UNINSTALL":
        return handle_uninstall_webhook(payload)

    if event_type in USER_UPSERT_TYPES:
        return handle_user_upsert_webhook(payload, event_type=event_type)
    if event_type in USER_DELETE_TYPES:
        return handle_user_delete_webhook(payload, event_type=event_type)

    if event_type.startswith("Opportunity"):
        from apps.roi.services.crm_webhooks import handle_opportunity_webhook

        return handle_opportunity_webhook(payload)

    logger.info("GHL webhook ignored type=%s", event_type)
    return {"ok": True, "action": "ignored", "type": event_type}


def handle_install_webhook(data: dict[str, Any]) -> dict[str, Any]:
    """INSTALL: mint location token from company auth and bootstrap the tenant."""
    from .oauth import GHLOAuthService

    location_id = str(data.get("locationId") or "").strip()
    company_id = str(data.get("companyId") or "").strip()
    user_id = str(data.get("userId") or "").strip()
    company_name = str(data.get("companyName") or "").strip()

    if location_id and company_id:
        cache.set(
            f"ghl_bulk_oauth_primary:{company_id}",
            location_id,
            timeout=PRIMARY_LOCATION_CACHE_TTL,
        )
        logger.info(
            "GHL INSTALL: cached primary location hint company_id=%s location_id=%s",
            company_id,
            location_id,
        )

    if not location_id or not company_id:
        return {"ok": True, "action": "skipped", "reason": "missing_ids"}

    existing = (
        Location.objects.filter(ghl_location_id=location_id, is_active=True)
        .exclude(access_token="")
        .first()
    )
    if existing is not None:
        logger.info("GHL INSTALL: location %s already connected, skipping", location_id)
        return {
            "ok": True,
            "action": "skipped",
            "reason": "already_exists",
            "location_id": location_id,
        }

    agency = Agency.objects.filter(ghl_company_id=company_id).first()
    if agency is None or not (agency.access_token or "").strip():
        logger.warning(
            "GHL INSTALL: no company-level token company_id=%s location_id=%s",
            company_id,
            location_id,
        )
        return {
            "ok": True,
            "action": "skipped",
            "reason": "no_company_token",
            "location_id": location_id,
        }

    if company_name and not (agency.name or "").strip():
        agency.name = company_name
        agency.save(update_fields=["name", "updated_at"])

    oauth = GHLOAuthService()
    try:
        token_data = oauth.exchange_location_token(
            company_id=company_id,
            company_token=agency.access_token,
            location_id=location_id,
        )
    except (IntegrationError, Exception) as exc:
        logger.warning(
            "GHL INSTALL: token exchange failed company_id=%s location_id=%s error=%s",
            company_id,
            location_id,
            exc,
        )
        return {
            "ok": True,
            "action": "skipped",
            "reason": "token_exchange_failed",
            "location_id": location_id,
        }

    if user_id and not str(token_data.get("userId") or "").strip():
        token_data["userId"] = user_id

    created = not Location.objects.filter(ghl_location_id=location_id).exists()
    oauth.bootstrap_location_from_token(
        token_data, agency=agency, company_id=company_id
    )
    _post_install_side_effects([location_id])

    logger.info(
        "GHL INSTALL: %s location_id=%s company_id=%s",
        "created" if created else "updated",
        location_id,
        company_id,
    )
    return {
        "ok": True,
        "action": "created" if created else "updated",
        "location_id": location_id,
        "company_id": company_id,
    }


@transaction.atomic
def handle_uninstall_webhook(data: dict[str, Any]) -> dict[str, Any]:
    """UNINSTALL: deactivate location + memberships and clear OAuth tokens."""
    location_id = str(data.get("locationId") or "").strip()
    if not location_id:
        return {"ok": True, "action": "skipped", "reason": "missing_location_id"}

    location = Location.objects.filter(ghl_location_id=location_id).first()
    if location is None:
        return {
            "ok": True,
            "action": "noop",
            "reason": "unknown_location",
            "location_id": location_id,
        }

    location.is_active = False
    location.status = Location.STATUS_CHURNED
    location.access_token = ""
    location.refresh_token = ""
    location.scope = ""
    location.token_expires_at = None
    location.save(
        update_fields=[
            "is_active",
            "status",
            "access_token",
            "refresh_token",
            "scope",
            "token_expires_at",
            "updated_at",
        ]
    )
    deactivated = Membership.objects.filter(location=location, is_active=True).update(
        is_active=False
    )
    logger.info(
        "GHL UNINSTALL: location_id=%s deactivated_memberships=%s",
        location_id,
        deactivated,
    )
    return {
        "ok": True,
        "action": "uninstalled",
        "location_id": location_id,
        "deactivated_memberships": deactivated,
    }


def handle_user_upsert_webhook(
    payload: dict[str, Any], *, event_type: str
) -> dict[str, Any]:
    from .user_sync import normalize_ghl_user_webhook_payload, upsert_user_from_ghl

    user_data = normalize_ghl_user_webhook_payload(payload)
    ghl_user_id = str(user_data.get("id") or "").strip()
    location_id = str(payload.get("locationId") or "").strip()
    company_id = str(
        payload.get("companyId") or user_data.get("companyId") or ""
    ).strip()
    location_ids = _target_location_ids(payload, location_id=location_id, company_id=company_id)

    if not location_ids:
        return {
            "ok": True,
            "action": "skipped",
            "type": event_type,
            "reason": "no_target_locations",
            "ghl_user_id": ghl_user_id,
        }

    upserted = 0
    for loc_id in location_ids:
        location = (
            Location.objects.select_related("agency")
            .filter(ghl_location_id=loc_id, is_active=True)
            .first()
        )
        if location is None:
            continue
        try:
            upsert_user_from_ghl(user_data, location=location)
            upserted += 1
        except Exception:
            logger.exception(
                "GHL webhook user upsert failed type=%s location=%s user=%s",
                event_type,
                loc_id,
                ghl_user_id,
            )

    return {
        "ok": True,
        "action": "upserted" if upserted else "skipped",
        "type": event_type,
        "ghl_user_id": ghl_user_id,
        "locations": upserted,
    }


def handle_user_delete_webhook(
    payload: dict[str, Any], *, event_type: str
) -> dict[str, Any]:
    from .user_sync import deactivate_user_from_ghl_webhook

    result = deactivate_user_from_ghl_webhook(payload)
    result["type"] = event_type
    result["ok"] = True
    return result


def _target_location_ids(
    payload: dict[str, Any], *, location_id: str, company_id: str
) -> list[str]:
    if location_id:
        return [location_id]

    locations = payload.get("locations") or []
    if isinstance(locations, str):
        locations = [locations]
    ids = [str(x).strip() for x in locations if str(x).strip()]
    if ids:
        return ids

    if not company_id:
        return []
    return list(
        Location.objects.filter(agency__ghl_company_id=company_id, is_active=True)
        .values_list("ghl_location_id", flat=True)
    )


def _post_install_side_effects(location_ids: list[str]) -> None:
    """Media folders + ads backfill (same as OAuth onboard)."""
    try:
        from apps.roi.tasks import (
            enqueue_onboard_google_ads_sync,
            enqueue_onboard_meta_ads_sync,
        )

        enqueue_onboard_meta_ads_sync(location_ids)
        enqueue_onboard_google_ads_sync(location_ids)
    except Exception:
        logger.exception(
            "GHL INSTALL: failed to enqueue ads sync locations=%s", location_ids
        )

    try:
        from apps.tenancy.services.ghl_media import ensure_location_onboard_media_folders

        for loc_id in location_ids:
            loc = (
                Location.objects.select_related("agency")
                .filter(ghl_location_id=loc_id, is_active=True)
                .first()
            )
            if loc is not None:
                ensure_location_onboard_media_folders(loc)
    except Exception:
        logger.exception(
            "GHL INSTALL: failed to ensure media folders locations=%s", location_ids
        )


def prioritize_installed_locations(
    company_id: str, locations: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Prefer the INSTALL-selected location during company-level OAuth (Snapshot)."""
    preferred_location_id = cache.get(f"ghl_bulk_oauth_primary:{company_id}")
    if not preferred_location_id:
        return locations

    preferred: Optional[dict[str, Any]] = None
    remaining: list[dict[str, Any]] = []
    for loc in locations:
        loc_id = str(loc.get("_id") or loc.get("id") or "").strip()
        if loc_id == preferred_location_id and preferred is None:
            preferred = loc
        else:
            remaining.append(loc)

    if preferred is None:
        return locations

    logger.info(
        "Prioritizing INSTALL-selected location company_id=%s location_id=%s",
        company_id,
        preferred_location_id,
    )
    return [preferred] + remaining
