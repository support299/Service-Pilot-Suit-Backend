"""Sync + query helpers for Google Ads ROI data."""
from __future__ import annotations

import logging
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, Optional

from django.db.models import Case, IntegerField, Max, Sum, Value, When
from django.utils import timezone

from apps.common.exceptions import IntegrationError, ValidationError
from apps.tenancy.models import Location

from ..models import (
    GoogleAdDailyStat,
    GoogleCampaign,
    GooglePeriodSnapshot,
    GoogleSyncState,
)
from .ghl_facebook import resolve_location_access_token
from .ghl_google import GHLGoogleAdsClient

logger = logging.getLogger("apps.roi")

DEFAULT_LOOKBACK_DAYS = 90
RECENT_REFRESH_DAYS = 14
ONBOARD_LOOKBACK_DAYS = 365
SYNC_CHUNK_DAYS = 90

MICROS = Decimal("1000000")


def _to_decimal(value: Any) -> Optional[Decimal]:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None


def _to_int(value: Any) -> int:
    if value is None or value == "":
        return 0
    try:
        return int(Decimal(str(value)))
    except (InvalidOperation, TypeError, ValueError):
        return 0


def _from_micros(value: Any, *, quantize: str = "0.01") -> Decimal:
    raw = _to_decimal(value)
    if raw is None:
        return Decimal("0")
    return (raw / MICROS).quantize(Decimal(quantize))


def _optional_from_micros(value: Any) -> Optional[Decimal]:
    if value is None or value == "":
        return None
    return _from_micros(value, quantize="0.000001")


def _parse_date(value: Any) -> Optional[date]:
    if not value:
        return None
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _safe_div(num: Decimal, den: Decimal) -> Optional[Decimal]:
    if den == 0:
        return None
    return (num / den).quantize(Decimal("0.0001"))


def _customer_id_from_resource(resource_name: Any) -> str:
    text = str(resource_name or "")
    # customers/9396854352 or customers/9396854352/campaigns/…
    parts = text.split("/")
    if len(parts) >= 2 and parts[0] == "customers":
        return parts[1][:64]
    return text[:64]


def _extract_metrics_block(row: dict[str, Any]) -> dict[str, Any]:
    metrics = row.get("metrics")
    if isinstance(metrics, dict):
        return metrics
    return row


def get_or_create_sync_state(location: Location) -> GoogleSyncState:
    state, _ = GoogleSyncState.objects.get_or_create(location=location)
    return state


def _upsert_period_snapshot(
    location: Location,
    *,
    start: date,
    end: date,
    totals: Any,
    synced_at,
) -> None:
    if not isinstance(totals, dict) or not totals:
        return

    impressions = _to_int(totals.get("impressions"))
    clicks = _to_int(totals.get("clicks"))
    if "costMicros" in totals or "cost_micros" in totals:
        spend = _from_micros(totals.get("costMicros") or totals.get("cost_micros"))
    else:
        spend = _to_decimal(totals.get("spend")) or Decimal("0")

    conversions = _to_decimal(totals.get("conversions")) or Decimal("0")

    cpc = _safe_div(spend, Decimal(clicks)) if clicks else _optional_from_micros(
        totals.get("averageCpc") or totals.get("average_cpc")
    )
    cpm = (
        _safe_div(spend * Decimal(1000), Decimal(impressions))
        if impressions
        else _optional_from_micros(totals.get("averageCpm") or totals.get("average_cpm"))
    )
    ctr = (
        _safe_div(Decimal(clicks) * Decimal(100), Decimal(impressions))
        if impressions
        else None
    )
    if ctr is None:
        raw_ctr = _to_decimal(totals.get("ctr"))
        if raw_ctr is not None:
            # GHL returns ratio (0–1); store as percentage for UI parity with Meta.
            ctr = (raw_ctr * Decimal(100)).quantize(Decimal("0.0001")) if raw_ctr <= 1 else raw_ctr

    cost_per_conversion = (
        _safe_div(spend, conversions)
        if conversions
        else _optional_from_micros(
            totals.get("costPerConversion") or totals.get("cost_per_conversion")
        )
    )

    GooglePeriodSnapshot.objects.update_or_create(
        location=location,
        period_start=start,
        period_end=end,
        defaults={
            "impressions": impressions,
            "clicks": clicks,
            "spend": spend,
            "conversions": conversions,
            "cpc": cpc,
            "cpm": cpm,
            "ctr": ctr,
            "cost_per_conversion": cost_per_conversion,
            "raw_totals": totals,
            "synced_at": synced_at,
        },
    )


