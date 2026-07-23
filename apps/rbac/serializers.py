from __future__ import annotations

from rest_framework import serializers

from .models import Permission, Role


class PermissionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Permission
        fields = ("id", "codename", "name", "description")


class RoleSerializer(serializers.ModelSerializer):
    permissions = PermissionSerializer(many=True, read_only=True)
    permission_codenames = serializers.SerializerMethodField()

    class Meta:
        model = Role
        fields = (
            "id",
            "slug",
            "name",
            "description",
            "is_system",
            "is_superuser_role",
            "permissions",
            "permission_codenames",
        )

    def get_permission_codenames(self, obj: Role) -> list[str]:
        return sorted(obj.permission_codenames())
