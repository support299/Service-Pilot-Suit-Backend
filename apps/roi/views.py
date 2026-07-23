"""ROI Center API endpoints — all reads from DB; sync pulls from GHL."""
from __future__ import annotations

from datetime import date, timedelta

from django.utils import timezone
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

from apps.common.exceptions import ValidationError
from apps.common.responses import ok
from apps.rbac.constants import Permissions
from apps.rbac.permissions import (
    HasPermission,
    HasTenantContext,
    IsTenantMember,
    effective_permissions,
)

from .services.google_sync import (
    list_google_campaigns,
    list_google_daily_series,
    summarize_google_ads,
    sync_location_google_ads,
)
from .services.meta_sync import (
    list_campaigns,
    list_daily_series,
    summarize_meta_ads,
    sync_location_meta_ads,
)
from .services.crm_sync import (
    discover_pipelines,
    get_or_create_crm_setup,
    list_opportunities,
    save_crm_pipeline,
    serialize_crm_setup,
    summarize_crm_returns,
    sync_location_opportunities,
)
from .tasks import (
    sync_location_google_ads_task,
    sync_location_meta_ads_task,
    sync_location_opportunities_task,
)


def _parse_date_param(raw: str | None, *, field: str) -> date | None:
    if not raw:
        return None
    try:
        return date.fromisoformat(raw[:10])
    except ValueError as exc:
        raise ValidationError(f"Invalid {field}. Use YYYY-MM-DD.") from exc


def _range_from_request(request) -> tuple[date, date]:
    end = _parse_date_param(request.query_params.get("end_date"), field="end_date")
    start = _parse_date_param(request.query_params.get("start_date"), field="start_date")
    today = timezone.localdate()
    if end is None:
        end = today
    if start is None:
        start = end - timedelta(days=29)
    if start > end:
        raise ValidationError("start_date must be on or before end_date.")
    return start, end


class MetaSummaryView(APIView):
    """Aggregated Meta KPIs for the current location + date range (DB)."""

    permission_classes = [
        IsAuthenticated,
        HasTenantContext,
        IsTenantMember,
        HasPermission.require(Permissions.REPORT_VIEW),
    ]

    def get(self, request):
        start, end = _range_from_request(request)
        data = summarize_meta_ads(request.location, start_date=start, end_date=end)
        data["location_id"] = request.location.ghl_location_id
        return ok(data)


class MetaDailyView(APIView):
    """Day-by-day series for charts (DB)."""

    permission_classes = [
        IsAuthenticated,
        HasTenantContext,
        IsTenantMember,
        HasPermission.require(Permissions.REPORT_VIEW),
    ]

    def get(self, request):
        start, end = _range_from_request(request)
        series = list_daily_series(request.location, start_date=start, end_date=end)
        return ok(
            {
                "location_id": request.location.ghl_location_id,
                "start_date": start.isoformat(),
                "end_date": end.isoformat(),
                "results": series,
            }
        )


class MetaCampaignsView(APIView):
    """Campaign catalog for the current location (DB)."""

    permission_classes = [
        IsAuthenticated,
        HasTenantContext,
        IsTenantMember,
        HasPermission.require(Permissions.REPORT_VIEW),
    ]

    def get(self, request):
        rows = list_campaigns(request.location)
        for row in rows:
            synced = row.get("synced_at")
            if synced is not None:
                row["synced_at"] = synced.isoformat()
        return ok(
            {
                "location_id": request.location.ghl_location_id,
                "count": len(rows),
                "results": rows,
            }
        )


class MetaSyncView(APIView):
    """Manual sync — pulls from GHL into DB for the current location."""

    permission_classes = [
        IsAuthenticated,
        HasTenantContext,
        IsTenantMember,
        HasPermission.require(Permissions.REPORT_MANAGE),
    ]

    def post(self, request):
        async_mode = str(request.data.get("async", "")).lower() in ("1", "true", "yes")
        start = _parse_date_param(request.data.get("start_date"), field="start_date")
        end = _parse_date_param(request.data.get("end_date"), field="end_date")

        location = request.location
        if async_mode:
            sync_location_meta_ads_task.delay(
                str(location.id),
                start.isoformat() if start else None,
                end.isoformat() if end else None,
            )
            return ok({"queued": True, "location_id": location.ghl_location_id})

        result = sync_location_meta_ads(
            location, start_date=start, end_date=end
        )
        return ok(result)


class GoogleSummaryView(APIView):
    """Aggregated Google Ads KPIs for the current location + date range (DB)."""

    permission_classes = [
        IsAuthenticated,
        HasTenantContext,
        IsTenantMember,
        HasPermission.require(Permissions.REPORT_VIEW),
    ]

    def get(self, request):
        start, end = _range_from_request(request)
        data = summarize_google_ads(request.location, start_date=start, end_date=end)
        data["location_id"] = request.location.ghl_location_id
        return ok(data)


