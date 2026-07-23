"""User endpoints, scoped to the current tenant (location)."""
from __future__ import annotations

from rest_framework import mixins, viewsets
from rest_framework.permissions import IsAuthenticated

from apps.rbac.constants import Permissions
from apps.rbac.permissions import HasPermission, IsTenantMember

from .models import User
from .serializers import UserSerializer, UserWriteSerializer


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
