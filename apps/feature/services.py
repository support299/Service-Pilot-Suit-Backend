"""Feature Center domain services."""
from __future__ import annotations

from typing import Any, Optional

from django.db import transaction
from django.db.models import Count, Q, QuerySet
from django.utils import timezone

from apps.common.exceptions import NotFoundError, PermissionDeniedError, ValidationError
from apps.tenancy.models import Location

from .models import (
    FeatureComment,
    FeatureReleaseNote,
    FeatureRequest,
    FeatureStatusEvent,
    FeatureVote,
)

VALID_STATUSES = {c.value for c in FeatureRequest.Status}
VALID_CATEGORIES = {c.value for c in FeatureRequest.Category}
VALID_NOTE_STATUSES = {c.value for c in FeatureReleaseNote.NoteStatus}
COLLABORATION_LOCKED_STATUSES = {FeatureRequest.Status.RELEASED}

# Explicit workflow — invalid jumps are rejected in the service layer.
ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    FeatureRequest.Status.SUBMITTED: {
        FeatureRequest.Status.UNDER_REVIEW,
        FeatureRequest.Status.PLANNED,
        FeatureRequest.Status.DECLINED,
    },
    FeatureRequest.Status.UNDER_REVIEW: {
        FeatureRequest.Status.SUBMITTED,
        FeatureRequest.Status.PLANNED,
        FeatureRequest.Status.IN_PROGRESS,
        FeatureRequest.Status.DECLINED,
    },
    FeatureRequest.Status.PLANNED: {
        FeatureRequest.Status.UNDER_REVIEW,
        FeatureRequest.Status.IN_PROGRESS,
        FeatureRequest.Status.DECLINED,
    },
    FeatureRequest.Status.IN_PROGRESS: {
        FeatureRequest.Status.PLANNED,
        FeatureRequest.Status.TESTING,
        FeatureRequest.Status.DECLINED,
    },
    FeatureRequest.Status.TESTING: {
        FeatureRequest.Status.IN_PROGRESS,
        FeatureRequest.Status.RELEASED,
        FeatureRequest.Status.DECLINED,
    },
    FeatureRequest.Status.RELEASED: set(),
    FeatureRequest.Status.DECLINED: {
        FeatureRequest.Status.UNDER_REVIEW,
    },
}

SORT_OPTIONS = {
    "votes": ("-vote_count", "-updated_at"),
    "newest": ("-created_at",),
    "updated": ("-updated_at",),
}


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


def category_catalog() -> list[dict[str, str]]:
    return [{"value": c.value, "label": c.label} for c in FeatureRequest.Category]


def status_catalog() -> list[dict[str, str]]:
    return [{"value": s.value, "label": s.label} for s in FeatureRequest.Status]


def _base_queryset() -> QuerySet[FeatureRequest]:
    return FeatureRequest.objects.select_related(
        "created_by",
        "source_agency",
        "source_location",
        "updated_by",
    ).annotate(vote_count=Count("votes", distinct=True))


def get_request(request_id: str) -> FeatureRequest:
    try:
        return _base_queryset().get(pk=request_id)
    except (FeatureRequest.DoesNotExist, ValueError, TypeError) as exc:
        raise NotFoundError("Feature request not found.") from exc


def _get_request_for_update(request_id: str) -> FeatureRequest:
    """Lock only the feature row — no nullable joins (Postgres FOR UPDATE rule)."""
    try:
        return FeatureRequest.objects.select_for_update().get(pk=request_id)
    except (FeatureRequest.DoesNotExist, ValueError, TypeError) as exc:
        raise NotFoundError("Feature request not found.") from exc


def _voted_ids_for_user(user, request_ids: list) -> set:
    if not user or not getattr(user, "is_authenticated", False) or not request_ids:
        return set()
    return set(
        FeatureVote.objects.filter(
            user=user,
            feature_request_id__in=request_ids,
        ).values_list("feature_request_id", flat=True)
    )


def serialize_release_note(
    note: FeatureReleaseNote,
    *,
    include_staff: bool = False,
) -> dict[str, Any]:
    data: dict[str, Any] = {
        "id": str(note.id),
        "title": note.title,
        "body": note.body,
        "status": note.status,
        "status_label": note.get_status_display(),
        "feature_request_id": str(note.feature_request_id) if note.feature_request_id else None,
        "published_at": note.published_at.isoformat() if note.published_at else None,
        "created_at": note.created_at.isoformat(),
        "updated_at": note.updated_at.isoformat(),
    }
    if include_staff:
        data["published_by"] = _user_payload(note.published_by)
    return data


