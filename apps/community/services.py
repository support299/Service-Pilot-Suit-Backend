"""Community domain services — channel hub + membership.

Message create/list + WS broadcast land in the chat slice; this module owns
visibility, create-auth matrix, and hub list payload.
"""
from __future__ import annotations

import re
from typing import Any, Optional

from django.db import transaction
from django.db.models import Count, Q, QuerySet
from django.utils import timezone
from django.utils.text import slugify

from apps.common.exceptions import NotFoundError, PermissionDeniedError, ValidationError
from apps.rbac.constants import Permissions
from apps.rbac.permissions import effective_permissions
from apps.tenancy.models import Location, Membership

from .models import CommunityChannel, CommunityChannelMember, CommunityMessage

CHANNEL_TYPES = {c.value for c in CommunityChannel.ChannelType}
PLATFORM_TYPES = {
    CommunityChannel.ChannelType.SERVICE_PILOT,
    CommunityChannel.ChannelType.INDUSTRY,
}
VISIBILITY_LABELS = {
    CommunityChannel.ChannelType.COMPANY: "Company",
    CommunityChannel.ChannelType.SERVICE_PILOT: "Service Pilot",
    CommunityChannel.ChannelType.INDUSTRY: "Industry",
}

# Seeded platform catalog (idempotent by slug).
SERVICE_PILOT_SEED = [
    {
        "slug": "announcements",
        "name": "Announcements",
        "description": "Official Service Pilot product and platform updates.",
        "sort_order": 10,
        "featured": True,
    },
    {
        "slug": "integrations",
        "name": "Integrations",
        "description": "GoHighLevel, ads, and third-party integration tips.",
        "sort_order": 20,
        "featured": False,
    },
]

INDUSTRY_SEED = [
    ("window-cleaning", "Window Cleaning", "Connect with other window cleaning operators."),
    ("pressure-washing", "Pressure Washing", "Pressure washing tips, gear, and jobs."),
    ("landscaping", "Landscaping", "Landscaping and groundskeeping peers."),
    ("hvac", "HVAC", "HVAC contractors and technicians."),
    ("janitorial", "Janitorial", "Commercial cleaning and janitorial services."),
    ("pest-control", "Pest Control", "Pest control operators."),
    ("auto-detailing", "Auto Detailing", "Auto detailing professionals."),
    ("pool-service", "Pool Service", "Pool and spa service companies."),
    ("lawn-care", "Lawn Care", "Lawn care and turf management."),
    ("roofing", "Roofing", "Roofing contractors and crews."),
]


def _user_payload(user) -> dict[str, Any] | None:
    if user is None:
        return None
    full_name = (getattr(user, "get_full_name", None) and user.get_full_name()) or ""
    if not full_name:
        full_name = getattr(user, "email", "") or "Unknown"
    return {
        "id": str(user.pk),
        "email": getattr(user, "email", "") or "",
        "full_name": full_name,
    }


def _held_permissions(request_or_perms) -> set[str]:
    if isinstance(request_or_perms, set):
        return request_or_perms
    if request_or_perms is None:
        return set()
    # DRF request
    if hasattr(request_or_perms, "user"):
        return effective_permissions(request_or_perms)
    return set()


def can_manage_company(held: set[str]) -> bool:
    return Permissions.COMMUNITY_MANAGE in held or Permissions.COMMUNITY_MANAGE_PLATFORM in held


def can_manage_platform(held: set[str]) -> bool:
    return Permissions.COMMUNITY_MANAGE_PLATFORM in held


def creatable_channel_types(held: set[str]) -> list[dict[str, str]]:
    options: list[dict[str, str]] = []
    if can_manage_company(held):
        options.append(
            {
                "value": CommunityChannel.ChannelType.COMPANY,
                "label": "Company Channel",
            }
        )
    if can_manage_platform(held):
        options.extend(
            [
                {
                    "value": CommunityChannel.ChannelType.SERVICE_PILOT,
                    "label": "Service Pilot Channel",
                },
                {
                    "value": CommunityChannel.ChannelType.INDUSTRY,
                    "label": "Industry Group",
                },
            ]
        )
    return options


def require_create_permission(held: set[str], channel_type: str) -> None:
    if channel_type == CommunityChannel.ChannelType.COMPANY:
        if not can_manage_company(held):
            raise PermissionDeniedError(
                "You need community.manage to create company channels."
            )
        return
    if channel_type in PLATFORM_TYPES:
        if not can_manage_platform(held):
            raise PermissionDeniedError(
                "You need community.manage_platform to create Service Pilot "
                "or Industry channels."
            )
        return
    raise ValidationError("Invalid channel_type.", details={"channel_type": channel_type})


