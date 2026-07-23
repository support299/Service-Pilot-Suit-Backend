"""GHL custom-menu-link auto-login service.

GoHighLevel opens a custom menu link passing the user's email and the current
location id. We identify the tenant + user, verify access, and mint JWTs.

An optional shared secret (``GHL_AUTOLOGIN_SHARED_SECRET``) can be required to
prevent spoofed auto-logins from arbitrary callers.
"""
from __future__ import annotations

import hmac
import logging
from typing import Any, Optional

from django.conf import settings

from apps.common.exceptions import (
    AuthenticationFailedError,
    NotFoundError,
    PermissionDeniedError,
    ValidationError,
)
from apps.rbac.constants import ALL_PERMISSIONS
from apps.rbac.services import permissions_for_membership, permissions_for_role
from apps.tenancy.models import Location
from apps.tenancy.repositories import LocationRepository
from apps.tenancy.services import ProvisioningService, resolve_membership_for_login

from ..jwt import issue_tokens_for_user

logger = logging.getLogger("apps.authentication")


class AutoLoginService:
    @staticmethod
    def verify_shared_secret(provided: Optional[str]) -> None:
        """Constant-time check of the optional auto-login shared secret."""
        expected = (settings.GHL.get("AUTOLOGIN_SHARED_SECRET") or "").strip()
        if not expected:
            return  # Feature disabled.
        if not provided or not hmac.compare_digest(provided.strip(), expected):
            logger.warning("Auto-login rejected: bad shared secret")
            raise AuthenticationFailedError("Invalid auto-login signature.")

    @staticmethod
    def login(*, email: str, location_id: str, shared_secret: Optional[str] = None) -> dict[str, Any]:
        AutoLoginService.verify_shared_secret(shared_secret)

        email = (email or "").strip().lower()
        location_id = (location_id or "").strip()
        if not email or not location_id:
            raise ValidationError("Both email and location_id are required.")

        location = LocationRepository.get_by_location_id(location_id)
        if location is None:
            raise NotFoundError(
                "This location is not onboarded or is inactive.",
                code="location_not_found",
            )

        user, _created = ProvisioningService.get_or_create_user(email=email)
        if not user.is_active:
            raise PermissionDeniedError("This user account is disabled.")

        membership = None
        if not user.is_superuser:
            membership = resolve_membership_for_login(user, location)
            if membership is None:
                raise PermissionDeniedError(
                    "You do not have access to this location.",
                    code="no_location_access",
                )

        tokens = issue_tokens_for_user(user, location=location)
        if user.is_superuser:
            permissions = sorted(ALL_PERMISSIONS)
        else:
            permissions = sorted(permissions_for_membership(membership))
        logger.info("Auto-login success email=%s location=%s", email, location_id)
        return {
            "tokens": tokens,
            "user": user,
            "location": location,
            "membership": membership,
            "permissions": permissions,
        }