def sync_location_google_ads(
    location: Location,
    *,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
) -> dict[str, Any]:
    """Pull daily account metrics + campaign list from GHL into the DB."""
    end = end_date or timezone.localdate()
    start = start_date or (end - timedelta(days=max(lookback_days - 1, 0)))
    if start > end:
        raise ValidationError("start_date must be on or before end_date.")

    state = get_or_create_sync_state(location)
    state.status = "syncing"
    state.last_error = ""
    state.save(update_fields=["status", "last_error", "updated_at"])

    token = resolve_location_access_token(location)
    if not token:
        state.status = "error"
        state.last_error = "No GHL access token for this location."
        state.save(update_fields=["status", "last_error", "updated_at"])
        raise IntegrationError(state.last_error, code="missing_ghl_token")

    client = GHLGoogleAdsClient(token)
    ghl_location_id = location.ghl_location_id
    now = timezone.now()

    try:
        reporting = client.get_daily_reporting(
            location_id=ghl_location_id,
            start_date=start,
            end_date=end,
        )
        campaigns_payload = client.list_campaigns(
            location_id=ghl_location_id,
            start_date=start,
            end_date=end,
        )
    except IntegrationError as exc:
        state.status = "error"
        state.last_error = exc.message
        state.save(update_fields=["status", "last_error", "updated_at"])
        raise

    grouped = reporting.get("grouped") if isinstance(reporting, dict) else None
    if not isinstance(grouped, list):
        grouped = []

    days_upserted = 0
    for row in grouped:
        if not isinstance(row, dict):
            continue
        segments = row.get("segments") if isinstance(row.get("segments"), dict) else {}
        day = _parse_date(segments.get("date") or row.get("date") or row.get("dateStart"))
        if day is None:
            continue

        metrics = _extract_metrics_block(row)
        customer = row.get("customer") if isinstance(row.get("customer"), dict) else {}
        impressions = _to_int(metrics.get("impressions"))
        clicks = _to_int(metrics.get("clicks"))
        spend = _from_micros(
            metrics.get("costMicros")
            if "costMicros" in metrics
            else metrics.get("cost_micros")
        )
        conversions = _to_decimal(metrics.get("conversions")) or Decimal("0")

        cpc = _safe_div(spend, Decimal(clicks)) if clicks else _optional_from_micros(
            metrics.get("averageCpc") or metrics.get("average_cpc")
        )
        cpm = (
            _safe_div(spend * Decimal(1000), Decimal(impressions))
            if impressions
            else _optional_from_micros(
                metrics.get("averageCpm") or metrics.get("average_cpm")
            )
        )
        ctr = (
            _safe_div(Decimal(clicks) * Decimal(100), Decimal(impressions))
            if impressions
            else None
        )
        cost_per_conversion = (
            _safe_div(spend, conversions)
            if conversions
            else _optional_from_micros(
                metrics.get("costPerConversion") or metrics.get("cost_per_conversion")
            )
        )

        GoogleAdDailyStat.objects.update_or_create(
            location=location,
            date=day,
            defaults={
                "customer_id": _customer_id_from_resource(customer.get("resourceName")),
                "impressions": impressions,
                "clicks": clicks,
                "spend": spend,
                "conversions": conversions,
                "cpc": cpc,
                "cpm": cpm,
                "ctr": ctr,
                "cost_per_conversion": cost_per_conversion,
                "raw": row,
                "synced_at": now,
            },
        )
        days_upserted += 1

    if isinstance(reporting, dict):
        _upsert_period_snapshot(
            location,
            start=start,
            end=end,
            totals=reporting.get("totals"),
            synced_at=now,
        )

    campaigns_upserted = 0
    for item in campaigns_payload:
        if not isinstance(item, dict):
            continue
        campaign = item.get("campaign") if isinstance(item.get("campaign"), dict) else {}
        metrics = item.get("metrics") if isinstance(item.get("metrics"), dict) else {}
        campaign_id = str(campaign.get("id") or "").strip()
        if not campaign_id:
            # Fallback: parse from resourceName …/campaigns/15788219508
            resource = str(campaign.get("resourceName") or "")
            if "/campaigns/" in resource:
                campaign_id = resource.rsplit("/campaigns/", 1)[-1].strip()
        if not campaign_id:
            continue

        impressions = _to_int(metrics.get("impressions"))
        clicks = _to_int(metrics.get("clicks"))
        spend = _from_micros(
            metrics.get("costMicros")
            if "costMicros" in metrics
            else metrics.get("cost_micros")
        )
        conversions = _to_decimal(metrics.get("conversions")) or Decimal("0")
        cpc = _safe_div(spend, Decimal(clicks)) if clicks else _optional_from_micros(
            metrics.get("averageCpc") or metrics.get("average_cpc")
        )
        cpm = (
            _safe_div(spend * Decimal(1000), Decimal(impressions))
            if impressions
            else _optional_from_micros(
                metrics.get("averageCpm") or metrics.get("average_cpm")
            )
        )
        ctr = (
            _safe_div(Decimal(clicks) * Decimal(100), Decimal(impressions))
            if impressions
            else None
        )
        cost_per_conversion = (
            _safe_div(spend, conversions)
            if conversions
            else _optional_from_micros(
                metrics.get("costPerConversion") or metrics.get("cost_per_conversion")
            )
        )

        GoogleCampaign.objects.update_or_create(
            location=location,
            campaign_id=campaign_id[:64],
            defaults={
                "customer_id": _customer_id_from_resource(campaign.get("resourceName")),
                "name": str(campaign.get("name") or "")[:512],
                "status": str(campaign.get("status") or "")[:64],
                "impressions": impressions,
                "clicks": clicks,
                "spend": spend,
                "conversions": conversions,
                "cpc": cpc,
                "cpm": cpm,
                "ctr": ctr,
                "cost_per_conversion": cost_per_conversion,
                "metrics_start": start,
                "metrics_end": end,
                "raw": item,
                "synced_at": now,
            },
        )
        campaigns_upserted += 1

    state.status = "success"
    state.last_synced_at = now
    state.daily_from = start
    state.daily_to = end
    state.days_upserted = days_upserted
    state.campaigns_upserted = campaigns_upserted
    state.last_error = ""
    state.save()

    result = {
        "location_id": ghl_location_id,
        "daily_from": start.isoformat(),
        "daily_to": end.isoformat(),
        "days_upserted": days_upserted,
        "campaigns_upserted": campaigns_upserted,
        "synced_at": now.isoformat(),
    }
    logger.info("google ads sync ok %s", result)
    return result