def _unique_slug(*, name: str, location: Optional[Location], channel_type: str) -> str:
    base = slugify(name)[:120] or "channel"
    candidate = base
    n = 2
    while True:
        qs = CommunityChannel.objects.filter(slug=candidate)
        if location is not None:
            qs = qs.filter(location=location)
        else:
            qs = qs.filter(location__isnull=True)
        if not qs.exists():
            return candidate
        suffix = f"-{n}"
        candidate = f"{base[: 140 - len(suffix)]}{suffix}"
        n += 1


def _active_members_qs(channel: CommunityChannel) -> QuerySet[CommunityChannelMember]:
    return channel.members.filter(left_at__isnull=True)


def serialize_channel(
    channel: CommunityChannel,
    *,
    member_count: Optional[int] = None,
    unread_count: int = 0,
    can_manage: bool = False,
    current_user_role: Optional[str] = None,
) -> dict[str, Any]:
    if member_count is None:
        member_count = _active_members_qs(channel).count()
    return {
        "id": str(channel.id),
        "name": channel.name,
        "slug": channel.slug,
        "description": channel.description or "",
        "channel_type": channel.channel_type,
        "channel_type_label": channel.get_channel_type_display(),
        "visibility_label": VISIBILITY_LABELS.get(channel.channel_type, channel.channel_type),
        "location_id": str(channel.location_id) if channel.location_id else None,
        "member_count": member_count,
        "unread_count": unread_count,
        "is_archived": channel.is_archived,
        "featured": channel.featured,
        "sort_order": channel.sort_order,
        "thumbnail_url": channel.thumbnail_url or None,
        "can_manage": can_manage,
        "current_user_role": current_user_role,
        "created_at": channel.created_at.isoformat(),
        "updated_at": channel.updated_at.isoformat(),
    }


def serialize_member(row: CommunityChannelMember) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "user": _user_payload(row.user),
        "role": row.role,
        "role_label": row.get_role_display(),
        "location_id": str(row.location_id) if row.location_id else None,
        "joined_at": row.joined_at.isoformat() if row.joined_at else row.created_at.isoformat(),
    }


def _channel_queryset() -> QuerySet[CommunityChannel]:
    return CommunityChannel.objects.select_related("location", "created_by").annotate(
        member_count=Count(
            "members",
            filter=Q(members__left_at__isnull=True),
            distinct=True,
        )
    )


def get_channel(channel_id: str) -> CommunityChannel:
    try:
        return _channel_queryset().get(pk=channel_id)
    except (CommunityChannel.DoesNotExist, ValueError, TypeError) as exc:
        raise NotFoundError("Channel not found.") from exc


def user_can_view_channel(
    channel: CommunityChannel,
    *,
    location: Location,
    user,
) -> bool:
    """Company → same location only. Platform → any authenticated location member."""
    if channel.is_archived:
        # Still readable so hub can show archived rows.
        pass
    if channel.channel_type == CommunityChannel.ChannelType.COMPANY:
        return bool(channel.location_id and channel.location_id == location.id)
    if channel.channel_type in PLATFORM_TYPES:
        return True
    return False


def user_can_manage_channel(
    channel: CommunityChannel,
    *,
    location: Location,
    user,
    held: set[str],
) -> bool:
    if not user_can_view_channel(channel, location=location, user=user):
        return False
    if channel.channel_type == CommunityChannel.ChannelType.COMPANY:
        return can_manage_company(held)
    return can_manage_platform(held)


def _membership_role_map(
    *,
    user,
    channel_ids: list,
) -> dict:
    if not user or not channel_ids:
        return {}
    rows = CommunityChannelMember.objects.filter(
        user=user,
        channel_id__in=channel_ids,
        left_at__isnull=True,
    ).values_list("channel_id", "role")
    return {cid: role for cid, role in rows}


def visible_channels_queryset(
    *,
    location: Location,
    include_archived: bool = False,
) -> QuerySet[CommunityChannel]:
    qs = _channel_queryset().filter(
        Q(channel_type=CommunityChannel.ChannelType.COMPANY, location=location)
        | Q(channel_type__in=list(PLATFORM_TYPES), location__isnull=True)
    )
    if not include_archived:
        qs = qs.filter(is_archived=False)
    return qs


