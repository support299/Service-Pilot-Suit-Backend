"""Channel-layer broadcast helpers for Community realtime events.

REST remains authoritative for creates/updates. After DB commit, call these
to fan out to channel or DM groups. Consumers forward via ``community_event``.
"""
from __future__ import annotations

import logging
from typing import Any

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer

from .services import channel_group_name
from .services_dms import dm_group_name

logger = logging.getLogger("apps.community")


def _group_send(group: str, event_type: str, payload: dict[str, Any]) -> None:
    layer = get_channel_layer()
    if layer is None:
        logger.warning("No channel layer configured — skipped %s", event_type)
        return
    body = {"type": event_type, **payload}
    try:
        async_to_sync(layer.group_send)(
            group,
            {"type": "community.event", "payload": body},
        )
    except Exception:
        logger.exception("Failed to broadcast %s to %s", event_type, group)


def broadcast_channel_event(
    channel_id: str,
    *,
    event_type: str,
    payload: dict[str, Any],
) -> None:
    """Send a JSON-serializable event to everyone subscribed to a channel room."""
    _group_send(channel_group_name(channel_id), event_type, payload)


def broadcast_dm_event(
    conversation_id: str,
    *,
    event_type: str,
    payload: dict[str, Any],
) -> None:
    """Fan-out to ``community.dm.<conversation_id>``."""
    _group_send(dm_group_name(conversation_id), event_type, payload)


def broadcast_inbox_event(
    user_id,
    *,
    event_type: str,
    payload: dict[str, Any],
) -> None:
    """Fan-out to a per-user inbox room for unread badge updates."""
    from .services_notifications import inbox_group_name

    _group_send(inbox_group_name(user_id), event_type, payload)
