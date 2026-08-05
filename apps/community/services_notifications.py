"""In-app Community notifications + per-channel preferences."""
from __future__ import annotations

import re
from typing import Any, Optional

from django.db import transaction
from django.db.models import Count
from django.utils import timezone

from apps.common.exceptions import NotFoundError, ValidationError
from apps.tenancy.models import Location

from .models import (
    CommunityChannel,
    CommunityChannelMember,
    CommunityChannelNotificationPreference,
    CommunityDmMessage,
    CommunityDmParticipant,
    CommunityMessage,
    CommunityNotification,
)
from .services import _user_payload, user_can_view_channel

DEFAULT_LEVEL = CommunityChannelNotificationPreference.Level.ALL_MESSAGES
NOTIFICATION_LIMIT = 40

LEVELS = {c.value for c in CommunityChannelNotificationPreference.Level}


def inbox_group_name(user_id) -> str:
    clean = re.sub(r"[^a-zA-Z0-9.\-_]", "", str(user_id))
    return f"community.inbox.{clean}"


def _excerpt(body: str) -> str:
    cleaned = re.sub(r"\s+", " ", (body or "").strip())
    if not cleaned:
        return "New activity"
    return cleaned if len(cleaned) <= 140 else f"{cleaned[:137]}..."


def _title_for_reason(reason: str) -> str:
    if reason == CommunityNotification.Reason.THREAD_REPLY:
        return "New thread reply"
    if reason == CommunityNotification.Reason.MENTION:
        return "New mention"
    if reason == CommunityNotification.Reason.DM_MESSAGE:
        return "New direct message"
    return "New message"


def _normalize_public_level(level: str) -> str:
    if level == CommunityChannelNotificationPreference.Level.NONE:
        return CommunityChannelNotificationPreference.Level.NONE
    # Treat legacy mentions_and_replies (and anything else) as all_messages.
    return CommunityChannelNotificationPreference.Level.ALL_MESSAGES


def serialize_preference(
    channel_id: str,
    row: Optional[CommunityChannelNotificationPreference] = None,
) -> dict[str, Any]:
    raw_level = row.notification_level if row else DEFAULT_LEVEL
    muted = bool(row.is_muted) if row else False
    if raw_level == CommunityChannelNotificationPreference.Level.NONE:
        muted = True
    level = _normalize_public_level(raw_level)
    if muted:
        level = CommunityChannelNotificationPreference.Level.NONE
    return {
        "channel_id": str(channel_id),
        "notification_level": level,
        "notify_thread_replies": True if row is None else bool(row.notify_thread_replies),
        "is_muted": muted or level == CommunityChannelNotificationPreference.Level.NONE,
        "is_hidden": False if row is None else bool(row.is_hidden),
        "updated_at": row.updated_at.isoformat() if row else None,
    }


def get_channel_preference(
    *,
    channel_id: str,
    location: Location,
    user,
) -> dict[str, Any]:
    channel = _require_viewable_channel(channel_id, location, user)
    row = CommunityChannelNotificationPreference.objects.filter(
        channel=channel, user=user
    ).first()
    return serialize_preference(str(channel.id), row)


@transaction.atomic
def update_channel_preference(
    *,
    channel_id: str,
    location: Location,
    user,
    notification_level: Optional[str] = None,
    notify_thread_replies: Optional[bool] = None,
    is_muted: Optional[bool] = None,
    is_hidden: Optional[bool] = None,
) -> dict[str, Any]:
    channel = _require_viewable_channel(channel_id, location, user)
    row, _ = CommunityChannelNotificationPreference.objects.get_or_create(
        channel=channel,
        user=user,
        defaults={"notification_level": DEFAULT_LEVEL},
    )

    if is_muted is True:
        row.notification_level = CommunityChannelNotificationPreference.Level.NONE
        row.is_muted = True
    elif notification_level is not None:
        cleaned = str(notification_level).strip()
        if cleaned not in LEVELS:
            raise ValidationError(
                "Invalid notification level.",
                details={"notification_level": "invalid"},
                code="invalid_notification_level",
            )
        level = _normalize_public_level(cleaned)
        row.notification_level = level
        row.is_muted = level == CommunityChannelNotificationPreference.Level.NONE
    elif is_muted is False:
        row.is_muted = False
        if row.notification_level == CommunityChannelNotificationPreference.Level.NONE:
            row.notification_level = DEFAULT_LEVEL

    if notify_thread_replies is not None:
        row.notify_thread_replies = bool(notify_thread_replies)
    if is_hidden is not None:
        row.is_hidden = bool(is_hidden)

    row.save()
    return serialize_preference(str(channel.id), row)