def list_hub(
    *,
    location: Location,
    user,
    held: set[str],
    include_archived: bool = False,
) -> dict[str, Any]:
    channels = list(
        visible_channels_queryset(
            location=location,
            include_archived=include_archived,
        ).order_by("sort_order", "name")
    )
    role_map = _membership_role_map(
        user=user,
        channel_ids=[c.id for c in channels],
    )

    groups: dict[str, list[dict[str, Any]]] = {
        "company": [],
        "service_pilot": [],
        "industry": [],
    }
    for channel in channels:
        key = channel.channel_type
        if key not in groups:
            continue
        can_manage = user_can_manage_channel(
            channel, location=location, user=user, held=held
        )
        groups[key].append(
            serialize_channel(
                channel,
                member_count=getattr(channel, "member_count", None),
                unread_count=0,
                can_manage=can_manage,
                current_user_role=role_map.get(channel.id),
            )
        )

    # Recent activity: newest updated first across all visible channels.
    recent_sorted = sorted(channels, key=lambda c: c.updated_at, reverse=True)[:8]
    recent_activity = [
        {
            "channel_id": str(c.id),
            "name": c.name,
            "channel_type": c.channel_type,
            "updated_at": c.updated_at.isoformat(),
            "icon": "chat",
        }
        for c in recent_sorted
    ]

    return {
        "company": {"count": len(groups["company"]), "channels": groups["company"]},
        "service_pilot": {
            "count": len(groups["service_pilot"]),
            "channels": groups["service_pilot"],
        },
        "industry": {"count": len(groups["industry"]), "channels": groups["industry"]},
        "recent_activity": recent_activity,
        "meta": {
            "creatable_types": creatable_channel_types(held),
            "can_create": bool(creatable_channel_types(held)),
            "permissions": {
                "view": Permissions.COMMUNITY_VIEW in held,
                "post": Permissions.COMMUNITY_POST in held,
                "manage": can_manage_company(held),
                "manage_platform": can_manage_platform(held),
            },
        },
    }


def _ensure_active_member(
    *,
    channel: CommunityChannel,
    user,
    location: Optional[Location],
    role: str,
) -> CommunityChannelMember:
    existing = (
        CommunityChannelMember.objects.filter(channel=channel, user=user)
        .order_by("-created_at")
        .first()
    )
    if existing and existing.left_at is None:
        if existing.role != role and role == CommunityChannelMember.Role.OWNER:
            existing.role = role
            existing.save(update_fields=["role", "updated_at"])
        return existing
    if existing and existing.left_at is not None:
        existing.left_at = None
        existing.role = role
        existing.location = location
        existing.joined_at = timezone.now()
        existing.save(
            update_fields=["left_at", "role", "location", "joined_at", "updated_at"]
        )
        return existing
    return CommunityChannelMember.objects.create(
        channel=channel,
        user=user,
        location=location,
        role=role,
    )


def _auto_join_location_members(
    *,
    channel: CommunityChannel,
    location: Location,
    owner,
) -> None:
    """All active location members join company channels; creator is owner."""
    memberships = (
        Membership.objects.filter(location=location, is_active=True)
        .select_related("user")
        .iterator()
    )
    for membership in memberships:
        role = (
            CommunityChannelMember.Role.OWNER
            if membership.user_id == owner.id
            else CommunityChannelMember.Role.MEMBER
        )
        _ensure_active_member(
            channel=channel,
            user=membership.user,
            location=location,
            role=role,
        )
    # Creator may not have a Membership row in edge cases (superuser).
    _ensure_active_member(
        channel=channel,
        user=owner,
        location=location,
        role=CommunityChannelMember.Role.OWNER,
    )


