"""Support ticket domain services."""
from __future__ import annotations

from typing import Any, Optional

from django.db import transaction
from django.db.models import Count, Max, Q, QuerySet
from django.utils import timezone

from apps.common.exceptions import NotFoundError, ValidationError
from apps.tenancy.models import Location, LocationMediaFolder
from apps.tenancy.services.ghl_media import upload_to_location_folder

from .models import SupportAttachment, SupportMessage, SupportTicket

VALID_STATUSES = {c.value for c in SupportTicket.Status}
VALID_CATEGORIES = {c.value for c in SupportTicket.Category}
VALID_PRIORITIES = {c.value for c in SupportTicket.Priority}

ALLOWED_CONTENT_TYPES = {
    "image/jpeg",
    "image/jpg",
    "image/png",
    "image/gif",
    "image/webp",
    "video/mp4",
    "video/quicktime",
    "video/webm",
    "video/x-m4v",
}
MAX_ATTACHMENT_BYTES = 80 * 1024 * 1024  # 80 MB (GHL-friendly)
MAX_ATTACHMENTS_PER_MESSAGE = 8


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


def serialize_attachment(att: SupportAttachment) -> dict[str, Any]:
    return {
        "id": str(att.id),
        "ghl_file_id": att.ghl_file_id,
        "url": att.url,
        "filename": att.filename,
        "content_type": att.content_type,
        "size_bytes": att.size_bytes,
        "kind": att.kind,
        "created_at": att.created_at.isoformat(),
    }


def serialize_message(msg: SupportMessage) -> dict[str, Any]:
    attachments = getattr(msg, "_prefetched_objects_cache", {}).get("attachments")
    if attachments is None:
        attachment_rows = list(msg.attachments.all())
    else:
        attachment_rows = list(attachments)
    return {
        "id": str(msg.id),
        "body": msg.body,
        "is_staff_reply": msg.is_staff_reply,
        "author": _user_payload(msg.author),
        "created_at": msg.created_at.isoformat(),
        "attachments": [serialize_attachment(a) for a in attachment_rows],
    }


def serialize_ticket(
    ticket: SupportTicket,
    *,
    include_messages: bool = False,
) -> dict[str, Any]:
    data: dict[str, Any] = {
        "id": str(ticket.id),
        "display_id": ticket.display_id,
        "number": ticket.number,
        "subject": ticket.subject,
        "description": ticket.description,
        "status": ticket.status,
        "status_label": ticket.get_status_display(),
        "category": ticket.category,
        "category_label": ticket.get_category_display(),
        "priority": ticket.priority,
        "priority_label": ticket.get_priority_display(),
        "created_by": _user_payload(ticket.created_by),
        "created_at": ticket.created_at.isoformat(),
        "updated_at": ticket.updated_at.isoformat(),
        "resolved_at": ticket.resolved_at.isoformat() if ticket.resolved_at else None,
        "message_count": getattr(ticket, "message_count", None),
    }
    if include_messages:
        messages = (
            ticket.messages.select_related("author")
            .prefetch_related("attachments")
            .all()
        )
        data["messages"] = [serialize_message(m) for m in messages]
        data["message_count"] = len(data["messages"])
    return data


def tickets_queryset(location: Location) -> QuerySet[SupportTicket]:
    return (
        SupportTicket.objects.filter(location=location)
        .select_related("created_by")
        .annotate(message_count=Count("messages"))
    )


def list_tickets(
    location: Location,
    *,
    status: Optional[str] = None,
    search: Optional[str] = None,
) -> list[dict[str, Any]]:
    qs = tickets_queryset(location)
    if status and status != "all":
        if status not in VALID_STATUSES:
            raise ValidationError("Invalid status filter.")
        qs = qs.filter(status=status)
    q = (search or "").strip()
    if q:
        filters = Q(subject__icontains=q) | Q(description__icontains=q)
        digits = "".join(ch for ch in q if ch.isdigit())
        if digits:
            try:
                filters = filters | Q(number=int(digits))
            except (TypeError, ValueError):
                pass
        qs = qs.filter(filters)
    return [serialize_ticket(t) for t in qs.order_by("-updated_at")[:200]]


def ticket_summary(location: Location) -> dict[str, Any]:
    rows = (
        SupportTicket.objects.filter(location=location)
        .values("status")
        .annotate(count=Count("id"))
    )
    by_status = {s.value: 0 for s in SupportTicket.Status}
    for row in rows:
        by_status[row["status"]] = row["count"]
    openish = (
        by_status[SupportTicket.Status.OPEN]
        + by_status[SupportTicket.Status.WAITING_ON_CUSTOMER]
        + by_status[SupportTicket.Status.WAITING_ON_SUPPORT]
    )
    return {
        "by_status": by_status,
        "open_count": openish,
        "total": sum(by_status.values()),
        "resolved_count": by_status[SupportTicket.Status.RESOLVED]
        + by_status[SupportTicket.Status.CLOSED],
    }