def serialize_notification(row: CommunityNotification) -> dict[str, Any]:
    channel_payload = None
    if row.channel_id:
        name = "Community"
        if getattr(row, "channel", None) is not None:
            name = row.channel.name
        channel_payload = {"id": str(row.channel_id), "name": name}

    dm_payload = None
    if row.dm_conversation_id:
        dm_payload = {"id": str(row.dm_conversation_id)}

    message_payload = None
    if row.message_id:
        message_payload = {
            "id": str(row.message_id),
            "thread_root_id": str(row.thread_root_id) if row.thread_root_id else None,
        }
    elif row.dm_message_id:
        message_payload = {
            "id": str(row.dm_message_id),
            "thread_root_id": None,
        }

    return {
        "id": str(row.id),
        "reason": row.reason,
        "title": row.title or _title_for_reason(row.reason),
        "excerpt": row.excerpt,
        "is_read": row.is_read,
        "created_at": row.created_at.isoformat(),
        "author": _user_payload(row.author),
        "channel": channel_payload,
        "dm_conversation": dm_payload,
        "message": message_payload,
    }


def list_notifications(*, user, limit: int = NOTIFICATION_LIMIT) -> dict[str, Any]:
    try:
        limit = max(1, min(int(limit), 100))
    except (TypeError, ValueError):
        limit = NOTIFICATION_LIMIT

    qs = (
        CommunityNotification.objects.filter(user=user)
        .select_related("author", "channel", "dm_conversation", "message", "dm_message")
        .order_by("-created_at")[:limit]
    )
    rows = list(qs)
    unread_count = CommunityNotification.objects.filter(user=user, is_read=False).count()
    return {
        "notifications": [serialize_notification(r) for r in rows],
        "unread_count": unread_count,
    }


def unread_count(*, user=None, user_id=None) -> int:
    uid = user_id if user_id is not None else getattr(user, "id", None)
    if uid is None:
        return 0
    return CommunityNotification.objects.filter(user_id=uid, is_read=False).count()


def mark_notification_read(*, notification_id: str, user, read: bool = True) -> dict[str, Any]:
    try:
        row = CommunityNotification.objects.select_related(
            "author", "channel", "dm_conversation", "message", "dm_message"
        ).get(pk=notification_id, user=user)
    except (CommunityNotification.DoesNotExist, ValueError, TypeError) as exc:
        raise NotFoundError("Notification not found.") from exc

    row.is_read = bool(read)
    row.read_at = timezone.now() if read else None
    row.save(update_fields=["is_read", "read_at", "updated_at"])
    _broadcast_inbox_badge(user.id)
    return serialize_notification(row)


def mark_all_notifications_read(*, user) -> dict[str, Any]:
    CommunityNotification.objects.filter(user=user, is_read=False).update(
        is_read=True, read_at=timezone.now()
    )
    _broadcast_inbox_badge(user.id)
    return {"ok": True, "unread_count": 0}


def mark_channel_notifications_read(
    *,
    channel_id: str,
    location: Location,
    user,
) -> dict[str, Any]:
    channel = _require_viewable_channel(channel_id, location, user)
    CommunityNotification.objects.filter(
        user=user, channel=channel, is_read=False
    ).update(is_read=True, read_at=timezone.now())
    _broadcast_inbox_badge(user.id)
    return {
        "ok": True,
        "channel_id": str(channel.id),
        "unread_count": unread_count(user_id=user.id),
    }


def _require_viewable_channel(channel_id: str, location: Location, user) -> CommunityChannel:
    from .services import get_channel

    channel = get_channel(channel_id)
    if not user_can_view_channel(channel, location=location, user=user):
        raise NotFoundError("Channel not found.")
    return channel


def _broadcast_inbox_badge(user_id) -> None:
    from .broadcast import broadcast_inbox_event

    broadcast_inbox_event(
        user_id,
        event_type="community.notifications.badge",
        payload={"unread_count": unread_count(user_id=user_id)},
    )


