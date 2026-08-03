"""Channel + DM message reactions."""
from __future__ import annotations

from collections import defaultdict
from typing import Any, Optional

from django.db import transaction

from apps.common.exceptions import NotFoundError, ValidationError
from apps.tenancy.models import Location

from .models import CommunityDmMessage, CommunityDmReaction, CommunityMessage, CommunityReaction
from .services import _get_message, user_can_view_channel
from .services_dms import _get_conversation_for_user, user_can_access_dm

REACTION_OPTIONS = [
    {"key": "like", "emoji": "👍", "label": "Like"},
    {"key": "love", "emoji": "❤️", "label": "Love"},
    {"key": "great_job", "emoji": "👏", "label": "Great Job"},
    {"key": "done", "emoji": "✅", "label": "Done"},
    {"key": "celebrate", "emoji": "🎉", "label": "Celebrate"},
    {"key": "awesome", "emoji": "🔥", "label": "Awesome"},
    {"key": "following", "emoji": "👀", "label": "Following"},
    {"key": "question", "emoji": "❓", "label": "Question"},
]
REACTION_KEYS = {o["key"] for o in REACTION_OPTIONS}
REACTION_EMOJI = {o["key"]: o["emoji"] for o in REACTION_OPTIONS}


def reaction_meta() -> list[dict[str, str]]:
    return list(REACTION_OPTIONS)


def _normalize_key(reaction_key: str) -> str:
    key = (reaction_key or "").strip().lower()
    if key not in REACTION_KEYS:
        raise ValidationError(
            "Invalid reaction.",
            details={"reaction_key": "invalid"},
            code="invalid_reaction_key",
        )
    return key


def summarize_reactions(
    *,
    message_ids: list,
    viewer_id=None,
    dm: bool = False,
) -> dict[str, list[dict[str, Any]]]:
    """Return {message_id: [{key, emoji, count, reacted_by_me}, ...]}.

    When ``viewer_id`` is None, ``reacted_by_me`` is always False (safe for WS fan-out).
    """
    if not message_ids:
        return {}
    Model = CommunityDmReaction if dm else CommunityReaction
    rows = Model.objects.filter(message_id__in=message_ids).values_list(
        "message_id", "reaction_key", "user_id"
    )
    grouped: dict[Any, dict[str, set]] = defaultdict(lambda: defaultdict(set))
    for mid, key, uid in rows:
        grouped[mid][key].add(uid)

    out: dict[str, list[dict[str, Any]]] = {}
    for mid, by_key in grouped.items():
        items = []
        for key, users in sorted(by_key.items()):
            items.append(
                {
                    "key": key,
                    "emoji": REACTION_EMOJI.get(key, key),
                    "count": len(users),
                    "reacted_by_me": bool(viewer_id and viewer_id in users),
                }
            )
        out[str(mid)] = items
    for mid in message_ids:
        out.setdefault(str(mid), [])
    return out


def reactions_for_message(*, message_id, viewer_id=None, dm: bool = False) -> list[dict[str, Any]]:
    return summarize_reactions(
        message_ids=[message_id], viewer_id=viewer_id, dm=dm
    ).get(str(message_id), [])


def reaction_broadcast_payload(
    *,
    message_id,
    reaction_key: str,
    added: bool,
    user_id,
    channel_id: Optional[str] = None,
    conversation_id: Optional[str] = None,
    dm: bool = False,
) -> dict[str, Any]:
    """Viewer-neutral reaction event for WS (clients merge reacted_by_me locally)."""
    payload: dict[str, Any] = {
        "message_id": str(message_id),
        "reaction_key": reaction_key,
        "emoji": REACTION_EMOJI.get(reaction_key, reaction_key),
        "added": added,
        "user_id": str(user_id),
        "reactions": reactions_for_message(
            message_id=message_id, viewer_id=None, dm=dm
        ),
    }
    if channel_id is not None:
        payload["channel_id"] = str(channel_id)
    if conversation_id is not None:
        payload["conversation_id"] = str(conversation_id)
    return payload


@transaction.atomic
def toggle_channel_reaction(
    *,
    message_id: str,
    location: Location,
    user,
    held: set[str],
    reaction_key: str,
) -> dict[str, Any]:
    msg = _get_message(message_id)
    if not user_can_view_channel(msg.channel, location=location, user=user):
        raise NotFoundError("Message not found.")
    if msg.status != CommunityMessage.Status.PUBLISHED:
        raise NotFoundError("Message not found.")

    key = _normalize_key(reaction_key)
    existing = CommunityReaction.objects.filter(
        message=msg, user=user, reaction_key=key
    ).first()
    if existing:
        existing.delete()
        added = False
    else:
        CommunityReaction.objects.create(message=msg, user=user, reaction_key=key)
        added = True

    # HTTP response is viewer-aware; WS fan-out is viewer-neutral.
    http_payload = {
        "message_id": str(msg.id),
        "channel_id": str(msg.channel_id),
        "reaction_key": key,
        "emoji": REACTION_EMOJI[key],
        "added": added,
        "user_id": str(user.id),
        "reactions": reactions_for_message(
            message_id=msg.id, viewer_id=user.id, dm=False
        ),
    }
    ws_payload = reaction_broadcast_payload(
        message_id=msg.id,
        reaction_key=key,
        added=added,
        user_id=user.id,
        channel_id=msg.channel_id,
        dm=False,
    )

    def _fanout(p=ws_payload):
        from .broadcast import broadcast_channel_event

        broadcast_channel_event(
            str(msg.channel_id),
            event_type="community.reaction.updated",
            payload=p,
        )

    transaction.on_commit(_fanout)
    return http_payload


@transaction.atomic
def toggle_dm_reaction(
    *,
    message_id: str,
    location: Location,
    user,
    reaction_key: str,
) -> dict[str, Any]:
    try:
        msg = CommunityDmMessage.objects.select_related("conversation").get(pk=message_id)
    except (CommunityDmMessage.DoesNotExist, ValueError, TypeError) as exc:
        raise NotFoundError("Message not found.") from exc

    if not user_can_access_dm(
        conversation_id=str(msg.conversation_id), location=location, user=user
    ):
        raise NotFoundError("Message not found.")
    if msg.status != CommunityDmMessage.Status.PUBLISHED:
        raise NotFoundError("Message not found.")

    # Ensure conversation still location-scoped for this user.
    _get_conversation_for_user(
        conversation_id=str(msg.conversation_id), location=location, user=user
    )

    key = _normalize_key(reaction_key)
    existing = CommunityDmReaction.objects.filter(
        message=msg, user=user, reaction_key=key
    ).first()
    if existing:
        existing.delete()
        added = False
    else:
        CommunityDmReaction.objects.create(message=msg, user=user, reaction_key=key)
        added = True

    http_payload = {
        "message_id": str(msg.id),
        "conversation_id": str(msg.conversation_id),
        "reaction_key": key,
        "emoji": REACTION_EMOJI[key],
        "added": added,
        "user_id": str(user.id),
        "reactions": reactions_for_message(
            message_id=msg.id, viewer_id=user.id, dm=True
        ),
    }
    ws_payload = reaction_broadcast_payload(
        message_id=msg.id,
        reaction_key=key,
        added=added,
        user_id=user.id,
        conversation_id=msg.conversation_id,
        dm=True,
    )

    def _fanout(p=ws_payload):
        from .broadcast import broadcast_dm_event

        broadcast_dm_event(
            str(msg.conversation_id),
            event_type="community.dm.reaction.updated",
            payload=p,
        )

    transaction.on_commit(_fanout)
    return http_payload