def get_ticket(location: Location, ticket_id: str) -> SupportTicket:
    ticket = (
        tickets_queryset(location)
        .filter(id=ticket_id)
        .first()
    )
    if ticket is None:
        raise NotFoundError("Ticket not found.")
    return ticket


def _next_number(location: Location) -> int:
    current = (
        SupportTicket.objects.filter(location=location).aggregate(m=Max("number"))["m"]
        or 0
    )
    return int(current) + 1


@transaction.atomic
def create_ticket(
    location: Location,
    *,
    user,
    subject: str,
    description: str = "",
    category: str = SupportTicket.Category.GENERAL,
    priority: str = SupportTicket.Priority.NORMAL,
    attachment_metas: Optional[list[dict[str, Any]]] = None,
) -> dict[str, Any]:
    subject = (subject or "").strip()
    if not subject:
        raise ValidationError("Subject is required.")
    if len(subject) > 255:
        raise ValidationError("Subject is too long.")
    description = (description or "").strip()
    if category not in VALID_CATEGORIES:
        raise ValidationError("Invalid category.")
    if priority not in VALID_PRIORITIES:
        raise ValidationError("Invalid priority.")
    attachment_metas = attachment_metas or []

    ticket = SupportTicket.objects.create(
        location=location,
        created_by=user if getattr(user, "is_authenticated", False) else None,
        number=_next_number(location),
        subject=subject,
        description=description,
        category=category,
        priority=priority,
        status=SupportTicket.Status.OPEN,
    )
    # Seed first message from description / attachments so the thread feels complete.
    if description or attachment_metas:
        message = SupportMessage.objects.create(
            ticket=ticket,
            author=ticket.created_by,
            body=description,
            is_staff_reply=False,
        )
        _attach_to_message(message, attachment_metas)
    ticket = get_ticket(location, str(ticket.id))
    return serialize_ticket(ticket, include_messages=True)


def create_ticket_with_uploads(
    location: Location,
    *,
    user,
    subject: str,
    description: str = "",
    category: str = SupportTicket.Category.GENERAL,
    priority: str = SupportTicket.Priority.NORMAL,
    files: Optional[list] = None,
) -> dict[str, Any]:
    """Upload media to GHL first, then create the ticket (DB transaction)."""
    metas = _upload_files_to_ghl(location, files or [])
    return create_ticket(
        location,
        user=user,
        subject=subject,
        description=description,
        category=category,
        priority=priority,
        attachment_metas=metas,
    )


@transaction.atomic
def update_ticket_status(
    location: Location,
    ticket_id: str,
    *,
    status: str,
    user=None,
) -> dict[str, Any]:
    if status not in VALID_STATUSES:
        raise ValidationError("Invalid status.")
    ticket = get_ticket(location, ticket_id)
    old = ticket.status
    if old == status:
        return serialize_ticket(ticket, include_messages=True)

    ticket.status = status
    if status in (SupportTicket.Status.RESOLVED, SupportTicket.Status.CLOSED):
        ticket.resolved_at = timezone.now()
    elif old in (SupportTicket.Status.RESOLVED, SupportTicket.Status.CLOSED):
        ticket.resolved_at = None
    ticket.save(update_fields=["status", "resolved_at", "updated_at"])

    SupportMessage.objects.create(
        ticket=ticket,
        author=user if getattr(user, "is_authenticated", False) else None,
        body=f"Status changed to {ticket.get_status_display()}.",
        is_staff_reply=True,
    )
    ticket = get_ticket(location, ticket_id)
    return serialize_ticket(ticket, include_messages=True)


def _validate_upload_file(uploaded) -> tuple[str, str, int]:
    filename = (getattr(uploaded, "name", None) or "file").strip() or "file"
    content_type = (getattr(uploaded, "content_type", None) or "").lower().strip()
    size = int(getattr(uploaded, "size", 0) or 0)
    if size <= 0:
        raise ValidationError(f"Empty file: {filename}")
    if size > MAX_ATTACHMENT_BYTES:
        raise ValidationError(
            f"{filename} is too large (max {MAX_ATTACHMENT_BYTES // (1024 * 1024)} MB)."
        )
    # Infer from extension when browser sends octet-stream.
    if content_type not in ALLOWED_CONTENT_TYPES:
        lower = filename.lower()
        if lower.endswith((".jpg", ".jpeg")):
            content_type = "image/jpeg"
        elif lower.endswith(".png"):
            content_type = "image/png"
        elif lower.endswith(".gif"):
            content_type = "image/gif"
        elif lower.endswith(".webp"):
            content_type = "image/webp"
        elif lower.endswith(".mp4"):
            content_type = "video/mp4"
        elif lower.endswith(".mov"):
            content_type = "video/quicktime"
        elif lower.endswith(".webm"):
            content_type = "video/webm"
    if content_type not in ALLOWED_CONTENT_TYPES:
        raise ValidationError(
            f"Unsupported file type for {filename}. Use images (jpg/png/gif/webp) or videos (mp4/mov/webm)."
        )
    return filename, content_type, size


