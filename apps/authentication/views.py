"""Authentication endpoints: GHL OAuth onboarding, auto-login, refresh, me."""
from __future__ import annotations

import logging
from urllib.parse import urlencode

from django.conf import settings
from django.shortcuts import redirect
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.views import TokenRefreshView

from apps.accounts.serializers import UserSerializer
from apps.common.exceptions import (
    IntegrationError,
    NotFoundError,
    PermissionDeniedError,
    ValidationError,
)
from apps.rbac.constants import ALL_PERMISSIONS
from apps.rbac.serializers import RoleSerializer
from apps.rbac.services import permissions_for_membership, permissions_for_role
from apps.tenancy.context import get_current_membership, set_current_location
from apps.tenancy.models import Location, Membership
from apps.tenancy.serializers import AccessibleLocationSerializer, LocationSerializer

from .jwt import issue_tokens_for_user
from .serializers import AutoLoginRequestSerializer
from .services import AutoLoginService, GHLOAuthService
from .services.oauth_session import consume_oauth_login_code

logger = logging.getLogger("apps.authentication")

SHARED_SECRET_HEADER = "HTTP_X_GHL_SIGNATURE"


class GHLAuthorizeView(APIView):
    """Start GHL Marketplace OAuth (redirect to chooselocation).

    GET  → 302 redirect (browser / Locations "Onboard" button).
    GET ?format=json → ``{ "auth_url": "..." }`` for SPA clients.

    When the caller is authenticated, their user id is passed as OAuth ``state``
    so the callback can grant them access to the newly onboarded location(s).
    """

    permission_classes = [AllowAny]

    def get(self, request):
        service = GHLOAuthService()
        state = None
        if getattr(request.user, "is_authenticated", False):
            state = str(request.user.pk)
        try:
            url = service.build_authorize_url(state=state)
        except IntegrationError as exc:
            if request.GET.get("format") == "json":
                return Response(
                    {"error": {"code": exc.code, "message": exc.message}},
                    status=exc.status_code,
                )
            frontend = settings.FRONTEND_BASE_URL.rstrip("/")
            return redirect(
                f"{frontend}/oauth/error?{urlencode({'reason': exc.message[:200]})}"
            )

        if request.GET.get("format") == "json":
            return Response({"auth_url": url})
        return redirect(url)


class GHLCallbackView(APIView):
    """Exchange the OAuth code, onboard the tenant, then bounce to the frontend."""

    permission_classes = [AllowAny]

    def get(self, request):
        code = request.GET.get("code")
        frontend = settings.FRONTEND_BASE_URL.rstrip("/")
        if not code:
            return redirect(f"{frontend}/oauth/error?{urlencode({'reason': 'missing_code'})}")

        service = GHLOAuthService()
        # MUST use the configured redirect_uri (exact match with marketplace app).
        try:
            payload = service.exchange_code(code, redirect_uri=service.redirect_uri)
            summary = service.onboard_from_token_payload(
                payload,
                initiated_by_user_id=(request.GET.get("state") or "").strip() or None,
            )
        except Exception as exc:  # noqa: BLE001 - surfaced to the user via redirect
            logger.exception("GHL OAuth callback failed")
            return redirect(
                f"{frontend}/oauth/error?{urlencode({'reason': str(exc)[:200]})}"
            )

        return redirect(f"{frontend}/oauth/success?{urlencode(summary)}")


def _login_response(result: dict) -> Response:
    membership = result["membership"]
    return Response(
        {
            "access": result["tokens"]["access"],
            "refresh": result["tokens"]["refresh"],
            "user": UserSerializer(result["user"]).data,
            "location": AccessibleLocationSerializer(result["location"]).data,
            "role": RoleSerializer(membership.role).data if membership else None,
            "permissions": result["permissions"],
        }
    )


class GHLAutoLoginView(APIView):
    """POST { email, location_id } → JWTs + user/location/permissions."""

    permission_classes = [AllowAny]

    def post(self, request):
        serializer = AutoLoginRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        result = AutoLoginService.login(
            email=serializer.validated_data["email"],
            location_id=serializer.validated_data["location_id"],
            shared_secret=request.META.get(SHARED_SECRET_HEADER)
            or request.data.get("shared_secret"),
        )
        return _login_response(result)


class GHLOAuthSessionView(APIView):
    """Exchange the one-time post-onboard login_code for JWTs."""

    permission_classes = [AllowAny]

    def post(self, request):
        code = (request.data.get("login_code") or "").strip()
        result = consume_oauth_login_code(code)
        return _login_response(result)


def _me_payload(request) -> dict:
    membership = get_current_membership(request)
    if request.user.is_superuser:
        permissions = sorted(ALL_PERMISSIONS)
    else:
        permissions = sorted(permissions_for_membership(membership)) if membership else []

    location = getattr(request, "location", None)
    return {
        "user": UserSerializer(request.user).data,
        "location": LocationSerializer(location).data if location else None,
        "role": RoleSerializer(membership.role).data if membership else None,
        "permissions": permissions,
    }


class MeView(APIView):
    """Return the authenticated user's identity in the current tenant context."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(_me_payload(request))


class SwitchLocationView(APIView):
    """Switch active tenant and re-issue JWTs with the new ``location_id`` claim.

    This keeps the JWT claim aligned with the sidebar selection so ROI and other
    tenant-scoped APIs never keep serving the previous location's data.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request):
        location_id = (
            (request.data.get("location_id") or request.data.get("locationId") or "")
            .strip()
        )
        if not location_id:
            raise ValidationError("location_id is required.")

        location = (
            Location.objects.select_related("agency")
            .filter(ghl_location_id=location_id, is_active=True)
            .first()
        )
        if location is None:
            raise NotFoundError("Location not found.", code="location_not_found")

        if not request.user.is_superuser:
            membership = Membership.objects.filter(
                user=request.user, location=location, is_active=True
            ).select_related("role").first()
            if membership is None:
                raise PermissionDeniedError(
                    "You are not a member of this location.",
                    code="not_location_member",
                )

        set_current_location(request, location.ghl_location_id)
        tokens = issue_tokens_for_user(request.user, location=location)
        payload = _me_payload(request)
        payload["access"] = tokens["access"]
        payload["refresh"] = tokens["refresh"]
        return Response(payload)


class RefreshTokenView(TokenRefreshView):
    permission_classes = [AllowAny]
