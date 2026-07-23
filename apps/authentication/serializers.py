from __future__ import annotations

from rest_framework import serializers


class AutoLoginRequestSerializer(serializers.Serializer):
    email = serializers.EmailField()
    location_id = serializers.CharField(max_length=255)

    def validate_location_id(self, value: str) -> str:
        value = value.strip()
        if not value:
            raise serializers.ValidationError("location_id is required.")
        return value
