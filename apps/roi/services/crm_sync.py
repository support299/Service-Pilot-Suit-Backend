"""GHL opportunities + pipeline helpers for ROI CRM returns."""
from __future__ import annotations

import logging
from datetime import date, datetime, time, timezone as dt_timezone
from decimal import Decimal
from typing import Any, Optional

import requests
from django.conf import settings
from django.db.models import Count, Q, Sum
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from apps.common.exceptions import IntegrationError, ValidationError
from apps.tenancy.models import Location
from apps.tenancy.services.ghl_media import ensure_location_access_token

from ..models import GhlOpportunity, RoiCrmSetup
from .ghl_facebook import resolve_location_access_token
from .google_sync import summarize_google_ads
from .meta_sync import summarize_meta_ads

logger = logging.getLogger("apps.roi.crm")

API_VERSION = "2021-07-28"


def _api_base() -> str:
    return settings.GHL["API_BASE_URL"].rstrip("/")


def _headers(access_token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {access_token}",
        "Version": API_VERSION,
        "Accept": "application/json",
        "Content-Type": "application/json",
    }


def normalize_opportunity_status(raw: Any) -> str:
    text = str(raw or "").strip().lower()
    if text in ("open",):
        return GhlOpportunity.Status.OPEN
    if text in ("won", "closed won", "closed_won"):
        return GhlOpportunity.Status.WON
    if text in ("lost", "closed lost", "closed_lost"):
        return GhlOpportunity.Status.LOST
    if text in ("abandoned", "abandon", "abondoned"):
        return GhlOpportunity.Status.ABANDONED
    if "won" in text:
        return GhlOpportunity.Status.WON
    if "lost" in text:
        return GhlOpportunity.Status.LOST
    if "abandon" in text:
        return GhlOpportunity.Status.ABANDONED
    if text == "open" or text.startswith("open"):
        return GhlOpportunity.Status.OPEN
    return GhlOpportunity.Status.OTHER


def map_source_channel(raw: Any) -> str:
    """Map GHL source strings like 'fb lead' / 'google lead' / 'Facebook' to channels."""
    text = str(raw or "").strip().lower()
    if not text:
        return GhlOpportunity.SourceChannel.OTHER
    compact = text.replace(" ", "").replace("_", "").replace("-", "")
    if "google" in text:
        return GhlOpportunity.SourceChannel.GOOGLE
    if (
        "fb" in text
        or "facebook" in text
        or "meta" in text
        or "paid social" in text
        or compact in ("fblead", "fbleads", "paidsocial")
    ):
        return GhlOpportunity.SourceChannel.FACEBOOK
    return GhlOpportunity.SourceChannel.OTHER