def serialize_status_event(event: FeatureStatusEvent) -> dict[str, Any]:
    return {
        "id": str(event.id),
        "previous_status": event.previous_status or None,
        "previous_status_label": (
            dict(FeatureRequest.Status.choices).get(event.previous_status)
            if event.previous_status
            else None
        ),
        "new_status": event.new_status,
        "new_status_label": dict(FeatureRequest.Status.choices).get(
            event.new_status, event.new_status
        ),
        "actor": _user_payload(event.actor),
        "created_at": event.created_at.isoformat(),
    }


def _public_author_payload(user) -> dict[str, Any] | None:
    """Customer-safe author — display name only (no email)."""
    if user is None:
        return None
    full_name = (getattr(user, "get_full_name", None) and user.get_full_name()) or ""
    if not full_name:
        email = getattr(user, "email", "") or ""
        full_name = email.split("@")[0] if email else "Community member"
    return {
        "id": str(user.pk),
        "full_name": full_name,
    }


def serialize_comment(
    comment: FeatureComment,
    *,
    include_staff: bool = False,
) -> dict[str, Any]:
    data: dict[str, Any] = {
        "id": str(comment.id),
        "body": comment.body,
        "created_at": comment.created_at.isoformat(),
        "is_internal": comment.is_internal,
    }
    if include_staff or comment.is_internal:
        data["author"] = _user_payload(comment.author)
    else:
        data["author"] = _public_author_payload(comment.author)
    return data


def serialize_feature_request(
    fr: FeatureRequest,
    *,
    user=None,
    voted_ids: Optional[set] = None,
    include_staff: bool = False,
    include_detail: bool = False,
) -> dict[str, Any]:
    vote_count = int(getattr(fr, "vote_count", None) or 0)
    if voted_ids is None:
        has_voted = bool(
            user
            and getattr(user, "is_authenticated", False)
            and FeatureVote.objects.filter(feature_request=fr, user=user).exists()
        )
    else:
        has_voted = fr.id in voted_ids

    data: dict[str, Any] = {
        "id": str(fr.id),
        "title": fr.title,
        "description": fr.description,
        "category": fr.category,
        "category_label": fr.get_category_display(),
        "status": fr.status,
        "status_label": fr.get_status_display(),
        "vote_count": vote_count,
        "has_voted": has_voted,
        "collaboration_locked": fr.collaboration_locked,
        "created_at": fr.created_at.isoformat(),
        "updated_at": fr.updated_at.isoformat(),
    }

    if include_staff:
        data["created_by"] = _user_payload(fr.created_by)
        data["updated_by"] = _user_payload(fr.updated_by)
        data["source"] = {
            "agency_id": str(fr.source_agency_id) if fr.source_agency_id else None,
            "agency_name": fr.source_agency.name if fr.source_agency_id else "",
            "location_id": (
                fr.source_location.ghl_location_id if fr.source_location_id else None
            ),
            "location_name": fr.source_location.name if fr.source_location_id else "",
        }

    if include_detail:
        events = (
            fr.status_events.select_related("actor").order_by("created_at")
        )
        data["status_history"] = [serialize_status_event(e) for e in events]

        published_notes = fr.release_notes.filter(
            status=FeatureReleaseNote.NoteStatus.PUBLISHED
        ).order_by("-published_at", "-created_at")
        data["release_notes"] = [
            serialize_release_note(n, include_staff=include_staff) for n in published_notes
        ]

        public_comments = (
            fr.comments.filter(is_internal=False)
            .select_related("author")
            .order_by("created_at")
        )
        data["comments"] = [
            serialize_comment(c, include_staff=False) for c in public_comments
        ]
        data["comment_count"] = len(data["comments"])

        if include_staff:
            internal = (
                fr.comments.filter(is_internal=True)
                .select_related("author")
                .order_by("created_at")
            )
            data["internal_comments"] = [
                serialize_comment(c, include_staff=True) for c in internal
            ]
            all_notes = fr.release_notes.select_related("published_by").order_by(
                "-created_at"
            )
            data["all_release_notes"] = [
                serialize_release_note(n, include_staff=True) for n in all_notes
            ]

    return data


