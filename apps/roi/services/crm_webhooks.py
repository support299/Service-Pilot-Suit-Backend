"""GoHighLevel marketplace webhook handlers for opportunity events."""
from __future__ import annotations

import logging
from typing import Any, Optional

from django.utils import timezone

from apps.tenancy.models import Location

from ..models import GhlOpportunity, RoiCrmSetup
from .crm_sync import _upsert_opportunity, get_or_create_crm_setup

logger = logging.getLogger("apps.roi.crm.webhooks")

# Events enabled in the GHL Marketplace webhook UI for this app.
OPPORTUNITY_UPSERT_TYPES = frozenset(
    {
        "OpportunityCreate",
        "OpportunityUpdate",
        "OpportunityStageUpdate",
        "OpportunityStatusUpdate",
        "OpportunityMonetaryValueUpdate",
        "OpportunityAssignmentUpdate",
    }
)
OPPORTUNITY_DELETE_TYPES = frozenset({"OpportunityDelete"})


def handle_opportunity_webhook(payload: dict[str, Any]) -> dict[str, Any]:
    """Handle Opportunity* marketplace events."""
    if not isinstance(payload, dict):
        return {"ok": False, "action": "ignored", "reason": "invalid_payload"}

    event_type = str(payload.get("type") or payload.get("event") or "").strip()
    if event_type in OPPORTUNITY_DELETE_TYPES:
        return _handle_opportunity_delete(payload, event_type=event_type)
    if event_type in OPPORTUNITY_UPSERT_TYPES:
        return _handle_opportunity_upsert(payload, event_type=event_type)

    logger.info("GHL opportunity webhook ignored type=%s", event_type)
    return {"ok": True, "action": "ignored", "type": event_type}


def _resolve_location(payload: dict[str, Any]) -> Optional[Location]:
    location_id = str(
        payload.get("locationId")
        or payload.get("location_id")
        or ""
    ).strip()
    if not location_id:
        return None
    return (
        Location.objects.select_related("agency")
        .filter(ghl_location_id=location_id, is_active=True)
        .first()
    )


def _refresh_opportunity_count(location: Location) -> int:
    setup = get_or_create_crm_setup(location)
    if not setup.pipeline_id:
        count = GhlOpportunity.objects.filter(location=location).count()
    else:
        count = GhlOpportunity.objects.filter(
            location=location, pipeline_id=setup.pipeline_id
        ).count()
    setup.opportunities_synced = count
    setup.last_synced_at = timezone.now()
    setup.sync_status = "success"
    setup.last_sync_error = ""
    setup.save(
        update_fields=[
            "opportunities_synced",
            "last_synced_at",
            "sync_status",
            "last_sync_error",
            "updated_at",
        ]
    )
    return count


def _handle_opportunity_delete(payload: dict[str, Any], *, event_type: str) -> dict[str, Any]:
    location = _resolve_location(payload)
    if location is None:
        return {
            "ok": True,
            "action": "ignored",
            "type": event_type,
            "reason": "unknown_location",
        }

    oid = str(payload.get("id") or payload.get("_id") or "").strip()
    if not oid:
        return {
            "ok": True,
            "action": "ignored",
            "type": event_type,
            "reason": "missing_opportunity_id",
        }

    deleted, _ = GhlOpportunity.objects.filter(
        location=location, ghl_opportunity_id=oid
    ).delete()
    count = _refresh_opportunity_count(location)
    logger.info(
        "GHL webhook delete type=%s location=%s opp=%s deleted=%s",
        event_type,
        location.ghl_location_id,
        oid,
        deleted,
    )
    return {
        "ok": True,
        "action": "deleted" if deleted else "noop",
        "type": event_type,
        "location_id": location.ghl_location_id,
        "opportunity_id": oid,
        "opportunities_synced": count,
    }


def _handle_opportunity_upsert(payload: dict[str, Any], *, event_type: str) -> dict[str, Any]:
    location = _resolve_location(payload)
    if location is None:
        return {
            "ok": True,
            "action": "ignored",
            "type": event_type,
            "reason": "unknown_location",
        }

    setup = get_or_create_crm_setup(location)
    pipeline_id = str(payload.get("pipelineId") or "").strip()

    # Mirror bulk sync: only keep opps for the confirmed ROI pipeline.
    if (
        setup.setup_status != RoiCrmSetup.SetupStatus.CONFIRMED
        or not setup.pipeline_id
    ):
        return {
            "ok": True,
            "action": "skipped",
            "type": event_type,
            "reason": "pipeline_not_confirmed",
            "location_id": location.ghl_location_id,
        }

    oid = str(payload.get("id") or payload.get("_id") or "").strip()
    if pipeline_id and pipeline_id != setup.pipeline_id:
        deleted = 0
        if oid:
            deleted, _ = GhlOpportunity.objects.filter(
                location=location, ghl_opportunity_id=oid
            ).delete()
            if deleted:
                _refresh_opportunity_count(location)
        return {
            "ok": True,
            "action": "deleted_out_of_pipeline" if deleted else "skipped",
            "type": event_type,
            "reason": "pipeline_mismatch",
            "location_id": location.ghl_location_id,
            "opportunity_id": oid,
        }

    body = dict(payload)
    if not body.get("pipelineId"):
        body["pipelineId"] = setup.pipeline_id

    now = timezone.now()
    try:
        row = _upsert_opportunity(location, body, synced_at=now)
    except Exception as exc:
        logger.exception(
            "GHL webhook upsert failed type=%s location=%s",
            event_type,
            location.ghl_location_id,
        )
        return {
            "ok": False,
            "action": "error",
            "type": event_type,
            "reason": str(exc)[:500],
            "location_id": location.ghl_location_id,
        }

    count = _refresh_opportunity_count(location)
    logger.info(
        "GHL webhook upsert type=%s location=%s opp=%s",
        event_type,
        location.ghl_location_id,
        row.ghl_opportunity_id,
    )
    return {
        "ok": True,
        "action": "upserted",
        "type": event_type,
        "location_id": location.ghl_location_id,
        "opportunity_id": row.ghl_opportunity_id,
        "opportunities_synced": count,
    }