def _parse_dt(value: Any) -> Optional[datetime]:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value if timezone.is_aware(value) else timezone.make_aware(value)
    if isinstance(value, (int, float)):
        # GHL sometimes returns ms timestamps
        ts = float(value)
        if ts > 1e12:
            ts = ts / 1000.0
        try:
            return datetime.fromtimestamp(ts, tz=dt_timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    text = str(value).strip()
    if not text:
        return None
    parsed = parse_datetime(text.replace("Z", "+00:00"))
    if parsed is None:
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
    if timezone.is_naive(parsed):
        parsed = timezone.make_aware(parsed)
    return parsed


def _money(value: Any) -> Decimal:
    try:
        return Decimal(str(value if value is not None else 0)).quantize(Decimal("0.01"))
    except Exception:
        return Decimal("0.00")


def _extract_source(payload: dict[str, Any]) -> str:
    for key in ("source", "opportunitySource", "leadSource"):
        val = payload.get(key)
        if val:
            return str(val).strip()
    custom = payload.get("customFields") or payload.get("customField") or []
    if isinstance(custom, dict):
        for k, v in custom.items():
            if "source" in str(k).lower() and v:
                return str(v).strip()
    if isinstance(custom, list):
        for item in custom:
            if not isinstance(item, dict):
                continue
            key = str(
                item.get("key")
                or item.get("fieldKey")
                or item.get("name")
                or item.get("id")
                or ""
            ).lower()
            if "source" in key:
                val = item.get("field_value") or item.get("value") or item.get("fieldValue")
                if val:
                    return str(val).strip()
    return ""


def fetch_ghl_pipelines(access_token: str, location_id: str) -> list[dict[str, Any]]:
    url = f"{_api_base()}/opportunities/pipelines"
    try:
        resp = requests.get(
            url,
            headers=_headers(access_token),
            params={"locationId": location_id},
            timeout=60,
        )
    except requests.RequestException as exc:
        raise IntegrationError(
            "Failed to reach GoHighLevel pipelines API.",
            code="ghl_network_error",
            details={"error": str(exc)},
        ) from exc

    if resp.status_code >= 400:
        raise IntegrationError(
            "GoHighLevel could not list pipelines.",
            code="ghl_pipelines_error",
            details={"status": resp.status_code, "body": (resp.text or "")[:400]},
        )

    try:
        payload = resp.json()
    except ValueError as exc:
        raise IntegrationError(
            "Invalid pipelines response from GoHighLevel.",
            code="ghl_invalid_json",
        ) from exc

    rows: list[Any]
    if isinstance(payload, list):
        rows = payload
    elif isinstance(payload, dict):
        rows = payload.get("pipelines") or payload.get("data") or payload.get("results") or []
    else:
        rows = []

    out: list[dict[str, Any]] = []
    for item in rows:
        if not isinstance(item, dict):
            continue
        pid = str(item.get("id") or item.get("_id") or "").strip()
        name = str(item.get("name") or item.get("title") or pid).strip()
        if not pid:
            continue
        stages = []
        for stage in item.get("stages") or []:
            if not isinstance(stage, dict):
                continue
            sid = str(stage.get("id") or stage.get("_id") or "").strip()
            if not sid:
                continue
            stages.append(
                {
                    "id": sid,
                    "name": str(stage.get("name") or stage.get("title") or sid),
                }
            )
        out.append({"id": pid, "name": name, "stages": stages})
    return out


def search_ghl_opportunities(
    access_token: str,
    location_id: str,
    *,
    pipeline_id: Optional[str] = None,
    max_pages: int = 50,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """Paginated opportunity search. TruShine/GHL expects GET ``/opportunities/search``."""
    return _search_opportunities_get(
        access_token,
        location_id,
        pipeline_id=pipeline_id,
        max_pages=max_pages,
        limit=limit,
    )


def _search_opportunities_get(
    access_token: str,
    location_id: str,
    *,
    pipeline_id: Optional[str] = None,
    max_pages: int = 50,
    limit: int = 100,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    next_url: Optional[str] = f"{_api_base()}/opportunities/search"
    page = 1
    while next_url and page <= max_pages:
        params: Optional[dict[str, Any]] = None
        if page == 1:
            params = {
                "location_id": location_id,
                "limit": str(limit),
            }
            if pipeline_id:
                params["pipeline_id"] = pipeline_id
        try:
            resp = requests.get(
                next_url,
                headers=_headers(access_token),
                params=params,
                timeout=90,
            )
        except requests.RequestException as exc:
            raise IntegrationError(
                "Failed to reach GoHighLevel opportunities API.",
                code="ghl_network_error",
                details={"error": str(exc)},
            ) from exc
        if resp.status_code >= 400:
            raise IntegrationError(
                "GoHighLevel could not search opportunities.",
                code="ghl_opportunities_error",
                details={"status": resp.status_code, "body": (resp.text or "")[:400]},
            )
        try:
            payload = resp.json()
        except ValueError as exc:
            raise IntegrationError(
                "Invalid opportunities response from GoHighLevel.",
                code="ghl_invalid_json",
            ) from exc

        batch = (
            payload.get("opportunities")
            or payload.get("data")
            or payload.get("results")
            or []
        )
        if isinstance(batch, list):
            for item in batch:
                if isinstance(item, dict):
                    rows.append(item)

        meta = payload.get("meta") if isinstance(payload, dict) else {}
        meta = meta if isinstance(meta, dict) else {}
        next_page_url = meta.get("nextPageUrl")
        if next_page_url:
            next_url = str(next_page_url)
            if next_url.startswith("/"):
                next_url = f"{_api_base()}{next_url}"
            page += 1
            continue
        start_after = meta.get("startAfter")
        start_after_id = meta.get("startAfterId")
        if start_after and start_after_id and batch:
            from urllib.parse import urlencode

            q = {
                "location_id": location_id,
                "limit": str(limit),
                "startAfter": str(start_after),
                "startAfterId": str(start_after_id),
            }
            if pipeline_id:
                q["pipeline_id"] = pipeline_id
            next_url = f"{_api_base()}/opportunities/search?{urlencode(q)}"
            page += 1
            continue
        break
    return rows


def get_or_create_crm_setup(location: Location) -> RoiCrmSetup:
    setup, _ = RoiCrmSetup.objects.get_or_create(location=location)
    return setup


def serialize_crm_setup(setup: RoiCrmSetup) -> dict[str, Any]:
    pipeline_id = setup.pipeline_id or ""
    opportunity_count = 0
    if pipeline_id:
        opportunity_count = GhlOpportunity.objects.filter(
            location_id=setup.location_id, pipeline_id=pipeline_id
        ).count()
    return {
        "location_id": setup.location.ghl_location_id,
        "pipeline_id": pipeline_id,
        "pipeline_name": setup.pipeline_name,
        "setup_status": setup.setup_status,
        "confirmed_at": setup.confirmed_at.isoformat() if setup.confirmed_at else None,
        "last_synced_at": setup.last_synced_at.isoformat() if setup.last_synced_at else None,
        "opportunities_synced": setup.opportunities_synced,
        "opportunity_count": opportunity_count,
        "sync_status": setup.sync_status,
        "last_sync_error": setup.last_sync_error,
        "is_configured": bool(
            pipeline_id and setup.setup_status == RoiCrmSetup.SetupStatus.CONFIRMED
        ),
    }


def discover_pipelines(location: Location) -> dict[str, Any]:
    token = resolve_location_access_token(location) or ""
    try:
        pipelines = fetch_ghl_pipelines(token, location.ghl_location_id) if token else []
    except IntegrationError:
        token = ensure_location_access_token(location, force_refresh=True)
        pipelines = fetch_ghl_pipelines(token, location.ghl_location_id)

    setup = get_or_create_crm_setup(location)
    return {
        **serialize_crm_setup(setup),
        "pipelines": pipelines,
    }


def save_crm_pipeline(
    location: Location,
    *,
    pipeline_id: str,
    pipeline_name: str = "",
) -> dict[str, Any]:
    pipeline_id = (pipeline_id or "").strip()
    if not pipeline_id:
        raise ValidationError("Select a pipeline.")

    # Prefer name from live discovery when not provided.
    name = (pipeline_name or "").strip()
    if not name:
        try:
            discovered = discover_pipelines(location)
            for p in discovered.get("pipelines") or []:
                if p.get("id") == pipeline_id:
                    name = str(p.get("name") or "")
                    break
        except Exception:
            logger.exception("pipeline name lookup failed location=%s", location.ghl_location_id)

    setup = get_or_create_crm_setup(location)
    setup.pipeline_id = pipeline_id
    setup.pipeline_name = name or pipeline_id
    setup.setup_status = RoiCrmSetup.SetupStatus.CONFIRMED
    setup.confirmed_at = timezone.now()
    setup.save(
        update_fields=[
            "pipeline_id",
            "pipeline_name",
            "setup_status",
            "confirmed_at",
            "updated_at",
        ]
    )
    return serialize_crm_setup(setup)


def _upsert_opportunity(
    location: Location, payload: dict[str, Any], *, synced_at: datetime
) -> GhlOpportunity:
    oid = str(payload.get("id") or payload.get("_id") or "").strip()
    if not oid:
        raise ValidationError("Opportunity missing id.")

    status_raw = str(payload.get("status") or "").strip()
    source_raw = _extract_source(payload)
    stage_id = str(payload.get("pipelineStageId") or "").strip()
    stage_name = ""
    stage_obj = payload.get("pipelineStage")
    if isinstance(stage_obj, dict):
        stage_id = str(stage_obj.get("id") or stage_id).strip()
        stage_name = str(stage_obj.get("name") or "").strip()
    elif stage_obj and not stage_id:
        stage_id = str(stage_obj).strip()

    contact = payload.get("contact") if isinstance(payload.get("contact"), dict) else {}
    contact_id = str(
        payload.get("contactId") or contact.get("id") or contact.get("_id") or ""
    ).strip()

    money_raw = payload.get("monetaryValue")
    if money_raw is None:
        money_raw = payload.get("value")

    defaults = {
        "pipeline_id": str(payload.get("pipelineId") or "").strip(),
        "pipeline_stage_id": stage_id,
        "pipeline_stage_name": stage_name,
        "name": str(payload.get("name") or payload.get("title") or "")[:512],
        "status": normalize_opportunity_status(status_raw),
        "status_raw": status_raw[:64],
        "monetary_value": _money(money_raw),
        "source_raw": source_raw[:255],
        "source_channel": map_source_channel(source_raw),
        "contact_id": contact_id[:64],
        "ghl_created_at": _parse_dt(payload.get("createdAt") or payload.get("dateAdded")),
        "ghl_updated_at": _parse_dt(payload.get("updatedAt")),
        "last_status_change_at": _parse_dt(
            payload.get("lastStatusChangeAt")
            or payload.get("statusUpdatedAt")
            or payload.get("lastStageChangeAt")
        ),
        "raw": payload,
        "synced_at": synced_at,
    }
    obj, _ = GhlOpportunity.objects.update_or_create(
        location=location,
        ghl_opportunity_id=oid,
        defaults=defaults,
    )
    return obj


def sync_location_opportunities(location: Location) -> dict[str, Any]:
    setup = get_or_create_crm_setup(location)
    if not setup.pipeline_id or setup.setup_status != RoiCrmSetup.SetupStatus.CONFIRMED:
        raise ValidationError(
            "Select and confirm a CRM pipeline before syncing opportunities."
        )

    setup.sync_status = "syncing"
    setup.last_sync_error = ""
    setup.save(update_fields=["sync_status", "last_sync_error", "updated_at"])

    try:
        token = resolve_location_access_token(location) or ""
        if not token:
            token = ensure_location_access_token(location, force_refresh=True)
        try:
            payloads = search_ghl_opportunities(
                token,
                location.ghl_location_id,
                pipeline_id=setup.pipeline_id,
            )
        except IntegrationError as exc:
            details = getattr(exc, "details", None) or {}
            if details.get("status") in (401, 403):
                token = ensure_location_access_token(location, force_refresh=True)
                payloads = search_ghl_opportunities(
                    token,
                    location.ghl_location_id,
                    pipeline_id=setup.pipeline_id,
                )
            else:
                raise

        now = timezone.now()
        seen_ids: list[str] = []
        for payload in payloads:
            if not payload.get("pipelineId"):
                payload = {**payload, "pipelineId": setup.pipeline_id}
            try:
                row = _upsert_opportunity(location, payload, synced_at=now)
                seen_ids.append(row.ghl_opportunity_id)
            except ValidationError:
                continue

        # Drop opps that left this pipeline (only for the selected pipeline).
        stale = GhlOpportunity.objects.filter(
            location=location, pipeline_id=setup.pipeline_id
        ).exclude(ghl_opportunity_id__in=seen_ids)
        deleted, _ = stale.delete()

        setup.opportunities_synced = len(seen_ids)
        setup.last_synced_at = now
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
        result = {
            "location_id": location.ghl_location_id,
            "pipeline_id": setup.pipeline_id,
            "upserted": len(seen_ids),
            "deleted_stale": deleted,
            "synced_at": now.isoformat(),
        }
        logger.info("CRM opportunities sync done %s", result)
        return result
    except Exception as exc:
        setup.sync_status = "error"
        setup.last_sync_error = str(exc)[:2000]
        setup.save(update_fields=["sync_status", "last_sync_error", "updated_at"])
        raise


def _day_bounds(start: date, end: date) -> tuple[datetime, datetime]:
    start_dt = timezone.make_aware(datetime.combine(start, time.min))
    end_dt = timezone.make_aware(datetime.combine(end, time.max))
    return start_dt, end_dt


def _channel_bucket() -> dict[str, Any]:
    return {
        "won_revenue": 0.0,
        "won_count": 0,
        "open_value": 0.0,
        "open_count": 0,
        "lost_value": 0.0,
        "lost_count": 0,
        "abandoned_value": 0.0,
        "abandoned_count": 0,
        "spend": 0.0,
        "roas": None,
        "cost_per_won": None,
    }


def summarize_crm_returns(
    location: Location,
    *,
    start_date: date,
    end_date: date,
) -> dict[str, Any]:
    """Aggregate opportunity returns + ROAS vs Meta/Google spend."""
    setup = get_or_create_crm_setup(location)
    start_dt, end_dt = _day_bounds(start_date, end_date)

    # Prefer last_status_change_at for won/lost/abandoned; fall back to created.
    qs = GhlOpportunity.objects.filter(location=location)
    if setup.pipeline_id:
        qs = qs.filter(pipeline_id=setup.pipeline_id)

    # In-range: status change in range OR (no status change date and created in range)
    qs = qs.filter(
        Q(last_status_change_at__gte=start_dt, last_status_change_at__lte=end_dt)
        | Q(
            last_status_change_at__isnull=True,
            ghl_created_at__gte=start_dt,
            ghl_created_at__lte=end_dt,
        )
        | Q(
            last_status_change_at__isnull=True,
            ghl_created_at__isnull=True,
            created_at__gte=start_dt,
            created_at__lte=end_dt,
        )
    )

    facebook = _channel_bucket()
    google = _channel_bucket()
    other = _channel_bucket()
    overall = _channel_bucket()

    buckets = {
        GhlOpportunity.SourceChannel.FACEBOOK: facebook,
        GhlOpportunity.SourceChannel.GOOGLE: google,
        GhlOpportunity.SourceChannel.OTHER: other,
    }

    for row in qs.only("status", "source_channel", "monetary_value"):
        bucket = buckets.get(row.source_channel, other)
        value = float(row.monetary_value or 0)
        if row.status == GhlOpportunity.Status.WON:
            for b in (bucket, overall):
                b["won_revenue"] += value
                b["won_count"] += 1
        elif row.status == GhlOpportunity.Status.OPEN:
            for b in (bucket, overall):
                b["open_value"] += value
                b["open_count"] += 1
        elif row.status == GhlOpportunity.Status.LOST:
            for b in (bucket, overall):
                b["lost_value"] += value
                b["lost_count"] += 1
        elif row.status == GhlOpportunity.Status.ABANDONED:
            for b in (bucket, overall):
                b["abandoned_value"] += value
                b["abandoned_count"] += 1

    meta = summarize_meta_ads(location, start_date=start_date, end_date=end_date)
    google_ads = summarize_google_ads(location, start_date=start_date, end_date=end_date)
    meta_spend = float((meta.get("totals") or {}).get("spend") or 0)
    google_spend = float((google_ads.get("totals") or {}).get("spend") or 0)

    facebook["spend"] = meta_spend
    google["spend"] = google_spend
    overall["spend"] = meta_spend + google_spend

    def _attach_roas(bucket: dict[str, Any]) -> None:
        spend = float(bucket["spend"] or 0)
        won = float(bucket["won_revenue"] or 0)
        won_count = int(bucket["won_count"] or 0)
        bucket["won_revenue"] = round(won, 2)
        bucket["open_value"] = round(float(bucket["open_value"]), 2)
        bucket["lost_value"] = round(float(bucket["lost_value"]), 2)
        bucket["abandoned_value"] = round(float(bucket["abandoned_value"]), 2)
        bucket["spend"] = round(spend, 2)
        bucket["roas"] = round(won / spend, 4) if spend > 0 else None
        bucket["cost_per_won"] = round(spend / won_count, 2) if won_count > 0 else None

    for b in (facebook, google, other, overall):
        _attach_roas(b)

    by_status = {
        row["status"]: {
            "count": row["count"],
            "value": float(row["value"] or 0),
        }
        for row in qs.values("status").annotate(
            count=Count("id"), value=Sum("monetary_value")
        )
    }

    return {
        "location_id": location.ghl_location_id,
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "crm": serialize_crm_setup(setup),
        "overall": overall,
        "facebook": facebook,
        "google": google,
        "other": other,
        "by_status": by_status,
        "opportunity_count": qs.count(),
    }


def list_opportunities(
    location: Location,
    *,
    status: Optional[str] = None,
    source_channel: Optional[str] = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    setup = get_or_create_crm_setup(location)
    qs = GhlOpportunity.objects.filter(location=location)
    if setup.pipeline_id:
        qs = qs.filter(pipeline_id=setup.pipeline_id)
    if status:
        qs = qs.filter(status=status)
    if source_channel:
        qs = qs.filter(source_channel=source_channel)
    qs = qs.order_by("-last_status_change_at", "-ghl_created_at")[: max(1, min(limit, 500))]
    out = []
    for row in qs:
        out.append(
            {
                "id": str(row.id),
                "ghl_opportunity_id": row.ghl_opportunity_id,
                "name": row.name,
                "status": row.status,
                "status_raw": row.status_raw,
                "monetary_value": float(row.monetary_value),
                "source_raw": row.source_raw,
                "source_channel": row.source_channel,
                "pipeline_id": row.pipeline_id,
                "pipeline_stage_id": row.pipeline_stage_id,
                "pipeline_stage_name": row.pipeline_stage_name,
                "ghl_created_at": row.ghl_created_at.isoformat()
                if row.ghl_created_at
                else None,
                "last_status_change_at": row.last_status_change_at.isoformat()
                if row.last_status_change_at
                else None,
            }
        )
    return out
