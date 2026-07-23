"""Sync GoHighLevel users into local User + Membership rows.

Mirrors the Snapshot JobTracker ``sync_all_users_to_db`` flow, adapted to our
Membership-based RBAC model.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

import requests
from django.conf import settings
from django.contrib.auth import get_user_model

from apps.rbac.constants import Roles
from apps.tenancy.models import Location
from apps.tenancy.services import ProvisioningService

logger = logging.getLogger("apps.authentication")
User = get_user_model()


def extract_ghl_user_metadata(user_data: dict[str, Any]) -> dict[str, Any]:
    """Extract agency/account metadata from a GHL user payload."""
    roles = user_data.get("roles") or {}
    user_type = (roles.get("type") or user_data.get("type") or "").strip().lower()
    location_ids = roles.get("locationIds") or user_data.get("locationIds") or []
    if isinstance(location_ids, str):
        location_ids = [location_ids]
    company_id = (
        (user_data.get("companyId") or roles.get("companyId") or "").strip() or None
    )
    return {
        "ghl_user_type": user_type or "",
        "ghl_location_ids": [str(x) for x in location_ids if x],
        "ghl_restrict_sub_account": bool(roles.get("restrictSubAccount")),
        "ghl_company_id": company_id or "",
    }


def map_ghl_user_to_role_slug(user_data: dict[str, Any]) -> str:
    """Map a GHL user payload onto our RBAC role slugs.

    Snapshot mapping (agency/supervisor/worker) → our catalog:
      agency (+ admin) → agency_admin
      location admin   → manager
      everyone else    → staff
    """
    roles = user_data.get("roles") or {}
    user_type = (roles.get("type") or user_data.get("type") or "").strip().lower()
    ghl_role = (roles.get("role") or "").strip().lower()

    if user_type == "agency":
        return Roles.AGENCY_ADMIN
    if ghl_role == "admin":
        return Roles.MANAGER
    return Roles.STAFF


def ghl_user_has_location_access(user_data: dict[str, Any], location_id: str) -> bool:
    roles = user_data.get("roles") or {}
    user_type = (roles.get("type") or user_data.get("type") or "").strip().lower()
    location_ids = roles.get("locationIds") or user_data.get("locationIds") or []
    if isinstance(location_ids, str):
        location_ids = [location_ids]

    if user_type == "agency":
        if roles.get("restrictSubAccount"):
            return location_id in [str(x) for x in location_ids if x]
        return True
    return location_id in [str(x) for x in location_ids if x] or not location_ids


def _paginate_users_search(
    *,
    access_token: str,
    company_id: str,
    extra_params: Optional[dict[str, str]] = None,
) -> list[dict[str, Any]]:
    api_base = settings.GHL["API_BASE_URL"]
    api_version = settings.GHL["API_VERSION"]
    collected: list[dict[str, Any]] = []
    skip = 0
    page_size = 100

    while True:
        params: dict[str, Any] = {
            "companyId": company_id,
            "limit": page_size,
            "skip": skip,
        }
        if extra_params:
            params.update(extra_params)
        resp = requests.get(
            f"{api_base}/users/search",
            params=params,
            headers={
                "Authorization": f"Bearer {access_token}",
                "Version": api_version,
                "Accept": "application/json",
            },
            timeout=30,
        )
        resp.raise_for_status()
        payload = resp.json() or {}
        batch = payload.get("users") or payload.get("data") or []
        if not isinstance(batch, list):
            break
        collected.extend(batch)
        if len(batch) < page_size:
            break
        skip += page_size
    return collected


def fetch_users_for_location(
    *,
    location: Location,
    access_token: str,
) -> list[dict[str, Any]]:
    """Fetch GHL users who can access ``location`` (account + agency users)."""
    company_id = ""
    if location.agency_id:
        company_id = (location.agency.ghl_company_id or "").strip()
    if not company_id:
        raise ValueError(
            f"company_id is required for users/search; none for location={location.ghl_location_id}"
        )

    # Prefer agency-level token when available (returns agency users).
    search_token = (access_token or "").strip()
    agency = location.agency
    if agency and (agency.access_token or "").strip():
        search_token = agency.access_token.strip()

    by_id: dict[str, dict[str, Any]] = {}

    def _merge(rows: list[dict[str, Any]]) -> None:
        for row in rows:
            uid = row.get("id")
            if uid:
                by_id[str(uid)] = row

    company_users = _paginate_users_search(
        access_token=search_token, company_id=company_id
    )
    for row in company_users:
        if ghl_user_has_location_access(row, location.ghl_location_id):
            _merge([row])

    location_users = _paginate_users_search(
        access_token=search_token,
        company_id=company_id,
        extra_params={"locationId": location.ghl_location_id},
    )
    _merge(location_users)

    agency_users = _paginate_users_search(
        access_token=search_token,
        company_id=company_id,
        extra_params={"type": "agency"},
    )
    for row in agency_users:
        if ghl_user_has_location_access(row, location.ghl_location_id):
            _merge([row])

    logger.info(
        "Fetched %s GHL users for location=%s (company=%s location_filter=%s agency=%s)",
        len(by_id),
        location.ghl_location_id,
        len(company_users),
        len(location_users),
        len(agency_users),
    )
    return list(by_id.values())


def upsert_user_from_ghl(user_data: dict[str, Any], *, location: Location) -> User:
    """Create/update a User from a GHL payload and assign a Membership."""
    if "user" in user_data and isinstance(user_data["user"], dict):
        user_data = user_data["user"]

    ghl_user_id = (user_data.get("id") or "").strip() or None
    email = (user_data.get("email") or "").strip().lower()
    if not email and not ghl_user_id:
        raise ValueError("GHL user payload missing email and id")

    metadata = extract_ghl_user_metadata(user_data)
    if not metadata.get("ghl_company_id") and location.agency_id:
        metadata["ghl_company_id"] = location.agency.ghl_company_id

    user = None
    if ghl_user_id:
        user = User.objects.filter(ghl_user_id=ghl_user_id).first()
    if user is None and email:
        user = User.objects.filter(email__iexact=email).first()

    defaults = {
        "first_name": user_data.get("firstName") or user_data.get("first_name") or "",
        "last_name": user_data.get("lastName") or user_data.get("last_name") or "",
        "ghl_user_id": ghl_user_id,
        **metadata,
    }
    if email:
        defaults["email"] = email

    if user is None:
        if not email:
            email = f"ghl_{ghl_user_id}@placeholder.local"
            defaults["email"] = email
        user, _ = ProvisioningService.get_or_create_user(email=email, defaults=defaults)
        # Apply metadata that get_or_create may have ignored on existing rows.
        for key, value in defaults.items():
            setattr(user, key, value)
        user.save()
    else:
        for key, value in defaults.items():
            if value is not None and value != "":
                setattr(user, key, value)
        user.save()

    role_slug = map_ghl_user_to_role_slug(user_data)
    # Don't downgrade an existing agency_admin membership for this location.
    existing = user.memberships.filter(location=location, is_active=True).select_related("role").first()
    if existing and existing.role.slug == Roles.AGENCY_ADMIN:
        role_slug = Roles.AGENCY_ADMIN

    ProvisioningService.assign_membership_by_slug(
        user=user, location=location, role_slug=role_slug
    )
    return user


def sync_location_users(*, location: Location, access_token: str) -> dict[str, int]:
    """Fetch GHL users for a location and upsert local users + memberships."""
    rows = fetch_users_for_location(location=location, access_token=access_token)
    created = 0
    updated = 0
    for row in rows:
        ghl_id = row.get("id")
        email = (row.get("email") or "").strip().lower()
        existed = False
        if ghl_id:
            existed = User.objects.filter(ghl_user_id=ghl_id).exists()
        if not existed and email:
            existed = User.objects.filter(email__iexact=email).exists()
        try:
            upsert_user_from_ghl(row, location=location)
        except Exception:
            logger.exception(
                "Failed to upsert GHL user id=%s email=%s location=%s",
                ghl_id,
                email,
                location.ghl_location_id,
            )
            continue
        if existed:
            updated += 1
        else:
            created += 1
    logger.info(
        "User sync location=%s created=%s updated=%s",
        location.ghl_location_id,
        created,
        updated,
    )
    return {"created": created, "updated": updated, "total": len(rows)}