@transaction.atomic
def create_channel(
    *,
    location: Location,
    user,
    held: set[str],
    name: str,
    description: str = "",
    channel_type: str,
) -> dict[str, Any]:
    name = (name or "").strip()
    description = (description or "").strip()
    channel_type = (channel_type or "").strip()

    if not name:
        raise ValidationError("Channel name is required.", details={"name": "required"})
    if len(name) > 120:
        raise ValidationError("Channel name is too long.", details={"name": "max_length"})
    if channel_type not in CHANNEL_TYPES:
        raise ValidationError(
            "Invalid channel_type.",
            details={"channel_type": f"Must be one of: {', '.join(sorted(CHANNEL_TYPES))}"},
        )

    require_create_permission(held, channel_type)

    channel_location: Optional[Location] = None
    if channel_type == CommunityChannel.ChannelType.COMPANY:
        channel_location = location
    else:
        channel_location = None

    slug = _unique_slug(name=name, location=channel_location, channel_type=channel_type)
    channel = CommunityChannel.objects.create(
        location=channel_location,
        name=name,
        slug=slug,
        description=description,
        channel_type=channel_type,
        created_by=user,
        sort_order=0,
    )

    if channel_type == CommunityChannel.ChannelType.COMPANY:
        _auto_join_location_members(channel=channel, location=location, owner=user)
    else:
        _ensure_active_member(
            channel=channel,
            user=user,
            location=location,
            role=CommunityChannelMember.Role.OWNER,
        )

    channel = get_channel(str(channel.id))
    return serialize_channel(
        channel,
        member_count=getattr(channel, "member_count", None),
        can_manage=True,
        current_user_role=CommunityChannelMember.Role.OWNER,
    )


@transaction.atomic
def update_channel(
    *,
    channel_id: str,
    location: Location,
    user,
    held: set[str],
    name: Optional[str] = None,
    description: Optional[str] = None,
    is_archived: Optional[bool] = None,
    featured: Optional[bool] = None,
    sort_order: Optional[int] = None,
) -> dict[str, Any]:
    channel = get_channel(channel_id)
    if not user_can_view_channel(channel, location=location, user=user):
        raise NotFoundError("Channel not found.")
    if not user_can_manage_channel(channel, location=location, user=user, held=held):
        raise PermissionDeniedError("You cannot manage this channel.")

    updates: list[str] = []
    if name is not None:
        cleaned = name.strip()
        if not cleaned:
            raise ValidationError("Channel name is required.", details={"name": "required"})
        channel.name = cleaned
        updates.append("name")
    if description is not None:
        channel.description = description.strip()
        updates.append("description")
    if is_archived is not None:
        channel.is_archived = bool(is_archived)
        updates.append("is_archived")
    if featured is not None:
        channel.featured = bool(featured)
        updates.append("featured")
    if sort_order is not None:
        channel.sort_order = int(sort_order)
        updates.append("sort_order")

    if updates:
        updates.append("updated_at")
        channel.save(update_fields=updates)

    channel = get_channel(str(channel.id))
    role_map = _membership_role_map(user=user, channel_ids=[channel.id])
    return serialize_channel(
        channel,
        member_count=getattr(channel, "member_count", None),
        can_manage=True,
        current_user_role=role_map.get(channel.id),
    )


@transaction.atomic
def archive_channel(
    *,
    channel_id: str,
    location: Location,
    user,
    held: set[str],
) -> dict[str, Any]:
    return update_channel(
        channel_id=channel_id,
        location=location,
        user=user,
        held=held,
        is_archived=True,
    )


def get_channel_detail(
    *,
    channel_id: str,
    location: Location,
    user,
    held: set[str],
) -> dict[str, Any]:
    channel = get_channel(channel_id)
    if not user_can_view_channel(channel, location=location, user=user):
        raise NotFoundError("Channel not found.")
    role_map = _membership_role_map(user=user, channel_ids=[channel.id])
    return serialize_channel(
        channel,
        member_count=getattr(channel, "member_count", None),
        can_manage=user_can_manage_channel(
            channel, location=location, user=user, held=held
        ),
        current_user_role=role_map.get(channel.id),
    )


def list_members(
    *,
    channel_id: str,
    location: Location,
    user,
) -> dict[str, Any]:
    channel = get_channel(channel_id)
    if not user_can_view_channel(channel, location=location, user=user):
        raise NotFoundError("Channel not found.")
    rows = list(
        _active_members_qs(channel)
        .select_related("user", "location")
        .order_by("role", "joined_at")
    )
    members = []
    for r in rows:
        data = serialize_member(r)
        # Same-company DM only — home location must match active tenant.
        data["can_dm"] = bool(
            r.user_id != user.id
            and r.location_id
            and r.location_id == location.id
        )
        members.append(data)
    return {
        "channel_id": str(channel.id),
        "count": len(members),
        "members": members,
    }


