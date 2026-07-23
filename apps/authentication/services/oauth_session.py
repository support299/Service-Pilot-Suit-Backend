"""One-time login handoff after GHL Marketplace OAuth onboarding.

Uses Django's TimestampSigner (no Redis required). The frontend exchanges the
code for JWTs within a short TTL so the installer lands in the app authenticated.
"""
from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from django.contrib.auth import get_user_model
from django.core import signing

from apps.common.exceptions import AuthenticationFailedError, NotFoundError
from apps.rbac.constants import ALL_PERMISSIONS, Roles
from apps.rbac.services import permissions_for_membership, permissions_for_role
from apps.tenancy.repositories import LocationRepository
from apps.tenancy.services import ProvisioningService, resolve_membership_for_login

from ..jwt import issue_tokens_for_user

logger = logging.getLogger("apps.authentication")
User = get_user_model()

SALT = "sps.oauth-login"
MAX_AGE_SECONDS = 180  # 3 minutes


def create_oauth_login_code(*, user_id: UUID | str, location_id: str) -> str:
    signer = signing.TimestampSigner(salt=SALT)
    return signer.sign_object(
        {"user_id": str(user_id), "location_id": (location_id or "").strip()}
    )


def consume_oauth_login_code(code: str) -> dict[str, Any]:
    """Validate the one-time code and return the same shape as AutoLoginService.login."""
    code = (code or "").strip()
    if not code:
        raise AuthenticationFailedError("Missing login code.")

    signer = signing.TimestampSigner(salt=SALT)
    try:
        payload = signer.unsign_object(code, max_age=MAX_AGE_SECONDS)
    except signing.SignatureExpired as exc:
        raise AuthenticationFailedError("This login link has expired. Re-open onboarding.") from exc
    except signing.BadSignature as exc:
        raise AuthenticationFailedError("Invalid login code.") from exc

    user_id = payload.get("user_id")
    location_id = (payload.get("location_id") or "").strip()
    if not user_id or not location_id:
        raise AuthenticationFailedError("Invalid login code payload.")

    location = LocationRepository.get_by_location_id(location_id)
    if location is None:
        raise NotFoundError("Location not found.", code="location_not_found")

    try:
        user = User.objects.get(pk=user_id, is_active=True)
    except User.DoesNotExist as exc:
        raise AuthenticationFailedError("User not found for this login code.") from exc

    membership = None
    if not user.is_superuser:
        membership = resolve_membership_for_login(user, location)
        if membership is None:
            # Installer should always get agency-admin access on the onboarded location.
            membership = ProvisioningService.assign_membership_by_slug(
                user=user, location=location, role_slug=Roles.AGENCY_ADMIN
            )

    tokens = issue_tokens_for_user(user, location=location)
    if user.is_superuser:
        permissions = sorted(ALL_PERMISSIONS)
    else:
        permissions = sorted(permissions_for_membership(membership)) if membership else []

    logger.info(
        "OAuth session exchange success user=%s location=%s", user.email, location_id
    )
    return {
        "tokens": tokens,
        "user": user,
        "location": location,
        "membership": membership,
        "permissions": permissions,
    }