def list_feature_requests(
    *,
    user,
    status: Optional[str] = None,
    category: Optional[str] = None,
    search: Optional[str] = None,
    sort: str = "votes",
    page: int = 1,
    page_size: int = 25,
    include_staff: bool = False,
    exclude_released: bool = False,
) -> dict[str, Any]:
    qs = _base_queryset()

    if status and status != "all":
        if status not in VALID_STATUSES:
            raise ValidationError("Invalid status filter.")
        qs = qs.filter(status=status)
    if exclude_released and (not status or status == "all"):
        qs = qs.exclude(status=FeatureRequest.Status.RELEASED)

    if category and category != "all":
        if category not in VALID_CATEGORIES:
            raise ValidationError("Invalid category filter.")
        qs = qs.filter(category=category)

    q = (search or "").strip()
    if q:
        qs = qs.filter(Q(title__icontains=q) | Q(description__icontains=q))

    ordering = SORT_OPTIONS.get(sort) or SORT_OPTIONS["votes"]
    qs = qs.order_by(*ordering)

    page = max(1, int(page or 1))
    page_size = min(200, max(1, int(page_size or 25)))
    total = qs.count()
    start = (page - 1) * page_size
    rows = list(qs[start : start + page_size])
    voted = _voted_ids_for_user(user, [r.id for r in rows])

    return {
        "count": total,
        "page": page,
        "page_size": page_size,
        "num_pages": max(1, (total + page_size - 1) // page_size) if total else 1,
        "results": [
            serialize_feature_request(
                r, user=user, voted_ids=voted, include_staff=include_staff
            )
            for r in rows
        ],
        "categories": category_catalog(),
        "statuses": status_catalog(),
    }


def feature_summary(*, user) -> dict[str, Any]:
    by_status = {s.value: 0 for s in FeatureRequest.Status}
    for row in FeatureRequest.objects.values("status").annotate(count=Count("id")):
        by_status[row["status"]] = row["count"]

    total = sum(by_status.values())
    open_count = total - by_status.get(FeatureRequest.Status.RELEASED, 0) - by_status.get(
        FeatureRequest.Status.DECLINED, 0
    )
    my_votes = 0
    if user and getattr(user, "is_authenticated", False):
        my_votes = FeatureVote.objects.filter(user=user).count()

    published_notes = FeatureReleaseNote.objects.filter(
        status=FeatureReleaseNote.NoteStatus.PUBLISHED
    ).count()

    return {
        "by_status": by_status,
        "total": total,
        "open_count": open_count,
        "released_count": by_status.get(FeatureRequest.Status.RELEASED, 0),
        "my_votes": my_votes,
        "published_announcements": published_notes,
        "categories": category_catalog(),
        "statuses": status_catalog(),
    }


def home_payload(*, user) -> dict[str, Any]:
    """Customer home: announcements, popular, recently updated / released."""
    summary = feature_summary(user=user)

    announcements_qs = (
        FeatureReleaseNote.objects.filter(status=FeatureReleaseNote.NoteStatus.PUBLISHED)
        .select_related("feature_request")
        .order_by("-published_at", "-created_at")[:8]
    )
    announcements = [serialize_release_note(n) for n in announcements_qs]

    # Released without a published note still appear as soft announcements.
    released_with_notes = {
        n.feature_request_id for n in announcements_qs if n.feature_request_id
    }
    released_fallback = (
        _base_queryset()
        .filter(status=FeatureRequest.Status.RELEASED)
        .exclude(id__in=released_with_notes)
        .order_by("-updated_at")[:5]
    )
    for fr in released_fallback:
        announcements.append(
            {
                "id": f"released-feature:{fr.id}",
                "title": fr.title,
                "body": fr.description,
                "status": FeatureReleaseNote.NoteStatus.PUBLISHED,
                "status_label": "Published",
                "feature_request_id": str(fr.id),
                "published_at": fr.updated_at.isoformat(),
                "created_at": fr.created_at.isoformat(),
                "updated_at": fr.updated_at.isoformat(),
                "is_fallback": True,
            }
        )
    announcements.sort(
        key=lambda a: a.get("published_at") or a.get("updated_at") or "",
        reverse=True,
    )
    announcements = announcements[:8]

    popular = list(
        _base_queryset()
        .exclude(status__in=[FeatureRequest.Status.RELEASED, FeatureRequest.Status.DECLINED])
        .order_by("-vote_count", "-updated_at")[:6]
    )
    recent = list(
        _base_queryset()
        .exclude(status=FeatureRequest.Status.DECLINED)
        .order_by("-updated_at")[:6]
    )
    voted = _voted_ids_for_user(user, [r.id for r in popular + recent])

    return {
        "summary": summary,
        "announcements": announcements,
        "popular": [
            serialize_feature_request(r, user=user, voted_ids=voted) for r in popular
        ],
        "recently_updated": [
            serialize_feature_request(r, user=user, voted_ids=voted) for r in recent
        ],
        "categories": category_catalog(),
        "statuses": status_catalog(),
    }


@transaction.atomic
def create_feature_request(
    *,
    location: Location,
    user,
    title: str,
    description: str,
    category: str = FeatureRequest.Category.OTHER,
) -> dict[str, Any]:
    title = (title or "").strip()
    description = (description or "").strip()
    category = (category or FeatureRequest.Category.OTHER).strip()

    if not title:
        raise ValidationError("Title is required.")
    if len(title) > 255:
        raise ValidationError("Title is too long.")
    if not description:
        raise ValidationError("Description is required.")
    if category not in VALID_CATEGORIES:
        raise ValidationError("Invalid category.")

    fr = FeatureRequest.objects.create(
        title=title,
        description=description,
        category=category,
        status=FeatureRequest.Status.SUBMITTED,
        created_by=user,
        updated_by=user,
        source_agency=getattr(location, "agency", None),
        source_location=location,
    )
    FeatureStatusEvent.objects.create(
        feature_request=fr,
        actor=user,
        previous_status="",
        new_status=FeatureRequest.Status.SUBMITTED,
    )
    fr = get_request(str(fr.id))
    return serialize_feature_request(fr, user=user, include_detail=True)


def get_feature_detail(
    request_id: str,
    *,
    user,
    include_staff: bool = False,
) -> dict[str, Any]:
    fr = get_request(request_id)
    return serialize_feature_request(
        fr,
        user=user,
        include_staff=include_staff,
        include_detail=True,
    )


@transaction.atomic
def add_vote(*, request_id: str, user) -> dict[str, Any]:
    fr = get_request(request_id)
    if fr.status in COLLABORATION_LOCKED_STATUSES:
        raise ValidationError(
            "Voting is closed for released features.",
            code="collaboration_locked",
        )
    FeatureVote.objects.get_or_create(feature_request=fr, user=user)
    fr = get_request(request_id)
    return serialize_feature_request(fr, user=user)


@transaction.atomic
def remove_vote(*, request_id: str, user) -> dict[str, Any]:
    fr = get_request(request_id)
    if fr.status in COLLABORATION_LOCKED_STATUSES:
        raise ValidationError(
            "Voting is closed for released features.",
            code="collaboration_locked",
        )
    FeatureVote.objects.filter(feature_request=fr, user=user).delete()
    fr = get_request(request_id)
    return serialize_feature_request(fr, user=user)


@transaction.atomic
def update_status(*, request_id: str, user, status: str) -> dict[str, Any]:
    status = (status or "").strip()
    if status not in VALID_STATUSES:
        raise ValidationError("Invalid status.")

    fr = _get_request_for_update(request_id)
    previous = fr.status
    if previous == status:
        raise ValidationError("Status is unchanged.", code="status_unchanged")

    allowed = ALLOWED_TRANSITIONS.get(previous, set())
    if status not in allowed:
        raise ValidationError(
            f"Cannot change status from {previous} to {status}.",
            code="invalid_transition",
            details={"from": previous, "to": status, "allowed": sorted(allowed)},
        )

    fr.status = status
    fr.updated_by = user
    fr.save(update_fields=["status", "updated_by", "updated_at"])
    FeatureStatusEvent.objects.create(
        feature_request=fr,
        actor=user,
        previous_status=previous,
        new_status=status,
    )
    return get_feature_detail(str(fr.id), user=user, include_staff=True)


@transaction.atomic
def add_public_comment(*, request_id: str, user, body: str) -> dict[str, Any]:
    body = (body or "").strip()
    if not body:
        raise ValidationError("Comment body is required.")
    if len(body) > 5000:
        raise ValidationError("Comment is too long.")
    fr = get_request(request_id)
    if fr.status in COLLABORATION_LOCKED_STATUSES:
        raise ValidationError(
            "Comments are closed for released features.",
            code="collaboration_locked",
        )
    comment = FeatureComment.objects.create(
        feature_request=fr,
        author=user,
        body=body,
        is_internal=False,
    )
    return serialize_comment(comment, include_staff=False)


@transaction.atomic
def add_internal_comment(*, request_id: str, user, body: str) -> dict[str, Any]:
    body = (body or "").strip()
    if not body:
        raise ValidationError("Comment body is required.")
    fr = get_request(request_id)
    comment = FeatureComment.objects.create(
        feature_request=fr,
        author=user,
        body=body,
        is_internal=True,
    )
    return serialize_comment(comment, include_staff=True)


def list_published_announcements(*, limit: int = 50) -> dict[str, Any]:
    limit = min(100, max(1, int(limit or 50)))
    rows = (
        FeatureReleaseNote.objects.filter(status=FeatureReleaseNote.NoteStatus.PUBLISHED)
        .select_related("feature_request")
        .order_by("-published_at", "-created_at")[:limit]
    )
    return {
        "count": len(rows),
        "results": [serialize_release_note(n) for n in rows],
    }


def list_release_notes_staff(
    *,
    request_id: Optional[str] = None,
    status: Optional[str] = None,
) -> dict[str, Any]:
    qs = FeatureReleaseNote.objects.select_related(
        "feature_request", "published_by"
    ).order_by("-created_at")
    if request_id:
        qs = qs.filter(feature_request_id=request_id)
    if status and status != "all":
        if status not in VALID_NOTE_STATUSES:
            raise ValidationError("Invalid release note status.")
        qs = qs.filter(status=status)
    rows = list(qs[:200])
    return {
        "count": len(rows),
        "results": [serialize_release_note(n, include_staff=True) for n in rows],
    }


@transaction.atomic
def create_release_note(
    *,
    user,
    title: str,
    body: str,
    request_id: Optional[str] = None,
    publish: bool = False,
) -> dict[str, Any]:
    title = (title or "").strip()
    body = (body or "").strip()
    if not title:
        raise ValidationError("Title is required.")
    if not body:
        raise ValidationError("Body is required.")

    fr = get_request(request_id) if request_id else None
    note = FeatureReleaseNote(
        feature_request=fr,
        title=title,
        body=body,
        status=FeatureReleaseNote.NoteStatus.DRAFT,
    )
    if publish:
        note.status = FeatureReleaseNote.NoteStatus.PUBLISHED
        note.published_at = timezone.now()
        note.published_by = user
    note.save()
    return serialize_release_note(note, include_staff=True)


@transaction.atomic
def update_release_note(
    *,
    note_id: str,
    user,
    title: Optional[str] = None,
    body: Optional[str] = None,
    request_id: Optional[str] = None,
) -> dict[str, Any]:
    try:
        note = FeatureReleaseNote.objects.select_for_update().get(pk=note_id)
    except FeatureReleaseNote.DoesNotExist as exc:
        raise NotFoundError("Release note not found.") from exc

    if title is not None:
        title = title.strip()
        if not title:
            raise ValidationError("Title is required.")
        note.title = title
    if body is not None:
        body = body.strip()
        if not body:
            raise ValidationError("Body is required.")
        note.body = body
    if request_id is not None:
        note.feature_request = get_request(request_id) if request_id else None
    note.save()
    return serialize_release_note(note, include_staff=True)


@transaction.atomic
def publish_release_note(*, note_id: str, user) -> dict[str, Any]:
    try:
        note = FeatureReleaseNote.objects.select_for_update().get(pk=note_id)
    except FeatureReleaseNote.DoesNotExist as exc:
        raise NotFoundError("Release note not found.") from exc
    if note.status == FeatureReleaseNote.NoteStatus.ARCHIVED:
        raise ValidationError("Archived release notes cannot be published. Create a new note.")
    note.status = FeatureReleaseNote.NoteStatus.PUBLISHED
    note.published_at = timezone.now()
    note.published_by = user
    note.save(update_fields=["status", "published_at", "published_by", "updated_at"])
    return serialize_release_note(note, include_staff=True)


@transaction.atomic
def archive_release_note(*, note_id: str, user) -> dict[str, Any]:
    try:
        note = FeatureReleaseNote.objects.select_for_update().get(pk=note_id)
    except FeatureReleaseNote.DoesNotExist as exc:
        raise NotFoundError("Release note not found.") from exc
    note.status = FeatureReleaseNote.NoteStatus.ARCHIVED
    note.save(update_fields=["status", "updated_at"])
    return serialize_release_note(note, include_staff=True)


def assert_staff_manage(user) -> None:
    """Defense-in-depth for service callers (views also gate with RBAC)."""
    if not user or not getattr(user, "is_authenticated", False):
        raise PermissionDeniedError()
    if getattr(user, "is_superuser", False):
        return
    # Role-based feature.manage is enforced at the view layer via HasPermission.
    # This helper is for optional internal guards only.
