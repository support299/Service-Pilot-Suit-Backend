"""Direct messages — same-location only (hard cross-location denial)."""
from __future__ import annotations

from typing import Any, Optional
from uuid import UUID

from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone

from apps.common.exceptions import NotFoundError, PermissionDeniedError, ValidationError
from apps.tenancy.models import Location, Membership

from .models import CommunityDmConversation, CommunityDmMessage, CommunityDmParticipant
from .services import DEFAULT_MESSAGE_LIMIT, MAX_MESSAGE_BODY, MAX_MESSAGE_LIMIT, _user_payload

User = get_user_model()

CROSS_LOCATION_CODE = "cross_location_dm_denied"


def dm_group_name(conversation_id: str) -> str:
    import re

    clean = re.sub(r"[^a-zA-Z0-9.\-_]", "", str(conversation_id))
    return f"community.dm.{clean}"


def participant_pair_key(user_a_id, user_b_id) -> str:
    a = str(user_a_id)
    b = str(user_b_id)
    return ":".join(sorted([a, b]))


def serialize_dm_message(
    msg: CommunityDmMessage,
    *,
    viewer=None,
    reactions: Optional[list] = None,
) -> dict[str, Any]:
    payload = {
        "id": str(msg.id),
        "conversation_id": str(msg.conversation_id),
        "body": msg.body if msg.status == CommunityDmMessage.Status.PUBLISHED else "",
        "status": msg.status,
        "author": _user_payload(msg.author),
        "edited_at": msg.edited_at.isoformat() if msg.edited_at else None,
        "created_at": msg.created_at.isoformat(),
        "updated_at": msg.updated_at.isoformat(),
        "reactions": reactions if reactions is not None else [],
    }
    if reactions is None and viewer is not None:
        from .services_reactions import reactions_for_message

        payload["reactions"] = reactions_for_message(
            message_id=msg.id, viewer_id=viewer.id, dm=True
        )
    return payload


def _broadcast_dm(event_type: str, message: dict[str, Any]) -> None:
    from .broadcast import broadcast_dm_event

    conversation_id = message.get("conversation_id")
    if not conversation_id:
        return
    broadcast_dm_event(
        str(conversation_id),
        event_type=event_type,
        payload={"message": message},
    )


def _require_same_location_membership(*, location: Location, user_id) -> None:
    """Reject DMs when the target is not an active member of this location."""
    exists = Membership.objects.filter(
        location=location, user_id=user_id, is_active=True
    ).exists()
    if not exists:
        raise PermissionDeniedError(
            "Direct messages are only allowed with teammates in the same company location.",
            code=CROSS_LOCATION_CODE,
        )


def _get_conversation_for_user(
    *, conversation_id: str, location: Location, user
) -> CommunityDmConversation:
    try:
        convo = CommunityDmConversation.objects.get(
            pk=conversation_id, location=location
        )
    except (CommunityDmConversation.DoesNotExist, ValueError, TypeError) as exc:
        raise NotFoundError("Conversation not found.") from exc
    if not CommunityDmParticipant.objects.filter(
        conversation=convo, user=user
    ).exists():
        raise NotFoundError("Conversation not found.")
    return convo


def _other_participant(convo: CommunityDmConversation, user) -> Optional[Any]:
    row = (
        CommunityDmParticipant.objects.filter(conversation=convo)
        .exclude(user=user)
        .select_related("user")
        .first()
    )
    return row.user if row else None


def serialize_conversation(
    convo: CommunityDmConversation,
    *,
    user,
) -> dict[str, Any]:
    other = _other_participant(convo, user)
    my_part = CommunityDmParticipant.objects.filter(
        conversation=convo, user=user
    ).first()
    unread = 0
    if my_part and convo.last_message_at:
        qs = CommunityDmMessage.objects.filter(
            conversation=convo,
            status=CommunityDmMessage.Status.PUBLISHED,
        ).exclude(author=user)
        if my_part.last_read_at:
            qs = qs.filter(created_at__gt=my_part.last_read_at)
        unread = qs.count()
    return {
        "id": str(convo.id),
        "location_id": str(convo.location_id),
        "recipient": _user_payload(other),
        "last_message_at": (
            convo.last_message_at.isoformat() if convo.last_message_at else None
        ),
        "last_message_preview": convo.last_message_preview or "",
        "unread_count": unread,
        "is_muted": bool(my_part.is_muted) if my_part else False,
        "updated_at": convo.updated_at.isoformat(),
        "created_at": convo.created_at.isoformat(),
    }


def list_dms(*, location: Location, user) -> dict[str, Any]:
    convo_ids = CommunityDmParticipant.objects.filter(user=user).values_list(
        "conversation_id", flat=True
    )
    rows = list(
        CommunityDmConversation.objects.filter(
            id__in=convo_ids, location=location
        ).order_by("-last_message_at", "-updated_at")
    )
    return {
        "count": len(rows),
        "conversations": [serialize_conversation(c, user=user) for c in rows],
    }


