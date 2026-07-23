"""Tenant management endpoints.

All list/detail querysets are tenant-scoped: a user only ever sees agencies,
locations and memberships they are entitled to, unless they are a superuser.
"""
from __future__ import annotations

from rest_framework import mixins, viewsets
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.rbac.constants import Permissions
from apps.rbac.permissions import HasPermission, IsSuperAdmin, IsTenantMember

from .models import Agency, Location, Membership
from .serializers import (
    AccessibleLocationSerializer,
    AgencySerializer,
    LocationSerializer,
    MembershipSerializer,
)
from .services import accessible_locations_for_user


class MyLocationsView(APIView):
    """Locations the current user can access — powers the tenant switcher."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        locations = accessible_locations_for_user(request.user)
        data = AccessibleLocationSerializer(locations, many=True).data
        return Response({"results": data})


class AgencyViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    serializer_class = AgencySerializer
    search_fields = ("name", "ghl_company_id")
    ordering_fields = ("name", "created_at")

    def get_permissions(self):
        if self.action in ("update", "partial_update"):
            return [IsAuthenticated(), IsSuperAdmin()]
        return [IsAuthenticated(), IsSuperAdmin()]

    def get_queryset(self):
        return Agency.objects.all()


class LocationViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    serializer_class = LocationSerializer
    search_fields = ("name", "ghl_location_id")
    ordering_fields = ("name", "created_at", "status")
    lookup_field = "ghl_location_id"

    def get_permissions(self):
        if self.action in ("update", "partial_update"):
            return [
                IsAuthenticated(),
                IsTenantMember(),
                HasPermission.require(Permissions.LOCATION_MANAGE)(),
            ]
        return [IsAuthenticated()]

    def get_queryset(self):
        return accessible_locations_for_user(self.request.user)


class MembershipViewSet(viewsets.ModelViewSet):
    """Members of the *current* location (X-Location-Id)."""

    serializer_class = MembershipSerializer
    search_fields = ("user__email", "user__first_name", "user__last_name")
    ordering_fields = ("created_at",)

    def get_permissions(self):
        if self.action in ("list", "retrieve"):
            return [
                IsAuthenticated(),
                IsTenantMember(),
                HasPermission.require(Permissions.MEMBER_VIEW)(),
            ]
        return [
            IsAuthenticated(),
            IsTenantMember(),
            HasPermission.require(Permissions.MEMBER_MANAGE)(),
        ]

    def get_queryset(self):
        location = getattr(self.request, "location", None)
        if location is None:
            return Membership.objects.none()
        return (
            Membership.objects.filter(location=location)
            .select_related("user", "role", "location")
        )

    def perform_create(self, serializer):
        serializer.save(location=self.request.location)