def sync_location_google_ads_lookback(
    location: Location,
    *,
    lookback_days: int = ONBOARD_LOOKBACK_DAYS,
    chunk_days: int = SYNC_CHUNK_DAYS,
) -> dict[str, Any]:
    """Backfill daily Google stats in chunks (used after location onboarding)."""
    end = timezone.localdate()
    start = end - timedelta(days=max(lookback_days - 1, 0))
    cursor = start
    days_upserted = 0
    campaigns_upserted = 0
    chunks = 0

    while cursor <= end:
        chunk_end = min(cursor + timedelta(days=max(chunk_days - 1, 0)), end)
        result = sync_location_google_ads(
            location, start_date=cursor, end_date=chunk_end
        )
        days_upserted += int(result.get("days_upserted") or 0)
        campaigns_upserted = max(
            campaigns_upserted, int(result.get("campaigns_upserted") or 0)
        )
        chunks += 1
        cursor = chunk_end + timedelta(days=1)

    out = {
        "location_id": location.ghl_location_id,
        "daily_from": start.isoformat(),
        "daily_to": end.isoformat(),
        "lookback_days": lookback_days,
        "chunks": chunks,
        "days_upserted": days_upserted,
        "campaigns_upserted": campaigns_upserted,
    }
    logger.info("google ads lookback sync ok %s", out)
    return out