@transaction.atomic
def open_or_create_dm(
    *,
    location: Location,
    user,
    target_user_id: str,
) -> dict[str, Any]:
    try:
        target_uuid = UUID(str(target_user_id))
    except (TypeError, ValueError) as exc:
        raise ValidationError(
            "Invalid user_id.", details={"user_id": "invalid"}
        ) from exc

    if target_uuid == user.id:
        raise ValidationError(
            "You cannot start a DM with yourself.",
            details={"user_id": "self"},
        )

    # Hard rule: both parties must belong to the current location.
    _require_same_location_membership(location=location, user_id=target_uuid)
    # Requester is already a tenant member via permission classes; assert anyway.
    _require_same_location_membership(location=location, user_id=user.id)

    try:
        target = User.objects.get(pk=target_uuid, is_active=True)
    except User.DoesNotExist as exc:
        raise NotFoundError("User not found.") from exc

    key = participant_pair_key(user.id, target.id)
    convo = (
        CommunityDmConversation.objects.select_for_update()
        .filter(location=location, participant_pair_key=key)
        .first()
    )
    if convo is None:
        convo = CommunityDmConversation.objects.create(
            location=location,
            participant_pair_key=key,
            created_by=user,
        )
        CommunityDmParticipant.objects.create(conversation=convo, user=user)
        CommunityDmParticipant.objects.create(conversation=convo, user=target)

    return serialize_conversation(convo, user=user)


def list_dm_messages(
    *,
    conversation_id: str,
    location: Location,
    user,
    limit: int = DEFAULT_MESSAGE_LIMIT,
    before: Optional[str] = None,
) -> dict[str, Any]:
    convo = _get_conversation_for_user(
        conversation_id=conversation_id, location=location, user=user
    )
    try:
        limit = int(limit)
    except (TypeError, ValueError):
        limit = DEFAULT_MESSAGE_LIMIT
    limit = max(1, min(limit, MAX_MESSAGE_LIMIT))

    qs = CommunityDmMessage.objects.filter(
        conversation=convo,
        status=CommunityDmMessage.Status.PUBLISHED,
    ).select_related("author")

    if before:
        try:
            anchor = CommunityDmMessage.objects.get(pk=before, conversation=convo)
        except (CommunityDmMessage.DoesNotExist, ValueError, TypeError) as exc:
            raise ValidationError(
                "Invalid before cursor.", details={"before": "not_found"}
            ) from exc
        qs = qs.filter(created_at__lt=anchor.created_at)

    page = list(qs.order_by("-created_at")[: limit + 1])
    has_more = len(page) > limit
    page = page[:limit]
    page.reverse()

    CommunityDmParticipant.objects.filter(conversation=convo, user=user).update(
        last_read_at=timezone.now()
    )

    from .services_reactions import summarize_reactions

    reaction_map = summarize_reactions(
        message_ids=[m.id for m in page], viewer_id=user.id, dm=True
    )
    return {
        "conversation_id": str(convo.id),
        "messages": [
            serialize_dm_message(m, reactions=reaction_map.get(str(m.id), []))
            for m in page
        ],
        "has_more": has_more,
        "next_before": str(page[0].id) if page and has_more else None,
    }


@transaction.atomic
def create_dm_message(
    *,
    conversation_id: str,
    location: Location,
    user,
    body: str,
) -> dict[str, Any]:
    convo = _get_conversation_for_user(
        conversation_id=conversation_id, location=location, user=user
    )
    # Re-check peer still shares this location (membership may have been revoked).
    other = _other_participant(convo, user)
    if other is None:
        raise NotFoundError("Conversation not found.")
    _require_same_location_membership(location=location, user_id=other.id)

    body = (body or "").strip()
    if not body:
        raise ValidationError("Message body is required.", details={"body": "required"})
    if len(body) > MAX_MESSAGE_BODY:
        raise ValidationError(
            "Message is too long.",
            details={"body": f"max {MAX_MESSAGE_BODY} characters"},
        )

    msg = CommunityDmMessage.objects.create(
        conversation=convo,
        author=user,
        body=body,
        status=CommunityDmMessage.Status.PUBLISHED,
    )
    preview = body if len(body) <= 240 else body[:237] + "..."
    convo.last_message_at = msg.created_at
    convo.last_message_preview = preview
    convo.save(update_fields=["last_message_at", "last_message_preview", "updated_at"])
    CommunityDmParticipant.objects.filter(conversation=convo, user=user).update(
        last_read_at=timezone.now()
    )

    payload = serialize_dm_message(msg, viewer=user)
    message_id = msg.id

    def _after_create(p=payload, mid=message_id):
        _broadcast_dm("community.dm.message.created", p)
        try:
            from .services_notifications import generate_notifications_for_dm_message

            generate_notifications_for_dm_message(
                CommunityDmMessage.objects.select_related("author", "conversation").get(
                    pk=mid
                )
            )
        except Exception:
            import logging

            logging.getLogger("apps.community").exception(
                "Failed to generate DM notifications for %s", mid
            )

    transaction.on_commit(_after_create)
    return payload


@transaction.atomic
def mark_dm_read(
    *,
    conversation_id: str,
    location: Location,
    user,
) -> dict[str, Any]:
    convo = _get_conversation_for_user(
        conversation_id=conversation_id, location=location, user=user
    )
    CommunityDmParticipant.objects.filter(conversation=convo, user=user).update(
        last_read_at=timezone.now()
    )
    return serialize_conversation(convo, user=user)


def user_can_access_dm(*, conversation_id: str, location: Location, user) -> bool:
    try:
        _get_conversation_for_user(
            conversation_id=conversation_id, location=location, user=user
        )
        return True
    except NotFoundError:
        return False
