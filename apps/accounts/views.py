"""User endpoints + public GHL marketplace webhook."""
from __future__ import annotations

import logging

from rest_framework import mixins, viewsets
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.views import APIView

from apps.authentication.services.ghl_webhooks import handle_ghl_webhook
from apps.common.responses import ok
from apps.rbac.constants import Permissions
from apps.rbac.permissions import HasPermission, IsTenantMember

from .models import User
from .serializers import UserSerializer, UserWriteSerializer

logger = logging.getLogger("apps.accounts")


class GhlMarketplaceWebhookView(APIView):
    """Receive GoHighLevel marketplace webhooks (no JWT).

    Configured as Default Webhook URL:
    ``https://suit.theservicepilot.com/api/accounts/webhook/``

    Handles INSTALL / UNINSTALL, UserCreate/Update/Delete, and Opportunity*
    events (same surface as Snapshot JobTracker).
    """

    authentication_classes = []
    permission_classes = [AllowAny]

    def post(self, request):
        payload = request.data
        if not isinstance(payload, dict):
            payload = {}
        result = handle_ghl_webhook(payload)
        # Always 200 so GHL does not retry forever on business skips.
        return ok(result)

    def get(self, request):
        return ok({"status": "ok", "endpoint": "ghl-marketplace-webhook"})


class UserViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    """Users visible within the current location.

    Superusers see everyone; otherwise the list is restricted to members of the
    resolved tenant so no cross-tenant data leaks.
    """

    serializer_class = UserSerializer
    search_fields = ("email", "first_name", "last_name")
    ordering_fields = ("email", "created_at")

    def get_permissions(self):
        perms = [IsAuthenticated(), IsTenantMember()]
        if self.action in ("create", "update", "partial_update"):
            perms.append(HasPermission.require(Permissions.USER_MANAGE)())
        else:
            perms.append(HasPermission.require(Permissions.USER_VIEW)())
        return perms

    def get_serializer_class(self):
        if self.action in ("create", "update", "partial_update"):
            return UserWriteSerializer
        return UserSerializer

    def get_queryset(self):
        user = self.request.user
        if user.is_superuser:
            return User.objects.all()
        location = getattr(self.request, "location", None)
        if location is None:
            return User.objects.none()
        return User.objects.filter(memberships__location=location).distinct()
