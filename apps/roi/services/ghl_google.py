"""GoHighLevel Google Ad Publishing API client."""
from __future__ import annotations

import logging
from datetime import date
from typing import Any

import requests
from django.conf import settings

from apps.common.exceptions import IntegrationError

logger = logging.getLogger("apps.roi")

REPORTING_FIELDS = (
    "impressions,clicks,cost_micros,average_cpc,conversions,"
    "average_cpm,cost_per_conversion,ctr"
)


class GHLGoogleAdsClient:
    """Thin HTTP client for GHL Google Ads reporting endpoints."""

    def __init__(self, access_token: str) -> None:
        self.access_token = (access_token or "").strip()
        if not self.access_token:
            raise IntegrationError(
                "No GoHighLevel access token available for this location.",
                code="missing_ghl_token",
            )
        self.base_url = settings.GHL["API_BASE_URL"].rstrip("/")
        self.version = settings.GHL["API_VERSION"]

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.access_token}",
            "Version": self.version,
            "Accept": "application/json",
        }

    def _get(self, path: str, params: dict[str, Any]) -> Any:
        url = f"{self.base_url}{path}"
        try:
            response = requests.get(
                url, headers=self._headers(), params=params, timeout=60
            )
        except requests.RequestException as exc:
            logger.exception("GHL Google Ads request failed path=%s", path)
            raise IntegrationError(
                "Failed to reach GoHighLevel Google Ad Publishing API.",
                code="ghl_network_error",
                details={"path": path, "error": str(exc)},
            ) from exc

        if response.status_code >= 400:
            logger.warning(
                "GHL Google Ads error path=%s status=%s body=%s",
                path,
                response.status_code,
                response.text[:500],
            )
            raise IntegrationError(
                "GoHighLevel Google Ad Publishing API returned an error.",
                code="ghl_api_error",
                details={
                    "path": path,
                    "status": response.status_code,
                    "body": response.text[:1000],
                },
            )

        if not response.content:
            return {}
        try:
            return response.json()
        except ValueError as exc:
            raise IntegrationError(
                "GoHighLevel returned a non-JSON response.",
                code="ghl_invalid_json",
                details={"path": path},
            ) from exc

    def get_daily_reporting(
        self,
        *,
        location_id: str,
        start_date: date,
        end_date: date,
        report_type: str = "INTEGRATION",
    ) -> dict[str, Any]:
        """Account-level metrics grouped by date."""
        return self._get(
            "/ad-publishing/google/reporting",
            {
                "locationId": location_id,
                "fields": REPORTING_FIELDS,
                "groupBy": "date",
                "startDate": start_date.isoformat(),
                "endDate": end_date.isoformat(),
                "type": report_type,
            },
        )

    def list_campaigns(
        self,
        *,
        location_id: str,
        start_date: date,
        end_date: date,
        report_type: str = "INTEGRATION",
    ) -> list[dict[str, Any]]:
        """Campaign list with metrics for the selected window."""
        payload = self._get(
            "/ad-publishing/google/reporting/list",
            {
                "locationId": location_id,
                "listType": "campaigns",
                "startDate": start_date.isoformat(),
                "endDate": end_date.isoformat(),
                "type": report_type,
            },
        )
        if isinstance(payload, list):
            return payload
        if isinstance(payload, dict):
            for key in ("campaigns", "data", "results", "list", "grouped"):
                value = payload.get(key)
                if isinstance(value, list):
                    return value
        return []