def _google_rates(
    *,
    spend: Decimal,
    impressions: int,
    clicks: int,
    conversions: Decimal,
) -> dict[str, float]:
    return {
        "ctr": float(
            _safe_div(Decimal(clicks) * Decimal(100), Decimal(impressions)) or 0
        )
        if impressions
        else 0.0,
        "cpc": float(_safe_div(spend, Decimal(clicks)) or 0),
        "cpm": float(_safe_div(spend * Decimal(1000), Decimal(impressions)) or 0),
        "cost_per_conversion": float(_safe_div(spend, conversions) or 0),
    }


def summarize_google_ads(
    location: Location,
    *,
    start_date: date,
    end_date: date,
) -> dict[str, Any]:
    """Aggregate for a date range.

    Prefer daily row sums when present so KPI cards match charts. Fall back to an
    exact-range GHL snapshot only when no daily rows exist yet.
    """
    qs = GoogleAdDailyStat.objects.filter(
        location=location, date__gte=start_date, date__lte=end_date
    )
    agg = qs.aggregate(
        impressions=Sum("impressions"),
        clicks=Sum("clicks"),
        spend=Sum("spend"),
        conversions=Sum("conversions"),
        last_day=Max("date"),
    )
    day_impressions = int(agg["impressions"] or 0)
    day_clicks = int(agg["clicks"] or 0)
    day_spend = Decimal(agg["spend"] or 0)
    day_conversions = Decimal(agg["conversions"] or 0)
    day_count = qs.count()
    expected_days = (end_date - start_date).days + 1

    snapshot = GooglePeriodSnapshot.objects.filter(
        location=location, period_start=start_date, period_end=end_date
    ).first()

    series_totals = {
        "impressions": day_impressions,
        "clicks": day_clicks,
        "spend": float(day_spend),
        "conversions": float(day_conversions),
        **_google_rates(
            spend=day_spend,
            impressions=day_impressions,
            clicks=day_clicks,
            conversions=day_conversions,
        ),
    }

    ghl_totals = None
    snapshot_synced_at = None
    if snapshot is not None:
        snap_rates = _google_rates(
            spend=snapshot.spend,
            impressions=snapshot.impressions,
            clicks=snapshot.clicks,
            conversions=snapshot.conversions,
        )
        ghl_totals = {
            "impressions": snapshot.impressions,
            "clicks": snapshot.clicks,
            "spend": float(snapshot.spend),
            "conversions": float(snapshot.conversions),
            "ctr": float(snapshot.ctr) if snapshot.ctr is not None else snap_rates["ctr"],
            "cpc": float(snapshot.cpc) if snapshot.cpc is not None else snap_rates["cpc"],
            "cpm": float(snapshot.cpm) if snapshot.cpm is not None else snap_rates["cpm"],
            "cost_per_conversion": (
                float(snapshot.cost_per_conversion)
                if snapshot.cost_per_conversion is not None
                else snap_rates["cost_per_conversion"]
            ),
        }
        snapshot_synced_at = snapshot.synced_at.isoformat()

    if day_count > 0:
        totals = series_totals
        source = "daily_sum"
    elif ghl_totals is not None:
        totals = ghl_totals
        source = "ghl_totals"
    else:
        totals = series_totals
        source = "daily_sum"

    totals_aligned = True
    if ghl_totals is not None and day_count > 0:
        totals_aligned = abs(float(ghl_totals["spend"]) - float(series_totals["spend"])) < 0.05

    state = GoogleSyncState.objects.filter(location=location).first()

    return {
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "days_with_data": day_count,
        "expected_days": expected_days,
        "data_through": agg["last_day"].isoformat() if agg["last_day"] else None,
        "totals_source": source,
        "totals_aligned": totals_aligned,
        "totals": totals,
        "series_totals": series_totals,
        "ghl_totals": ghl_totals,
        "sync": {
            "status": state.status if state else "never",
            "last_synced_at": snapshot_synced_at
            or (
                state.last_synced_at.isoformat()
                if state and state.last_synced_at
                else None
            ),
            "daily_from": state.daily_from.isoformat()
            if state and state.daily_from
            else None,
            "daily_to": state.daily_to.isoformat() if state and state.daily_to else None,
            "last_error": state.last_error if state else "",
            "range_synced_at": snapshot_synced_at,
        },
    }


