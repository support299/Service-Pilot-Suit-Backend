"""GoHighLevel Marketplace OAuth service.

Handles the agency/location onboarding flow (mirrors Snapshot JobTracker):
    authorize → chooselocation → callback(code) → exchange →
    (optional company-level installedLocations + locationToken) →
    persist Agency/Location tokens → sync users.
"""
from __future__ import annotations

import logging
from typing import Any
from urllib.parse import quote, urlencode

import requests
from django.conf import settings
from django.utils import timezone

from apps.common.exceptions import IntegrationError
from apps.rbac.constants import Roles
from apps.tenancy.models import Location
from apps.tenancy.repositories import LocationRepository
from apps.tenancy.services import ProvisioningService

from .oauth_session import create_oauth_login_code
from .user_sync import sync_location_users, upsert_user_from_ghl

logger = logging.getLogger("apps.authentication")

MARKETPLACE_BASE_URL = "https://marketplace.gohighlevel.com"
CHOOSELOCATION_PATH = "/v2/oauth/chooselocation"
TOKEN_PATH = "/oauth/token"
LOCATION_TOKEN_PATH = "/oauth/locationToken"
INSTALLED_LOCATIONS_PATH = "/oauth/installedLocations"


class GHLOAuthService:
    def __init__(self) -> None:
        cfg = settings.GHL
        self.client_id: str = cfg["CLIENT_ID"]
        self.client_secret: str = cfg["CLIENT_SECRET"]
        self.redirect_uri: str = cfg["REDIRECT_URI"]
        self.scopes: str = cfg["SCOPES"]
        self.version_id: str = cfg["VERSION_ID"]
        self.api_base: str = cfg["API_BASE_URL"]
        self.api_version: str = cfg["API_VERSION"]

    # ── Step 1: authorize ────────────────────────────────────────
    def build_authorize_url(
        self, *, redirect_uri: str | None = None, state: str | None = None
    ) -> str:
        """Build the marketplace ``chooselocation`` URL."""
        if not self.client_id:
            raise IntegrationError("GHL_CLIENT_ID is not configured.")
        params: dict[str, str] = {
            "response_type": "code",
            "redirect_uri": redirect_uri or self.redirect_uri,
            "client_id": self.client_id,
            "scope": self.scopes,
        }
        if self.version_id:
            params["version_id"] = self.version_id
        if state:
            params["state"] = state
        return (
            f"{MARKETPLACE_BASE_URL}{CHOOSELOCATION_PATH}?"
            f"{urlencode(params, quote_via=quote)}"
        )

    # ── Step 2: exchange code for tokens ─────────────────────────
    def exchange_code(self, code: str, *, redirect_uri: str | None = None) -> dict[str, Any]:
        if not self.client_secret:
            raise IntegrationError(
                "GHL_CLIENT_SECRET is not configured. "
                "Paste it into backend/.env from your GHL Marketplace app settings."
            )
        data = {
            "grant_type": "authorization_code",
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "redirect_uri": redirect_uri or self.redirect_uri,
            "code": code,
        }
        try:
            resp = requests.post(f"{self.api_base}{TOKEN_PATH}", data=data, timeout=30)
        except requests.RequestException as exc:
            logger.exception("GHL token exchange request failed")
            raise IntegrationError("Could not reach GoHighLevel to exchange the code.") from exc

        payload = _safe_json(resp)
        if not resp.ok or payload.get("error"):
            detail = payload.get("error_description") or payload.get("error") or resp.text[:400]
            logger.warning("GHL token exchange failed: %s", detail)
            raise IntegrationError(
                "GoHighLevel token exchange failed.", details={"detail": detail}
            )
        return payload

    def refresh_token(self, refresh_token: str) -> dict[str, Any]:
        data = {
            "grant_type": "refresh_token",
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "refresh_token": refresh_token,
        }
        resp = requests.post(f"{self.api_base}{TOKEN_PATH}", data=data, timeout=30)
        payload = _safe_json(resp)
        if not resp.ok or payload.get("error"):
            detail = payload.get("error_description") or payload.get("error") or resp.text[:400]
            raise IntegrationError("GHL token refresh failed.", details={"detail": detail})
        return payload

    def exchange_location_token(
        self, *, company_id: str, company_token: str, location_id: str
    ) -> dict[str, Any]:
        resp = requests.post(
            f"{self.api_base}{LOCATION_TOKEN_PATH}",
            data={"companyId": company_id, "locationId": location_id},
            headers={
                "Authorization": f"Bearer {company_token}",
                "Version": self.api_version,
                "Accept": "application/json",
            },
            timeout=30,
        )
        payload = _safe_json(resp)
        if not resp.ok:
            raise IntegrationError(
                f"locationToken failed for {location_id}",
                details={"detail": resp.text[:400]},
            )
        payload.setdefault("locationId", location_id)
        payload.setdefault("companyId", company_id)
        return payload

    def fetch_installed_locations(
        self, *, company_id: str, company_token: str
    ) -> list[dict[str, Any]]:
        app_id = (self.client_id.split("-")[0] if self.client_id else "").strip()
        if not app_id:
            raise IntegrationError("GHL client id is not configured.")
        resp = requests.get(
            f"{self.api_base}{INSTALLED_LOCATIONS_PATH}",
            params={"companyId": company_id, "appId": app_id},
            headers={
                "Authorization": f"Bearer {company_token}",
                "Version": self.api_version,
                "Accept": "application/json",
            },
            timeout=30,
        )
        if not resp.ok:
            raise IntegrationError(
                "Failed to fetch installed locations from GHL.",
                details={"detail": resp.text[:400]},
            )
        return (_safe_json(resp).get("locations") or [])

    def fetch_user(self, *, access_token: str, user_id: str) -> dict[str, Any]:
        """Fetch a GHL user by id (best-effort)."""
        user_id = (user_id or "").strip()
        if not user_id or not access_token:
            return {}
        try:
            resp = requests.get(
                f"{self.api_base}/users/{user_id}",
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Version": self.api_version,
                    "Accept": "application/json",
                },
                timeout=20,
            )
            if resp.ok:
                data = _safe_json(resp)
                return data.get("user") or data or {}
        except requests.RequestException:
            logger.info("GHL user fetch failed for user_id=%s", user_id)
        return {}

    def fetch_location_details(self, *, access_token: str, location_id: str) -> dict[str, Any]:
        try:
            resp = requests.get(
                f"{self.api_base}/locations/{location_id}",
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Version": self.api_version,
                },
                timeout=20,
            )
            if resp.ok:
                return _safe_json(resp).get("location", {}) or {}
        except requests.RequestException:
            logger.info("GHL location detail fetch failed for %s", location_id)
        return {}

    # ── Step 3: onboard ──────────────────────────────────────────
    def onboard_from_token_payload(
        self,
        payload: dict[str, Any],
        *,
        initiated_by_user_id: str | None = None,
    ) -> dict[str, Any]:
        """Persist agency/location tokens, then sync users.

        Supports both:
        - location-level OAuth (payload contains ``locationId``)
        - company-level OAuth (no locationId → installedLocations + locationToken)

        ``initiated_by_user_id`` is the Suite user who clicked Onboard (from OAuth
        ``state``). They always receive Agency Admin on every connected location so
        the new location shows up in their switcher.
        """
        company_id = (payload.get("companyId") or "").strip()
        location_id = (payload.get("locationId") or "").strip()
        company_token = payload.get("access_token") or ""
        company_level = not location_id and bool(company_id)

        agency = None
        if company_id:
            agency = ProvisioningService.upsert_agency(
                company_id=company_id,
                tokens=payload if company_level or not location_id else None,
            )
            # Always store company tokens when present so beat refresh works.
            if company_token and payload.get("refresh_token"):
                agency = ProvisioningService.upsert_agency(
                    company_id=company_id, tokens=payload
                )

        connected: list[str] = []
        primary: dict[str, Any] | None = None
        primary_location_id = ""

        if company_level:
            try:
                locations = self.fetch_installed_locations(
                    company_id=company_id, company_token=company_token
                )
            except Exception as exc:
                logger.exception("installedLocations failed company_id=%s", company_id)
                raise IntegrationError(
                    f"Failed to fetch installed locations from GHL: {exc}"
                ) from exc

            if not locations:
                raise IntegrationError(
                    "Bulk install returned no approved subaccounts. "
                    "Open the app from a subaccount and try again."
                )

            for loc in locations:
                loc_id = (loc.get("_id") or loc.get("id") or "").strip()
                if not loc_id:
                    continue
                try:
                    loc_tokens = self.exchange_location_token(
                        company_id=company_id,
                        company_token=company_token,
                        location_id=loc_id,
                    )
                    self._persist_and_bootstrap(
                        loc_tokens, agency=agency, company_id=company_id
                    )
                    connected.append(loc_id)
                    if primary is None:
                        primary = loc_tokens
                        primary_location_id = loc_id
                except Exception:
                    logger.exception(
                        "Skipped locationToken exchange location_id=%s", loc_id
                    )

            if not primary or not primary_location_id:
                raise IntegrationError(
                    "OAuth succeeded, but no approved subaccount token could be created."
                )
        else:
            if not location_id:
                raise IntegrationError(
                    "OAuth succeeded but GoHighLevel returned no locationId. "
                    "Open the app from a sub-account and retry."
                )
            self._persist_and_bootstrap(
                payload, agency=agency, company_id=company_id
            )
            connected.append(location_id)
            primary = payload
            primary_location_id = location_id

        details = self.fetch_location_details(
            access_token=primary.get("access_token") or "",
            location_id=primary_location_id,
        )

        # Prefer the Suite user who started onboarding (so they keep their session
        # identity and immediately see the new location). Fall back to the GHL installer.
        login_user = self._grant_initiator_access(
            user_id=initiated_by_user_id,
            location_ids=connected,
        )
        if login_user is None:
            login_user = self._ensure_installer_user(
                token_payload=primary,
                company_token=company_token if company_level else (primary.get("access_token") or ""),
                location_id=primary_location_id,
                company_id=company_id,
            )

        login_code = ""
        if login_user is not None:
            login_code = create_oauth_login_code(
                user_id=login_user.pk, location_id=primary_location_id
            )

        # Kick off 1-year Meta + Google ads backfill in Celery (non-blocking).
        try:
            from apps.roi.tasks import (
                enqueue_onboard_google_ads_sync,
                enqueue_onboard_meta_ads_sync,
            )

            enqueue_onboard_meta_ads_sync(connected)
            enqueue_onboard_google_ads_sync(connected)
        except Exception:
            logger.exception(
                "Failed to enqueue ads onboard sync locations=%s", connected
            )

        # Ensure GHL media folders (Support Media, …) for each connected location.
        try:
            from apps.tenancy.models import Location
            from apps.tenancy.services.ghl_media import (
                ensure_location_onboard_media_folders,
            )

            for loc_id in connected:
                loc = (
                    Location.objects.select_related("agency")
                    .filter(ghl_location_id=loc_id, is_active=True)
                    .first()
                )
                if loc is None:
                    continue
                ensure_location_onboard_media_folders(loc)
        except Exception:
            logger.exception(
                "Failed to ensure GHL media folders locations=%s", connected
            )

        return {
            "company_id": company_id,
            "location_id": primary_location_id,
            "location_name": details.get("name", ""),
            "connected_location_ids": ",".join(connected),
            "connected_locations": len(connected),
            "company_level_oauth": str(company_level).lower(),
            "login_code": login_code,
        }

    def _grant_initiator_access(self, *, user_id: str | None, location_ids: list[str]):
        """Give the Suite user who clicked Onboard Agency Admin on each location."""
        from django.contrib.auth import get_user_model

        User = get_user_model()
        user_id = (user_id or "").strip()
        if not user_id or not location_ids:
            return None
        try:
            user = User.objects.get(pk=user_id, is_active=True)
        except (User.DoesNotExist, ValueError):
            logger.warning("OAuth state user_id=%s not found", user_id)
            return None

        for loc_id in location_ids:
            location = LocationRepository.get_by_location_id(loc_id)
            if location is None:
                continue
            ProvisioningService.assign_membership_by_slug(
                user=user, location=location, role_slug=Roles.AGENCY_ADMIN
            )
            logger.info(
                "Granted initiator %s agency_admin on location=%s",
                user.email,
                loc_id,
            )
        return user

    def _ensure_installer_user(
        self,
        *,
        token_payload: dict[str, Any],
        company_token: str,
        location_id: str,
        company_id: str,
    ):
        """Upsert the GHL user who installed the app as Agency Admin on the location."""
        ghl_user_id = (
            token_payload.get("userId")
            or token_payload.get("user_id")
            or ""
        ).strip()
        access = (token_payload.get("access_token") or company_token or "").strip()
        location = LocationRepository.get_by_location_id(location_id)
        if location is None:
            return None

        user_data: dict[str, Any] = {}
        if ghl_user_id and access:
            user_data = self.fetch_user(access_token=access, user_id=ghl_user_id)
            # Agency token sometimes needed for agency-level users.
            if not user_data and company_token and company_token != access:
                user_data = self.fetch_user(access_token=company_token, user_id=ghl_user_id)

        if not user_data and ghl_user_id:
            user_data = {
                "id": ghl_user_id,
                "email": "",
                "roles": {"type": "agency", "role": "admin"},
                "companyId": company_id,
            }

        if not user_data:
            logger.warning(
                "No installer userId on OAuth payload; cannot auto-login after onboard"
            )
            return None

        # Force agency-admin for the installer.
        roles = dict(user_data.get("roles") or {})
        roles.setdefault("type", "agency")
        roles.setdefault("role", "admin")
        user_data["roles"] = roles
        if company_id and not user_data.get("companyId"):
            user_data["companyId"] = company_id

        try:
            user = upsert_user_from_ghl(user_data, location=location)
            ProvisioningService.assign_membership_by_slug(
                user=user, location=location, role_slug=Roles.AGENCY_ADMIN
            )
            # Also grant agency_admin on every connected location we just onboarded.
            for loc in Location.objects.filter(
                agency__ghl_company_id=company_id, is_active=True
            ) if company_id else Location.objects.filter(pk=location.pk):
                ProvisioningService.assign_membership_by_slug(
                    user=user, location=loc, role_slug=Roles.AGENCY_ADMIN
                )
            return user
        except Exception:
            logger.exception("Failed to provision installer user ghl_user_id=%s", ghl_user_id)
            return None

    def _persist_and_bootstrap(
        self,
        token_payload: dict[str, Any],
        *,
        agency,
        company_id: str,
    ) -> None:
        location_id = (token_payload.get("locationId") or "").strip()
        access_token = token_payload.get("access_token") or ""
        details = self.fetch_location_details(
            access_token=access_token, location_id=location_id
        )
        if agency is None and company_id:
            agency = ProvisioningService.upsert_agency(company_id=company_id)

        location = ProvisioningService.upsert_location(
            location_id=location_id,
            name=details.get("name", ""),
            agency=agency,
            timezone_name=details.get("timezone", "") or "",
            tokens=token_payload,
        )
        # Sync users immediately (also scheduled via Celery for resilience).
        try:
            sync_location_users(location=location, access_token=access_token)
        except Exception:
            logger.exception("User sync failed location_id=%s", location_id)

        location.last_sync_at = timezone.now()
        location.save(update_fields=["last_sync_at", "updated_at"])
        logger.info("Onboarded location=%s company=%s", location_id, company_id or "-")


def _safe_json(resp: requests.Response) -> dict[str, Any]:
    try:
        return resp.json() or {}
    except ValueError:
        return {}
