"""Sync + query helpers for Meta ads ROI data."""
from __future__ import annotations

import logging
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, Optional

from django.db.models import Case, IntegerField, Max, Sum, Value, When
from django.utils import timezone

from apps.common.exceptions import IntegrationError, ValidationError
from apps.tenancy.models import Location

from ..models import MetaAdDailyStat, MetaCampaign, MetaPeriodSnapshot, MetaSyncState
from .ghl_facebook import GHLFacebookAdsClient, resolve_location_access_token

logger = logging.getLogger("apps.roi")

DEFAULT_LOOKBACK_DAYS = 90
RECENT_REFRESH_DAYS = 14
ONBOARD_LOOKBACK_DAYS = 365
# GHL/Meta responses stay manageable when we pull long windows in chunks.
SYNC_CHUNK_DAYS = 90
# Re-pull from GHL when the selected range was synced longer ago than this.
ENSURE_MAX_AGE_SECONDS = 5 * 60


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


def _leads_from_results(results: Any) -> int:
    if not isinstance(results, dict):
        return 0
    for key in ("lead", "onsiteConversion.leadGrouped"):
        if key in results:
            return _to_int(results.get(key))
    return 0


def _leads_from_totals(totals: dict[str, Any]) -> int:
    breakdown = totals.get("resultsBreakdown") or totals.get("results_breakdown")
    if isinstance(breakdown, dict):
        for key in ("lead", "onsiteConversion.leadGrouped"):
            if key in breakdown:
                return _to_int(breakdown.get(key))
    return _to_int(totals.get("conversions"))


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


def get_or_create_sync_state(location: Location) -> MetaSyncState:
    state, _ = MetaSyncState.objects.get_or_create(location=location)
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
    spend = _to_decimal(totals.get("spend")) or Decimal("0")
    conversions = _to_int(totals.get("conversions"))
    leads = _leads_from_totals(totals)

    # Prefer rates recomputed from additive metrics (GHL totals.ctr/cpm can be odd).
    cpc = _safe_div(spend, Decimal(clicks)) if clicks else _to_decimal(totals.get("cpc"))
    cpm = (
        _safe_div(spend * Decimal(1000), Decimal(impressions))
        if impressions
        else _to_decimal(totals.get("cpm"))
    )
    ctr = (
        _safe_div(Decimal(clicks) * Decimal(100), Decimal(impressions))
        if impressions
        else _to_decimal(totals.get("ctr"))
    )
    cpl = _safe_div(spend, Decimal(conversions)) if conversions else None
    cost_per_conversion = (
        _to_decimal(totals.get("costPerConversion") or totals.get("cost_per_conversion"))
        or cpl
    )

    MetaPeriodSnapshot.objects.update_or_create(
        location=location,
        period_start=start,
        period_end=end,
        defaults={
            "impressions": impressions,
            "clicks": clicks,
            "spend": spend,
            "conversions": conversions,
            "leads": leads,
            "cpc": cpc,
            "cpm": cpm,
            "ctr": ctr,
            "cost_per_conversion": cost_per_conversion,
            "raw_totals": totals,
            "synced_at": synced_at,
        },
    )