def ensure_platform_seeds(*, created_by=None) -> dict[str, int]:
    """Idempotent seed for SP + industry platform channels."""
    created = 0
    updated = 0

    for item in SERVICE_PILOT_SEED:
        obj, was_created = CommunityChannel.objects.update_or_create(
            location=None,
            slug=item["slug"],
            defaults={
                "name": item["name"],
                "description": item["description"],
                "channel_type": CommunityChannel.ChannelType.SERVICE_PILOT,
                "sort_order": item["sort_order"],
                "featured": item["featured"],
                "is_archived": False,
                "created_by": created_by,
            },
        )
        if was_created:
            created += 1
        else:
            updated += 1

    for idx, (slug, name, description) in enumerate(INDUSTRY_SEED, start=1):
        obj, was_created = CommunityChannel.objects.update_or_create(
            location=None,
            slug=slug,
            defaults={
                "name": name,
                "description": description,
                "channel_type": CommunityChannel.ChannelType.INDUSTRY,
                "sort_order": idx * 10,
                "featured": False,
                "is_archived": False,
                "created_by": created_by,
            },
        )
        if was_created:
            created += 1
        else:
            updated += 1

    return {"created": created, "updated": updated}


def channel_group_name(channel_id: str) -> str:
    """Redis Channels group key for a community channel room."""
    # UUID-safe: strip non-word chars for Channels group name rules.
    clean = re.sub(r"[^a-zA-Z0-9.\-_]", "", str(channel_id))
    return f"community.channel.{clean}"


# ─────────────────────────────────────────────────────────────
# Messages (Phase 1 chat)
# ─────────────────────────────────────────────────────────────

DEFAULT_MESSAGE_LIMIT = 50
MAX_MESSAGE_LIMIT = 100
MAX_MESSAGE_BODY = 8000


def serialize_message(msg: CommunityMessage) -> dict[str, Any]:
    return {
        "id": str(msg.id),
        "channel_id": str(msg.channel_id),
        "body": msg.body if msg.status == CommunityMessage.Status.PUBLISHED else "",
        "status": msg.status,
        "thread_root_id": str(msg.thread_root_id) if msg.thread_root_id else None,
        "author": _user_payload(msg.author),
        "edited_at": msg.edited_at.isoformat() if msg.edited_at else None,
        "created_at": msg.created_at.isoformat(),
        "updated_at": msg.updated_at.isoformat(),
    }


def _get_message(message_id: str) -> CommunityMessage:
    try:
        return CommunityMessage.objects.select_related("author", "channel").get(
            pk=message_id
        )
    except (CommunityMessage.DoesNotExist, ValueError, TypeError) as exc:
        raise NotFoundError("Message not found.") from exc


def _require_channel_access(
    *,
    channel_id: str,
    location: Location,
    user,
) -> CommunityChannel:
    channel = get_channel(channel_id)
    if not user_can_view_channel(channel, location=location, user=user):
        raise NotFoundError("Channel not found.")
    return channel


def _can_post(held: set[str]) -> bool:
    return (
        Permissions.COMMUNITY_POST in held
        or Permissions.COMMUNITY_MANAGE in held
        or Permissions.COMMUNITY_MANAGE_PLATFORM in held
    )


def _touch_channel(channel: CommunityChannel) -> None:
    CommunityChannel.objects.filter(pk=channel.pk).update(updated_at=timezone.now())


def _broadcast_message(event_type: str, message: dict[str, Any]) -> None:
    from .broadcast import broadcast_channel_event

    channel_id = message.get("channel_id")
    if not channel_id:
        return
    broadcast_channel_event(
        str(channel_id),
        event_type=event_type,
        payload={"message": message},
    )


def list_messages(
    *,
    channel_id: str,
    location: Location,
    user,
    limit: int = DEFAULT_MESSAGE_LIMIT,
    before: Optional[str] = None,
) -> dict[str, Any]:
    """Return chronological root messages (oldest → newest) with optional cursor."""
    channel = _require_channel_access(
        channel_id=channel_id, location=location, user=user
    )
    try:
        limit = int(limit)
    except (TypeError, ValueError):
        limit = DEFAULT_MESSAGE_LIMIT
    limit = max(1, min(limit, MAX_MESSAGE_LIMIT))

    qs = CommunityMessage.objects.filter(
        channel=channel,
        status=CommunityMessage.Status.PUBLISHED,
        thread_root__isnull=True,
    ).select_related("author")

    if before:
        try:
            anchor = CommunityMessage.objects.get(pk=before, channel=channel)
        except (CommunityMessage.DoesNotExist, ValueError, TypeError) as exc:
            raise ValidationError(
                "Invalid before cursor.", details={"before": "not_found"}
            ) from exc
        qs = qs.filter(created_at__lt=anchor.created_at)

    # Fetch newest page, then reverse for chat display order.
    page = list(qs.order_by("-created_at")[: limit + 1])
    has_more = len(page) > limit
    page = page[:limit]
    page.reverse()

    # Soft-update last_read for this user when they load history.
    CommunityChannelMember.objects.filter(
        channel=channel, user=user, left_at__isnull=True
    ).update(last_read_at=timezone.now())

    return {
        "channel_id": str(channel.id),
        "messages": [serialize_message(m) for m in page],
        "has_more": has_more,
        "next_before": str(page[0].id) if page and has_more else None,
    }


