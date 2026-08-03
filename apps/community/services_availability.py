"""Availability services — per-location presence for Community."""
from __future__ import annotations

from typing import Any, Optional

from django.db import transaction
from django.utils import timezone

from apps.common.exceptions import ValidationError
from apps.tenancy.models import Location

from .models import CommunityChannelMember, CommunityUserAvailability
from .services import _require_channel_access, _user_payload

VALID_STATUSES = {c.value for c in CommunityUserAvailability.Status}
MAX_STATUS_MESSAGE = 160


def serialize_availability(
    row: Optional[CommunityUserAvailability],
    *,
    user=None,
    location_id: Optional[str] = None,
) -> dict[str, Any]:
    if row is None:
        return {
            "status": CommunityUserAvailability.Status.OFFLINE,
            "status_label": "Offline",
            "status_message": "",
            "user": _user_payload(user) if user else None,
            "location_id": location_id,
            "updated_at": None,
        }
    return {
        "status": row.status,
        "status_label": row.get_status_display(),
        "status_message": row.status_message or "",
        "user": _user_payload(row.user),
        "location_id": str(row.location_id),
        "updated_at": row.updated_at.isoformat(),
    }


def get_my_availability(*, location: Location, user) -> dict[str, Any]:
    row = (
        CommunityUserAvailability.objects.select_related("user")
        .filter(location=location, user=user)
        .first()
    )
    return serialize_availability(row, user=user, location_id=str(location.id))


@transaction.atomic
def set_my_availability(
    *,
    location: Location,
    user,
    status: str,
    status_message: str = "",
) -> dict[str, Any]:
    status = (status or "").strip().lower()
    if status not in VALID_STATUSES:
        raise ValidationError(
            "Invalid availability status.",
            details={"status": f"Must be one of: {', '.join(sorted(VALID_STATUSES))}"},
        )
    message = (status_message or "").strip()[:MAX_STATUS_MESSAGE]
    row, _ = CommunityUserAvailability.objects.update_or_create(
        location=location,
        user=user,
        defaults={
            "status": status,
            "status_message": message,
            "expires_at": None,
        },
    )
    row = CommunityUserAvailability.objects.select_related("user").get(pk=row.pk)
    return serialize_availability(row)


def list_channel_availability(
    *,
    channel_id: str,
    location: Location,
    user,
) -> dict[str, Any]:
    """Members of a channel with availability from each member's home location."""
    channel = _require_channel_access(
        channel_id=channel_id, location=location, user=user
    )
    members = list(
        CommunityChannelMember.objects.filter(channel=channel, left_at__isnull=True)
        .select_related("user", "location")
        .order_by("role", "joined_at")
    )
    # Home location for availability lookup (fall back to current location).
    lookup_pairs: list[tuple] = []
    for m in members:
        home_id = m.location_id or location.id
        lookup_pairs.append((home_id, m.user_id))

    avail_map: dict[tuple, CommunityUserAvailability] = {}
    if lookup_pairs:
        location_ids = {p[0] for p in lookup_pairs}
        user_ids = {p[1] for p in lookup_pairs}
        for row in CommunityUserAvailability.objects.filter(
            location_id__in=location_ids, user_id__in=user_ids
        ).select_related("user"):
            # Skip expired
            if row.expires_at and row.expires_at <= timezone.now():
                continue
            avail_map[(row.location_id, row.user_id)] = row

    items: list[dict[str, Any]] = []
    available_only: list[dict[str, Any]] = []
    for m in members:
        home_id = m.location_id or location.id
        row = avail_map.get((home_id, m.user_id))
        payload = serialize_availability(row, user=m.user, location_id=str(home_id))
        payload["role"] = m.role
        payload["can_dm"] = bool(
            m.user_id != user.id
            and m.location_id
            and m.location_id == location.id
        )
        items.append(payload)
        if payload["status"] == CommunityUserAvailability.Status.AVAILABLE:
            available_only.append(payload)

    return {
        "channel_id": str(channel.id),
        "members": items,
        "available": available_only,
        "available_count": len(available_only),
    }
