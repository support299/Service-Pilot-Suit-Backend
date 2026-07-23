from __future__ import annotations

from rest_framework import serializers

from apps.accounts.serializers import UserSerializer
from apps.rbac.models import Role
from apps.rbac.serializers import RoleSerializer

from .models import Agency, Location, Membership


class AgencySerializer(serializers.ModelSerializer):
    location_count = serializers.IntegerField(source="locations.count", read_only=True)

    class Meta:
        model = Agency
        fields = (
            "id",
            "ghl_company_id",
            "name",
            "is_active",
            "location_count",
            "created_at",
        )
        read_only_fields = ("id", "ghl_company_id", "location_count", "created_at")


class LocationSerializer(serializers.ModelSerializer):
    agency_name = serializers.CharField(source="agency.name", read_only=True, default="")

    class Meta:
        model = Location
        fields = (
            "id",
            "ghl_location_id",
            "name",
            "agency",
            "agency_name",
            "timezone",
            "is_active",
            "status",
            "onboarded_at",
            "last_sync_at",
            "created_at",
        )
        read_only_fields = ("id", "ghl_location_id", "agency", "onboarded_at", "created_at")


class MembershipSerializer(serializers.ModelSerializer):
    user = UserSerializer(read_only=True)
    role = RoleSerializer(read_only=True)
    role_id = serializers.PrimaryKeyRelatedField(
        source="role", queryset=Role.objects.all(), write_only=True
    )
    location = LocationSerializer(read_only=True)

    class Meta:
        model = Membership
        fields = (
            "id",
            "user",
            "location",
            "role",
            "role_id",
            "is_active",
            "created_at",
        )
        read_only_fields = ("id", "user", "location", "created_at")


class AccessibleLocationSerializer(serializers.ModelSerializer):
    """Compact location shape for the tenant switcher + login payload."""

    agency_name = serializers.CharField(source="agency.name", read_only=True, default="")

    class Meta:
        model = Location
        fields = (
            "id",
            "ghl_location_id",
            "name",
            "agency_name",
            "timezone",
            "status",
        )