@transaction.atomic
def create_message(
    *,
    channel_id: str,
    location: Location,
    user,
    held: set[str],
    body: str,
    thread_root_id: Optional[str] = None,
) -> dict[str, Any]:
    channel = _require_channel_access(
        channel_id=channel_id, location=location, user=user
    )
    if not _can_post(held):
        raise PermissionDeniedError("You need community.post to send messages.")
    if channel.is_archived:
        raise ValidationError(
            "This channel is archived. New messages are not allowed.",
            code="channel_archived",
        )

    body = (body or "").strip()
    if not body:
        raise ValidationError("Message body is required.", details={"body": "required"})
    if len(body) > MAX_MESSAGE_BODY:
        raise ValidationError(
            "Message is too long.",
            details={"body": f"max {MAX_MESSAGE_BODY} characters"},
        )

    thread_root = None
    if thread_root_id:
        thread_root = _get_message(str(thread_root_id))
        if thread_root.channel_id != channel.id:
            raise ValidationError("Thread root must belong to this channel.")
        if thread_root.thread_root_id:
            thread_root = thread_root.thread_root
        if thread_root.status != CommunityMessage.Status.PUBLISHED:
            raise ValidationError("Cannot reply to a deleted message.")

    # Ensure poster is an active member (platform channels auto-join on first post).
    _ensure_active_member(
        channel=channel,
        user=user,
        location=location,
        role=CommunityChannelMember.Role.MEMBER,
    )

    msg = CommunityMessage.objects.create(
        channel=channel,
        author=user,
        body=body,
        thread_root=thread_root,
        status=CommunityMessage.Status.PUBLISHED,
    )
    _touch_channel(channel)
    CommunityChannelMember.objects.filter(
        channel=channel, user=user, left_at__isnull=True
    ).update(last_read_at=timezone.now())

    payload = serialize_message(msg)
    transaction.on_commit(
        lambda p=payload: _broadcast_message("community.message.created", p)
    )
    return payload


@transaction.atomic
def update_message(
    *,
    message_id: str,
    location: Location,
    user,
    held: set[str],
    body: str,
) -> dict[str, Any]:
    msg = _get_message(message_id)
    channel = msg.channel
    if not user_can_view_channel(channel, location=location, user=user):
        raise NotFoundError("Message not found.")
    if msg.status != CommunityMessage.Status.PUBLISHED:
        raise NotFoundError("Message not found.")
    if msg.author_id != user.id and not user_can_manage_channel(
        channel, location=location, user=user, held=held
    ):
        raise PermissionDeniedError("You can only edit your own messages.")

    body = (body or "").strip()
    if not body:
        raise ValidationError("Message body is required.", details={"body": "required"})
    if len(body) > MAX_MESSAGE_BODY:
        raise ValidationError(
            "Message is too long.",
            details={"body": f"max {MAX_MESSAGE_BODY} characters"},
        )

    msg.body = body
    msg.edited_at = timezone.now()
    msg.save(update_fields=["body", "edited_at", "updated_at"])
    _touch_channel(channel)

    payload = serialize_message(msg)
    transaction.on_commit(
        lambda p=payload: _broadcast_message("community.message.updated", p)
    )
    return payload


@transaction.atomic
def delete_message(
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
    if msg.status == CommunityMessage.Status.DELETED:
        return serialize_message(msg)
    if msg.author_id != user.id and not user_can_manage_channel(
        channel, location=location, user=user, held=held
    ):
        raise PermissionDeniedError("You can only delete your own messages.")

    msg.status = CommunityMessage.Status.DELETED
    msg.body = ""
    msg.save(update_fields=["status", "body", "updated_at"])
    _touch_channel(channel)

    payload = serialize_message(msg)
    transaction.on_commit(
        lambda p=payload: _broadcast_message("community.message.deleted", p)
    )
    return payload