def sync_location_meta_ads(
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
        raise IntegrationError(
            state.last_error,
            code="missing_ghl_token",
        )

    client = GHLFacebookAdsClient(token)
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
        day = _parse_date(row.get("dateStart") or row.get("dateStop"))
        if day is None:
            continue
        results = row.get("results") if isinstance(row.get("results"), dict) else {}
        MetaAdDailyStat.objects.update_or_create(
            location=location,
            date=day,
            defaults={
                "ad_account_id": str(row.get("accountId") or "")[:64],
                "impressions": _to_int(row.get("impressions")),
                "clicks": _to_int(row.get("clicks")),
                "spend": _to_decimal(row.get("spend")) or Decimal("0"),
                "conversions": _to_int(row.get("conversions")),
                "leads": _leads_from_results(results),
                "cpc": _to_decimal(row.get("cpc")),
                "cpm": _to_decimal(row.get("cpm")),
                "ctr": _to_decimal(row.get("ctr")),
                "reach": _to_int(row.get("reach")) or None,
                "frequency": _to_decimal(row.get("frequency")),
                "cost_per_conversion": _to_decimal(
                    row.get("costPerConversion") or row.get("cost_per_conversion")
                ),
                "results": results,
                "cost_per_result_breakdown": row.get("costPerResultBreakdown")
                if isinstance(row.get("costPerResultBreakdown"), dict)
                else {},
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
        campaign_id = str(item.get("campaignId") or "").strip()
        if not campaign_id:
            continue
        MetaCampaign.objects.update_or_create(
            location=location,
            campaign_id=campaign_id[:64],
            defaults={
                "ad_account_id": str(item.get("adAccountId") or "")[:64],
                "name": str(item.get("name") or "")[:512],
                "status": str(item.get("status") or "")[:64],
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
    logger.info("meta ads sync ok %s", result)
    return result


def sync_location_meta_ads_lookback(
    location: Location,
    *,
    lookback_days: int = ONBOARD_LOOKBACK_DAYS,
    chunk_days: int = SYNC_CHUNK_DAYS,
) -> dict[str, Any]:
    """Backfill daily Meta stats in chunks (used after location onboarding)."""
    end = timezone.localdate()
    start = end - timedelta(days=max(lookback_days - 1, 0))
    cursor = start
    days_upserted = 0
    campaigns_upserted = 0
    chunks = 0

    while cursor <= end:
        chunk_end = min(cursor + timedelta(days=max(chunk_days - 1, 0)), end)
        result = sync_location_meta_ads(
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
    logger.info("meta ads lookback sync ok %s", out)
    return out


def range_needs_refresh(
    location: Location,
    *,
    start_date: date,
    end_date: date,
    max_age_seconds: int = ENSURE_MAX_AGE_SECONDS,
) -> bool:
    """True when we should re-pull this exact range from GHL."""
    snapshot = MetaPeriodSnapshot.objects.filter(
        location=location, period_start=start_date, period_end=end_date
    ).first()
    if snapshot is None:
        return True
    age = (timezone.now() - snapshot.synced_at).total_seconds()
    if age > max_age_seconds:
        return True

    # Also refresh if daily coverage looks thin vs calendar days (common lag).
    day_count = MetaAdDailyStat.objects.filter(
        location=location, date__gte=start_date, date__lte=end_date
    ).count()
    expected = (end_date - start_date).days + 1
    # Allow sparse days (zero-activity days may be omitted by GHL), but if we have
    # a snapshot with spend and almost no daily rows, still ok. Force refresh when
    # snapshot is older than max age (handled above).
    if day_count == 0 and (snapshot.spend or 0) > 0:
        return True
    if expected >= 3 and day_count == 0:
        return True
    return False


def ensure_range_synced(
    location: Location,
    *,
    start_date: date,
    end_date: date,
    force: bool = False,
) -> dict[str, Any]:
    """Make sure the selected date range is freshly pulled from GHL (like GHL UI)."""
    if force or range_needs_refresh(
        location, start_date=start_date, end_date=end_date
    ):
        sync_result = sync_location_meta_ads(
            location, start_date=start_date, end_date=end_date
        )
        refreshed = True
    else:
        sync_result = {
            "location_id": location.ghl_location_id,
            "daily_from": start_date.isoformat(),
            "daily_to": end_date.isoformat(),
            "days_upserted": 0,
            "campaigns_upserted": 0,
            "synced_at": None,
        }
        refreshed = False

    summary = summarize_meta_ads(location, start_date=start_date, end_date=end_date)
    return {
        "refreshed": refreshed,
        "sync": sync_result,
        "summary": summary,
    }


def _meta_rates(
    *,
    spend: Decimal,
    impressions: int,
    clicks: int,
    conversions: int,
    leads: int,
) -> dict[str, float]:
    return {
        "ctr": float(
            _safe_div(Decimal(clicks) * Decimal(100), Decimal(impressions)) or 0
        )
        if impressions
        else 0.0,
        "cpc": float(_safe_div(spend, Decimal(clicks)) or 0),
        "cpm": float(_safe_div(spend * Decimal(1000), Decimal(impressions)) or 0),
        "cost_per_lead": float(_safe_div(spend, Decimal(leads)) or 0),
        "cost_per_conversion": float(_safe_div(spend, Decimal(conversions)) or 0),
    }


def summarize_meta_ads(
    location: Location,
    *,
    start_date: date,
    end_date: date,
) -> dict[str, Any]:
    """Aggregate for a date range.

    Prefer daily row sums when present so KPI cards match charts. Fall back to an
    exact-range GHL snapshot only when no daily rows exist yet.
    """
    qs = MetaAdDailyStat.objects.filter(
        location=location, date__gte=start_date, date__lte=end_date
    )
    agg = qs.aggregate(
        impressions=Sum("impressions"),
        clicks=Sum("clicks"),
        spend=Sum("spend"),
        conversions=Sum("conversions"),
        leads=Sum("leads"),
        last_day=Max("date"),
    )
    day_impressions = int(agg["impressions"] or 0)
    day_clicks = int(agg["clicks"] or 0)
    day_spend = Decimal(agg["spend"] or 0)
    day_conversions = int(agg["conversions"] or 0)
    day_leads = int(agg["leads"] or 0)
    day_count = qs.count()
    expected_days = (end_date - start_date).days + 1

    snapshot = MetaPeriodSnapshot.objects.filter(
        location=location, period_start=start_date, period_end=end_date
    ).first()

    series_totals = {
        "impressions": day_impressions,
        "clicks": day_clicks,
        "spend": float(day_spend),
        "conversions": day_conversions,
        "leads": day_leads,
        **_meta_rates(
            spend=day_spend,
            impressions=day_impressions,
            clicks=day_clicks,
            conversions=day_conversions,
            leads=day_leads,
        ),
    }

    ghl_totals = None
    snapshot_synced_at = None
    if snapshot is not None:
        snap_rates = _meta_rates(
            spend=snapshot.spend,
            impressions=snapshot.impressions,
            clicks=snapshot.clicks,
            conversions=snapshot.conversions,
            leads=snapshot.leads,
        )
        ghl_totals = {
            "impressions": snapshot.impressions,
            "clicks": snapshot.clicks,
            "spend": float(snapshot.spend),
            "conversions": snapshot.conversions,
            "leads": snapshot.leads,
            "ctr": float(snapshot.ctr) if snapshot.ctr is not None else snap_rates["ctr"],
            "cpc": float(snapshot.cpc) if snapshot.cpc is not None else snap_rates["cpc"],
            "cpm": float(snapshot.cpm) if snapshot.cpm is not None else snap_rates["cpm"],
            "cost_per_lead": snap_rates["cost_per_lead"],
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

    state = MetaSyncState.objects.filter(location=location).first()

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


def list_daily_series(
    location: Location,
    *,
    start_date: date,
    end_date: date,
) -> list[dict[str, Any]]:
    rows = (
        MetaAdDailyStat.objects.filter(
            location=location, date__gte=start_date, date__lte=end_date
        )
        .order_by("date")
        .values(
            "date",
            "impressions",
            "clicks",
            "spend",
            "conversions",
            "leads",
            "cpc",
            "cpm",
            "ctr",
            "reach",
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
                "conversions": row["conversions"],
                "leads": row["leads"],
                "cpc": float(row["cpc"]) if row["cpc"] is not None else None,
                "cpm": float(row["cpm"]) if row["cpm"] is not None else None,
                "ctr": float(row["ctr"]) if row["ctr"] is not None else None,
                "reach": row["reach"],
            }
        )
    return out


def list_campaigns(location: Location) -> list[dict[str, Any]]:
    # ACTIVE first, then other statuses, then name.
    status_rank = Case(
        When(status__iexact="ACTIVE", then=Value(0)),
        When(status__iexact="PAUSED", then=Value(1)),
        default=Value(2),
        output_field=IntegerField(),
    )
    return list(
        MetaCampaign.objects.filter(location=location)
        .annotate(_status_rank=status_rank)
        .order_by("_status_rank", "name")
        .values(
            "campaign_id",
            "ad_account_id",
            "name",
            "status",
            "synced_at",
        )
    )