def _upload_files_to_ghl(location: Location, files: list) -> list[dict[str, Any]]:
    if not files:
        return []
    if len(files) > MAX_ATTACHMENTS_PER_MESSAGE:
        raise ValidationError(
            f"You can attach at most {MAX_ATTACHMENTS_PER_MESSAGE} files per message."
        )
    uploaded_meta: list[dict[str, Any]] = []
    for uploaded in files:
        if not uploaded:
            continue
        filename, content_type, size = _validate_upload_file(uploaded)
        meta = upload_to_location_folder(
            location,
            folder_name=LocationMediaFolder.FOLDER_SUPPORT_MEDIA,
            file_obj=uploaded,
            display_name=filename,
            content_type=content_type,
            filename=filename,
        )
        uploaded_meta.append(
            {
                "ghl_file_id": meta["ghl_file_id"],
                "url": meta["url"],
                "filename": filename,
                "content_type": content_type,
                "size_bytes": size,
            }
        )
    return uploaded_meta


def _attach_to_message(message: SupportMessage, metas: list[dict[str, Any]]) -> None:
    for meta in metas:
        SupportAttachment.objects.create(
            message=message,
            ghl_file_id=meta.get("ghl_file_id") or "",
            url=meta["url"],
            filename=meta.get("filename") or "",
            content_type=meta.get("content_type") or "",
            size_bytes=meta.get("size_bytes"),
        )


def _bump_ticket_after_message(
    ticket: SupportTicket, *, is_staff_reply: bool
) -> None:
    if is_staff_reply and ticket.status == SupportTicket.Status.WAITING_ON_SUPPORT:
        ticket.status = SupportTicket.Status.WAITING_ON_CUSTOMER
        ticket.save(update_fields=["status", "updated_at"])
    elif not is_staff_reply and ticket.status in (
        SupportTicket.Status.OPEN,
        SupportTicket.Status.WAITING_ON_CUSTOMER,
        SupportTicket.Status.RESOLVED,
    ):
        ticket.status = SupportTicket.Status.WAITING_ON_SUPPORT
        if ticket.resolved_at:
            ticket.resolved_at = None
            ticket.save(update_fields=["status", "resolved_at", "updated_at"])
        else:
            ticket.save(update_fields=["status", "updated_at"])
    else:
        ticket.save(update_fields=["updated_at"])


@transaction.atomic
def add_message(
    location: Location,
    ticket_id: str,
    *,
    user,
    body: str,
    is_staff_reply: bool = False,
    attachment_metas: Optional[list[dict[str, Any]]] = None,
) -> dict[str, Any]:
    body = (body or "").strip()
    attachment_metas = attachment_metas or []
    if not body and not attachment_metas:
        raise ValidationError("Add a message or attach a file.")
    if len(body) > 10000:
        raise ValidationError("Message is too long.")

    ticket = get_ticket(location, ticket_id)
    if ticket.status == SupportTicket.Status.CLOSED:
        raise ValidationError("This ticket is closed. Reopen it before replying.")

    message = SupportMessage.objects.create(
        ticket=ticket,
        author=user if getattr(user, "is_authenticated", False) else None,
        body=body,
        is_staff_reply=is_staff_reply,
    )
    _attach_to_message(message, attachment_metas)
    _bump_ticket_after_message(ticket, is_staff_reply=is_staff_reply)

    ticket = get_ticket(location, ticket_id)
    return serialize_ticket(ticket, include_messages=True)


def add_message_with_uploads(
    location: Location,
    ticket_id: str,
    *,
    user,
    body: str,
    is_staff_reply: bool = False,
    files: Optional[list] = None,
) -> dict[str, Any]:
    """Upload media to GHL first, then create the message + attachment rows."""
    # Validate ticket exists / not closed before uploading (cheap fail-fast).
    ticket = get_ticket(location, ticket_id)
    if ticket.status == SupportTicket.Status.CLOSED:
        raise ValidationError("This ticket is closed. Reopen it before replying.")
    metas = _upload_files_to_ghl(location, files or [])
    return add_message(
        location,
        ticket_id,
        user=user,
        body=body,
        is_staff_reply=is_staff_reply,
        attachment_metas=metas,
    )
