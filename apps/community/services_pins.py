"""Pinned + saved channel messages."""
from __future__ import annotations

from typing import Any

from django.db import transaction

from apps.common.exceptions import NotFoundError, PermissionDeniedError, ValidationError
from apps.tenancy.models import Location

from .models import CommunityPinnedMessage, CommunitySavedMessage
from .services import (
    _get_message,
    serialize_message,
    user_can_manage_channel,
    user_can_view_channel,
)

MAX_PINS_PER_CHANNEL = 5


def serialize_pin(pin: CommunityPinnedMessage) -> dict[str, Any]:
    return {
        "id": str(pin.id),
        "channel_id": str(pin.channel_id),
        "message": serialize_message(pin.message),
        "pinned_by": (
            {
                "id": str(pin.pinned_by_id),
            }
            if pin.pinned_by_id
            else None
        ),
        "created_at": pin.created_at.isoformat(),
    }


def list_pins(*, channel_id: str, location: Location, user) -> dict[str, Any]:
    from .services import get_channel

    channel = get_channel(channel_id)
    if not user_can_view_channel(channel, location=location, user=user):
        raise NotFoundError("Channel not found.")
    rows = list(
        CommunityPinnedMessage.objects.filter(channel=channel, is_active=True)
        .select_related("message", "message__author", "pinned_by")
        .order_by("-created_at")[:MAX_PINS_PER_CHANNEL]
    )
    return {
        "channel_id": str(channel.id),
        "count": len(rows),
        "max": MAX_PINS_PER_CHANNEL,
        "pins": [serialize_pin(p) for p in rows],
    }


@transaction.atomic
def pin_message(
    *,
    message_id: str,
    location: Location,
    user,
    held: set[str],
) -> dict[str, Any]:
    msg = _get_message(message_id)
    channel = msg.channel
    if not user_can_view_channel(channel, location=location, user=user):
        raise NotFoundError("Message not found.")
    if msg.status != msg.Status.PUBLISHED:
        raise ValidationError("Only published messages can be pinned.")
    if not user_can_manage_channel(channel, location=location, user=user, held=held):
        # Allow any poster to pin for Phase 2 usability (channel members with post).
        # Still require view access above.
        pass

    existing = CommunityPinnedMessage.objects.filter(
        channel=channel, message=msg, is_active=True
    ).first()
    if existing:
        return serialize_pin(existing)

    active_count = CommunityPinnedMessage.objects.filter(
        channel=channel, is_active=True
    ).count()
    if active_count >= MAX_PINS_PER_CHANNEL:
        raise ValidationError(
            f"This channel already has {MAX_PINS_PER_CHANNEL} pinned messages.",
            code="pin_limit_reached",
        )

    pin = CommunityPinnedMessage.objects.create(
        channel=channel,
        message=msg,
        pinned_by=user,
        is_active=True,
    )
    pin = CommunityPinnedMessage.objects.select_related(
        "message", "message__author", "pinned_by"
    ).get(pk=pin.pk)
    return serialize_pin(pin)


@transaction.atomic
def unpin_message(
    *,
    message_id: str,
    location: Location,
    user,
    held: set[str],
) -> dict[str, Any]:
    msg = _get_message(message_id)
    channel = msg.channel
    if not user_can_view_channel(channel, location=location, user=user):
        raise NotFoundError("Message not found.")
    pin = CommunityPinnedMessage.objects.filter(
        channel=channel, message=msg, is_active=True
    ).first()
    if not pin:
        raise NotFoundError("Pin not found.")
    if pin.pinned_by_id != user.id and not user_can_manage_channel(
        channel, location=location, user=user, held=held
    ):
        raise PermissionDeniedError("You cannot remove this pin.")
    pin.is_active = False
    pin.save(update_fields=["is_active", "updated_at"])
    return {"ok": True, "message_id": str(msg.id)}


def list_saved(*, location: Location, user) -> dict[str, Any]:
    rows = list(
        CommunitySavedMessage.objects.filter(user=user, location=location)
        .select_related("message", "message__author", "message__channel")
        .order_by("-created_at")[:100]
    )
    items = []
    for row in rows:
        msg = row.message
        if msg.status != msg.Status.PUBLISHED:
            continue
        if not user_can_view_channel(msg.channel, location=location, user=user):
            continue
        items.append(
            {
                "id": str(row.id),
                "saved_at": row.created_at.isoformat(),
                "message": serialize_message(msg),
                "channel": {
                    "id": str(msg.channel_id),
                    "name": msg.channel.name,
                    "channel_type": msg.channel.channel_type,
                },
            }
        )
    return {"count": len(items), "saved": items}


@transaction.atomic
def save_message(*, message_id: str, location: Location, user) -> dict[str, Any]:
    msg = _get_message(message_id)
    if not user_can_view_channel(msg.channel, location=location, user=user):
        raise NotFoundError("Message not found.")
    if msg.status != msg.Status.PUBLISHED:
        raise ValidationError("Only published messages can be saved.")
    row, _ = CommunitySavedMessage.objects.get_or_create(
        user=user,
        message=msg,
        defaults={"location": location},
    )
    return {
        "id": str(row.id),
        "saved_at": row.created_at.isoformat(),
        "message": serialize_message(msg),
    }


@transaction.atomic
def unsave_message(*, message_id: str, location: Location, user) -> dict[str, Any]:
    deleted, _ = CommunitySavedMessage.objects.filter(
        user=user, message_id=message_id
    ).delete()
    if not deleted:
        raise NotFoundError("Saved message not found.")
    return {"ok": True, "message_id": str(message_id)}