def _broadcast_inbox_badge_for_users(user_ids) -> None:
    from .broadcast import broadcast_inbox_event

    ids = list({uid for uid in user_ids if uid})
    if not ids:
        return
    counts = {
        row["user_id"]: row["c"]
        for row in CommunityNotification.objects.filter(user_id__in=ids, is_read=False)
        .values("user_id")
        .annotate(c=Count("id"))
    }
    for uid in ids:
        broadcast_inbox_event(
            uid,
            event_type="community.notifications.badge",
            payload={"unread_count": int(counts.get(uid, 0))},
        )


def _body_mentions_user(body: str, user) -> bool:
    text = (body or "").lower()
    if not text:
        return False
    email = (getattr(user, "email", None) or "").strip().lower()
    if email and f"@{email}" in text:
        return True
    name = (getattr(user, "full_name", None) or "").strip().lower()
    if name and len(name) >= 2 and f"@{name}" in text:
        return True
    # First token of name
    if name:
        first = name.split()[0]
        if len(first) >= 2 and f"@{first}" in text:
            return True
    return False


def _preference_map(channel_id, user_ids) -> dict:
    rows = CommunityChannelNotificationPreference.objects.filter(
        channel_id=channel_id, user_id__in=user_ids
    )
    return {r.user_id: r for r in rows}


def _should_notify_channel_member(
    *,
    pref: Optional[CommunityChannelNotificationPreference],
    message: CommunityMessage,
    recipient,
) -> Optional[str]:
    """Notify unless muted/none. Default (no pref) = all messages."""
    level = pref.notification_level if pref else DEFAULT_LEVEL
    muted = bool(pref.is_muted) if pref else False
    if muted or level == CommunityChannelNotificationPreference.Level.NONE:
        return None

    # Mentions still get a specific reason if present; otherwise every message.
    if _body_mentions_user(message.body, recipient):
        return CommunityNotification.Reason.MENTION
    if message.thread_root_id:
        return CommunityNotification.Reason.THREAD_REPLY
    return CommunityNotification.Reason.NEW_MESSAGE


def generate_notifications_for_channel_message(message: CommunityMessage) -> None:
    """Create inbox rows for eligible active channel members (excludes author)."""
    if message.status != CommunityMessage.Status.PUBLISHED:
        return
    if not message.author_id:
        return

    member_ids = list(
        CommunityChannelMember.objects.filter(
            channel_id=message.channel_id, left_at__isnull=True
        )
        .exclude(user_id=message.author_id)
        .values_list("user_id", flat=True)
    )
    if not member_ids:
        return

    from django.contrib.auth import get_user_model

    User = get_user_model()
    recipients = list(User.objects.filter(id__in=member_ids, is_active=True))
    prefs = _preference_map(message.channel_id, [u.id for u in recipients])

    to_create: list[CommunityNotification] = []
    notify_user_ids: list = []
    for recipient in recipients:
        reason = _should_notify_channel_member(
            pref=prefs.get(recipient.id),
            message=message,
            recipient=recipient,
        )
        if not reason:
            continue
        to_create.append(
            CommunityNotification(
                user=recipient,
                channel_id=message.channel_id,
                message=message,
                author_id=message.author_id,
                thread_root_id=message.thread_root_id,
                reason=reason,
                title=_title_for_reason(reason),
                excerpt=_excerpt(message.body),
                is_read=False,
            )
        )
        notify_user_ids.append(recipient.id)

    if not to_create:
        return

    CommunityNotification.objects.bulk_create(to_create, ignore_conflicts=True)
    _broadcast_inbox_badge_for_users(notify_user_ids)


def generate_notifications_for_dm_message(message: CommunityDmMessage) -> None:
    if message.status != CommunityDmMessage.Status.PUBLISHED:
        return
    if not message.author_id:
        return

    peers = list(
        CommunityDmParticipant.objects.filter(conversation_id=message.conversation_id)
        .exclude(user_id=message.author_id)
        .select_related("user")
    )
    if not peers:
        return

    notify_ids = []
    for part in peers:
        if part.is_muted:
            continue
        CommunityNotification.objects.update_or_create(
            user_id=part.user_id,
            dm_message=message,
            reason=CommunityNotification.Reason.DM_MESSAGE,
            defaults={
                "dm_conversation_id": message.conversation_id,
                "author_id": message.author_id,
                "title": _title_for_reason(CommunityNotification.Reason.DM_MESSAGE),
                "excerpt": _excerpt(message.body),
                "is_read": False,
                "read_at": None,
            },
        )
        notify_ids.append(part.user_id)

    _broadcast_inbox_badge_for_users(notify_ids)