class GoogleDailyView(APIView):
    """Day-by-day Google series for charts (DB)."""

    permission_classes = [
        IsAuthenticated,
        HasTenantContext,
        IsTenantMember,
        HasPermission.require(Permissions.REPORT_VIEW),
    ]

    def get(self, request):
        start, end = _range_from_request(request)
        series = list_google_daily_series(
            request.location, start_date=start, end_date=end
        )
        return ok(
            {
                "location_id": request.location.ghl_location_id,
                "start_date": start.isoformat(),
                "end_date": end.isoformat(),
                "results": series,
            }
        )


class GoogleCampaignsView(APIView):
    """Google campaign list with last-synced range metrics (DB)."""

    permission_classes = [
        IsAuthenticated,
        HasTenantContext,
        IsTenantMember,
        HasPermission.require(Permissions.REPORT_VIEW),
    ]

    def get(self, request):
        rows = list_google_campaigns(request.location)
        return ok(
            {
                "location_id": request.location.ghl_location_id,
                "count": len(rows),
                "results": rows,
            }
        )


class GoogleSyncView(APIView):
    """Manual Google Ads sync — pulls from GHL into DB."""

    permission_classes = [
        IsAuthenticated,
        HasTenantContext,
        IsTenantMember,
        HasPermission.require(Permissions.REPORT_MANAGE),
    ]

    def post(self, request):
        async_mode = str(request.data.get("async", "")).lower() in ("1", "true", "yes")
        start = _parse_date_param(request.data.get("start_date"), field="start_date")
        end = _parse_date_param(request.data.get("end_date"), field="end_date")

        location = request.location
        if async_mode:
            sync_location_google_ads_task.delay(
                str(location.id),
                start.isoformat() if start else None,
                end.isoformat() if end else None,
            )
            return ok({"queued": True, "location_id": location.ghl_location_id})

        result = sync_location_google_ads(
            location, start_date=start, end_date=end
        )
        return ok(result)


class CrmSetupView(APIView):
    """Discover pipelines + current CRM setup, or save selected pipeline."""

    permission_classes = [
        IsAuthenticated,
        HasTenantContext,
        IsTenantMember,
        HasPermission.require(Permissions.REPORT_VIEW),
    ]

    def get(self, request):
        discover = str(request.query_params.get("discover", "1")).lower() not in (
            "0",
            "false",
            "no",
        )
        if discover:
            return ok(discover_pipelines(request.location))
        setup = get_or_create_crm_setup(request.location)
        return ok(serialize_crm_setup(setup))

    def post(self, request):
        # Saving setup requires manage.
        perms = effective_permissions(request)
        if (
            Permissions.REPORT_MANAGE not in perms
            and not getattr(request.user, "is_superuser", False)
        ):
            from apps.common.exceptions import PermissionDeniedError

            raise PermissionDeniedError("You need report.manage to change CRM setup.")

        data = save_crm_pipeline(
            request.location,
            pipeline_id=str(request.data.get("pipeline_id") or ""),
            pipeline_name=str(request.data.get("pipeline_name") or ""),
        )
        # Kick off opportunity sync after confirming pipeline.
        async_mode = str(request.data.get("sync", "1")).lower() not in (
            "0",
            "false",
            "no",
        )
        if async_mode:
            try:
                sync_location_opportunities(request.location)
                data = {**data, **serialize_crm_setup(get_or_create_crm_setup(request.location)), "synced": True}
            except Exception:
                # Fall back to async if sync is slow/fails mid-request.
                sync_location_opportunities_task.delay(str(request.location.id))
                data = {**data, "sync_queued": True}
        return ok(data)


class CrmReturnsSummaryView(APIView):
    """Won revenue + ROAS from synced opportunities vs ad spend."""

    permission_classes = [
        IsAuthenticated,
        HasTenantContext,
        IsTenantMember,
        HasPermission.require(Permissions.REPORT_VIEW),
    ]

    def get(self, request):
        start, end = _range_from_request(request)
        data = summarize_crm_returns(
            request.location, start_date=start, end_date=end
        )
        return ok(data)


class CrmOpportunityListView(APIView):
    permission_classes = [
        IsAuthenticated,
        HasTenantContext,
        IsTenantMember,
        HasPermission.require(Permissions.REPORT_VIEW),
    ]

    def get(self, request):
        limit_raw = request.query_params.get("limit") or "100"
        try:
            limit = int(limit_raw)
        except ValueError:
            limit = 100
        rows = list_opportunities(
            request.location,
            status=request.query_params.get("status"),
            source_channel=request.query_params.get("source"),
            limit=limit,
        )
        return ok(
            {
                "location_id": request.location.ghl_location_id,
                "count": len(rows),
                "results": rows,
            }
        )


class CrmOpportunitySyncView(APIView):
    permission_classes = [
        IsAuthenticated,
        HasTenantContext,
        IsTenantMember,
        HasPermission.require(Permissions.REPORT_MANAGE),
    ]

    def post(self, request):
        async_mode = str(request.data.get("async", "")).lower() in ("1", "true", "yes")
        location = request.location
        if async_mode:
            sync_location_opportunities_task.delay(str(location.id))
            return ok({"queued": True, "location_id": location.ghl_location_id})
        return ok(sync_location_opportunities(location))
