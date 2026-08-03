"""Minimal message report / moderation queue."""
from __future__ import annotations

from typing import Any, Optional

from django.db import transaction
from django.utils import timezone

from apps.common.exceptions import NotFoundError, PermissionDeniedError, ValidationError
from apps.rbac.constants import Permissions
from apps.tenancy.models import Location

from .models import CommunityMessage, CommunityMessageReport
from .services import (
    _get_message,
    _user_payload,
    can_manage_company,
    can_manage_platform,
    serialize_message,
    user_can_manage_channel,
    user_can_view_channel,
)

REPORT_REASONS = {
    "spam",
    "harassment",
    "inappropriate",
    "off_topic",
    "other",
}


def _can_moderate(held: set[str]) -> bool:
    return can_manage_company(held) or can_manage_platform(held)


def serialize_report(row: CommunityMessageReport) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "status": row.status,
        "reason": row.reason,
        "notes": row.notes,
        "created_at": row.created_at.isoformat(),
        "reviewed_at": row.reviewed_at.isoformat() if row.reviewed_at else None,
        "reporter": _user_payload(row.reporter),
        "reviewed_by": _user_payload(row.reviewed_by) if row.reviewed_by_id else None,
        "location_id": str(row.location_id),
        "message": serialize_message(row.message),
        "channel": {
            "id": str(row.message.channel_id),
            "name": row.message.channel.name if row.message.channel_id else "",
        },
    }


@transaction.atomic
def report_message(
    *,
    message_id: str,
    location: Location,
    user,
    reason: str = "other",
    notes: str = "",
) -> dict[str, Any]:
    msg = _get_message(message_id)
    if not user_can_view_channel(msg.channel, location=location, user=user):
        raise NotFoundError("Message not found.")
    if msg.status != CommunityMessage.Status.PUBLISHED:
        raise NotFoundError("Message not found.")
    if msg.author_id == user.id:
        raise ValidationError("You cannot report your own message.", code="self_report")

    reason_key = (reason or "other").strip().lower()
    if reason_key not in REPORT_REASONS:
        reason_key = "other"
    notes = (notes or "").strip()[:2000]

    row, created = CommunityMessageReport.objects.get_or_create(
        message=msg,
        reporter=user,
        defaults={
            "location": location,
            "reason": reason_key,
            "notes": notes,
            "status": CommunityMessageReport.Status.OPEN,
        },
    )
    if not created:
        row.reason = reason_key
        row.notes = notes
        row.location = location
        if row.status != CommunityMessageReport.Status.OPEN:
            row.status = CommunityMessageReport.Status.OPEN
            row.reviewed_at = None
            row.reviewed_by = None
        row.save()

    row = CommunityMessageReport.objects.select_related(
        "message", "message__channel", "message__author", "reporter", "reviewed_by"
    ).get(pk=row.pk)
    return serialize_report(row)


def list_reports(
    *,
    location: Location,
    user,
    held: set[str],
    status: Optional[str] = "open",
) -> dict[str, Any]:
    if not _can_moderate(held):
        raise PermissionDeniedError("You need community manage permission to review reports.")

    qs = CommunityMessageReport.objects.select_related(
        "message",
        "message__channel",
        "message__author",
        "reporter",
        "reviewed_by",
    ).order_by("-created_at")

    # Location managers see reports filed from their location + company-channel messages.
    # Platform managers see all open reports.
    if not can_manage_platform(held):
        qs = qs.filter(location=location)

    if status and status != "all":
        qs = qs.filter(status=status)

    rows = list(qs[:100])
    return {
        "count": len(rows),
        "reports": [serialize_report(r) for r in rows],
    }


@transaction.atomic
def update_report_status(
    *,
    report_id: str,
    location: Location,
    user,
    held: set[str],
    status: str,
) -> dict[str, Any]:
    if not _can_moderate(held):
        raise PermissionDeniedError("You need community manage permission to review reports.")

    try:
        row = CommunityMessageReport.objects.select_related(
            "message", "message__channel", "message__author", "reporter", "reviewed_by"
        ).get(pk=report_id)
    except (CommunityMessageReport.DoesNotExist, ValueError, TypeError) as exc:
        raise NotFoundError("Report not found.") from exc

    if not can_manage_platform(held) and row.location_id != location.id:
        raise NotFoundError("Report not found.")

    # Company managers can only act on messages in channels they can manage.
    if not can_manage_platform(held):
        if not user_can_manage_channel(
            row.message.channel, location=location, user=user, held=held
        ):
            # Still allow if report was filed from this location (staff triage).
            if row.location_id != location.id:
                raise PermissionDeniedError("You cannot moderate this report.")

    next_status = (status or "").strip().lower()
    allowed = {c.value for c in CommunityMessageReport.Status}
    if next_status not in allowed:
        raise ValidationError("Invalid report status.", details={"status": "invalid"})

    row.status = next_status
    if next_status == CommunityMessageReport.Status.OPEN:
        row.reviewed_at = None
        row.reviewed_by = None
    else:
        row.reviewed_at = timezone.now()
        row.reviewed_by = user
    row.save(
        update_fields=["status", "reviewed_at", "reviewed_by", "updated_at"]
    )
    return serialize_report(row)
