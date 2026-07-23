"""Onboarding/provisioning service.

Turns GoHighLevel OAuth + user payloads into Agency/Location/User/Membership
rows. Called by the authentication app's OAuth callback and (for JIT user
creation) the auto-login flow.
"""
from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any, Optional

from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone

from apps.rbac.models import Role
from apps.rbac.services import get_role

from ..models import Agency, Location, Membership
from ..repositories import AgencyRepository, LocationRepository, MembershipRepository

logger = logging.getLogger("apps.tenancy")
User = get_user_model()


class ProvisioningService:
    """Idempotent upserts for tenant + membership records."""

    @staticmethod
    @transaction.atomic
    def upsert_agency(*, company_id: str, name: str = "", tokens: Optional[dict] = None) -> Agency:
        defaults: dict[str, Any] = {}
        if name:
            defaults["name"] = name
        if tokens:
            defaults.update(_token_defaults(tokens))
        agency, created = AgencyRepository.upsert(company_id, defaults=defaults)
        logger.info("Agency %s (%s)", "created" if created else "updated", company_id)
        return agency

    @staticmethod
    @transaction.atomic
    def upsert_location(
        *,
        location_id: str,
        name: str = "",
        agency: Optional[Agency] = None,
        timezone_name: str = "",
        tokens: Optional[dict] = None,
    ) -> Location:
        defaults: dict[str, Any] = {}
        if name:
            defaults["name"] = name
        if agency is not None:
            defaults["agency"] = agency
        if timezone_name:
            defaults["timezone"] = timezone_name
        if tokens:
            defaults.update(_token_defaults(tokens))
            defaults["ghl_user_id"] = tokens.get("userId") or tokens.get("user_id") or ""
        location, created = LocationRepository.upsert(location_id, defaults=defaults)
        if location.onboarded_at is None:
            location.mark_onboarded()
            location.save(update_fields=["onboarded_at"])
        logger.info("Location %s (%s)", "created" if created else "updated", location_id)
        return location

    @staticmethod
    def get_or_create_user(*, email: str, defaults: Optional[dict] = None) -> tuple["User", bool]:
        email = (email or "").strip().lower()
        user, created = User.objects.get_or_create(
            email=email, defaults=defaults or {}
        )
        if created:
            user.set_unusable_password()
            user.save(update_fields=["password"])
            logger.info("Provisioned user %s", email)
        return user, created

    @staticmethod
    def assign_membership(*, user, location: Location, role: Role) -> Membership:
        membership, _ = MembershipRepository.upsert(user, location, role)
        return membership

    @staticmethod
    def assign_membership_by_slug(*, user, location: Location, role_slug: str) -> Optional[Membership]:
        role = get_role(role_slug)
        if role is None:
            logger.error("Role slug '%s' not found; run seed_rbac.", role_slug)
            return None
        return ProvisioningService.assign_membership(user=user, location=location, role=role)


def _token_defaults(tokens: dict) -> dict[str, Any]:
    defaults: dict[str, Any] = {}
    if tokens.get("access_token"):
        defaults["access_token"] = tokens["access_token"]
    if tokens.get("refresh_token"):
        defaults["refresh_token"] = tokens["refresh_token"]
    if tokens.get("scope"):
        defaults["scope"] = tokens["scope"]
    expires_in = tokens.get("expires_in")
    if expires_in:
        try:
            defaults["token_expires_at"] = timezone.now() + timedelta(seconds=int(expires_in))
        except (TypeError, ValueError):
            pass
    return defaults