def list_google_daily_series(
    location: Location,
    *,
    start_date: date,
    end_date: date,
) -> list[dict[str, Any]]:
    rows = (
        GoogleAdDailyStat.objects.filter(
            location=location, date__gte=start_date, date__lte=end_date
        )
        .order_by("date")
        .values(
            "date",
            "impressions",
            "clicks",
            "spend",
            "conversions",
            "cpc",
            "cpm",
            "ctr",
        )
    )
    out: list[dict[str, Any]] = []
    for row in rows:
        out.append(
            {
                "date": row["date"].isoformat(),
                "impressions": row["impressions"],
                "clicks": row["clicks"],
                "spend": float(row["spend"] or 0),
                "conversions": float(row["conversions"] or 0),
                "cpc": float(row["cpc"]) if row["cpc"] is not None else None,
                "cpm": float(row["cpm"]) if row["cpm"] is not None else None,
                "ctr": float(row["ctr"]) if row["ctr"] is not None else None,
            }
        )
    return out


def list_google_campaigns(location: Location) -> list[dict[str, Any]]:
    status_rank = Case(
        When(status__iexact="ENABLED", then=Value(0)),
        When(status__iexact="PAUSED", then=Value(1)),
        default=Value(2),
        output_field=IntegerField(),
    )
    rows = (
        GoogleCampaign.objects.filter(location=location)
        .annotate(_status_rank=status_rank)
        .order_by("_status_rank", "name")
        .values(
            "campaign_id",
            "customer_id",
            "name",
            "status",
            "impressions",
            "clicks",
            "spend",
            "conversions",
            "cpc",
            "cpm",
            "ctr",
            "cost_per_conversion",
            "metrics_start",
            "metrics_end",
            "synced_at",
        )
    )
    out: list[dict[str, Any]] = []
    for row in rows:
        out.append(
            {
                "campaign_id": row["campaign_id"],
                "customer_id": row["customer_id"],
                "name": row["name"],
                "status": row["status"],
                "impressions": row["impressions"],
                "clicks": row["clicks"],
                "spend": float(row["spend"] or 0),
                "conversions": float(row["conversions"] or 0),
                "cpc": float(row["cpc"]) if row["cpc"] is not None else None,
                "cpm": float(row["cpm"]) if row["cpm"] is not None else None,
                "ctr": float(row["ctr"]) if row["ctr"] is not None else None,
                "cost_per_conversion": (
                    float(row["cost_per_conversion"])
                    if row["cost_per_conversion"] is not None
                    else None
                ),
                "metrics_start": row["metrics_start"].isoformat()
                if row["metrics_start"]
                else None,
                "metrics_end": row["metrics_end"].isoformat()
                if row["metrics_end"]
                else None,
                "synced_at": row["synced_at"].isoformat() if row["synced_at"] else None,
            }
        )
    return out
