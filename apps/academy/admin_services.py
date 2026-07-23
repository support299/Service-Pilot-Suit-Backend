"""Agency-portal Academy catalog admin (create / edit / publish / delete)."""
from __future__ import annotations

from typing import Any, Optional

from django.db import transaction
from django.db.models import Count, Q
from django.utils import timezone

from apps.common.exceptions import NotFoundError, ValidationError

from .models import AcademyCourse, AcademyLesson
from .services import ensure_unique_slug, serialize_course, serialize_lesson


def meta_options() -> dict[str, Any]:
    return {
        "sections": [
            {"value": v, "label": label} for v, label in AcademyCourse.Section.choices
        ],
        "course_types": [
            {"value": v, "label": label} for v, label in AcademyCourse.CourseType.choices
        ],
        "lesson_types": [
            {"value": v, "label": label} for v, label in AcademyLesson.LessonType.choices
        ],
        "statuses": [
            {"value": v, "label": label} for v, label in AcademyCourse.Status.choices
        ],
    }


def serialize_course_admin(course: AcademyCourse) -> dict[str, Any]:
    lesson_total = getattr(course, "lesson_total", None)
    if lesson_total is None:
        lesson_total = course.lessons.count()
    published_lessons = getattr(course, "published_lesson_count", None)
    if published_lessons is None:
        published_lessons = course.lessons.filter(
            status=AcademyLesson.Status.PUBLISHED
        ).count()
    data = serialize_course(course, lesson_count=published_lessons)
    data["lesson_total"] = int(lesson_total or 0)
    data["created_at"] = course.created_at.isoformat() if course.created_at else None
    data["updated_at"] = course.updated_at.isoformat() if course.updated_at else None
    return data


def list_courses_admin(
    *,
    section: Optional[str] = None,
    status: Optional[str] = None,
    search: Optional[str] = None,
) -> list[dict[str, Any]]:
    qs = AcademyCourse.objects.all()
    section = (section or "").strip()
    if section:
        qs = qs.filter(section_key=section)
    status = (status or "").strip()
    if status:
        qs = qs.filter(status=status)
    q = (search or "").strip()
    if q:
        qs = qs.filter(Q(title__icontains=q) | Q(description__icontains=q) | Q(slug__icontains=q))

    qs = qs.annotate(
        lesson_total=Count("lessons"),
        published_lesson_count=Count(
            "lessons",
            filter=Q(lessons__status=AcademyLesson.Status.PUBLISHED),
        ),
    ).order_by("sort_order", "title")
    return [serialize_course_admin(c) for c in qs]


def get_course_admin(course_id: str) -> dict[str, Any]:
    course = (
        AcademyCourse.objects.prefetch_related("lessons")
        .filter(pk=course_id)
        .first()
    )
    if course is None:
        raise NotFoundError("Course not found.")
    data = serialize_course_admin(course)
    data["lessons"] = [
        serialize_lesson(lesson)
        for lesson in course.lessons.all().order_by("sort_order", "created_at")
    ]
    return data


def _apply_course_fields(course: AcademyCourse, payload: dict[str, Any]) -> None:
    if "title" in payload and payload["title"] is not None:
        title = str(payload["title"]).strip()
        if not title:
            raise ValidationError("Title is required.")
        course.title = title
    if "description" in payload:
        course.description = str(payload.get("description") or "")
    if "body" in payload:
        course.body = str(payload.get("body") or "")
    if "course_type" in payload and payload["course_type"]:
        ct = str(payload["course_type"])
        if ct not in {c.value for c in AcademyCourse.CourseType}:
            raise ValidationError("Invalid course_type.")
        course.course_type = ct
    if "section_key" in payload and payload["section_key"]:
        sk = str(payload["section_key"])
        if sk not in {c.value for c in AcademyCourse.Section}:
            raise ValidationError("Invalid section_key.")
        course.section_key = sk
    for int_field in ("duration_minutes", "sort_order"):
        if int_field in payload and payload[int_field] is not None:
            try:
                setattr(course, int_field, max(0, int(payload[int_field])))
            except (TypeError, ValueError) as exc:
                raise ValidationError(f"{int_field} must be a number.") from exc
    if "featured" in payload:
        course.featured = bool(payload["featured"])
    for url_field in ("video_url", "download_url", "thumbnail_url"):
        if url_field in payload:
            setattr(course, url_field, str(payload.get(url_field) or "").strip())


@transaction.atomic
def create_course(payload: dict[str, Any], *, user=None) -> dict[str, Any]:
    title = str(payload.get("title") or "").strip()
    if not title:
        raise ValidationError("Title is required.")
    course = AcademyCourse(
        title=title,
        slug=ensure_unique_slug(title),
        created_by=user if getattr(user, "is_authenticated", False) else None,
    )
    _apply_course_fields(course, payload)
    # Default draft unless explicitly published
    status = str(payload.get("status") or AcademyCourse.Status.DRAFT).strip()
    if status not in {c.value for c in AcademyCourse.Status}:
        raise ValidationError("Invalid status.")
    course.status = status
    if course.status == AcademyCourse.Status.PUBLISHED and not course.published_at:
        course.published_at = timezone.now()
    course.save()
    return get_course_admin(str(course.id))


@transaction.atomic
def update_course(course_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    course = AcademyCourse.objects.filter(pk=course_id).first()
    if course is None:
        raise NotFoundError("Course not found.")
    old_title = course.title
    _apply_course_fields(course, payload)
    if course.title != old_title and payload.get("regenerate_slug"):
        course.slug = ensure_unique_slug(course.title, exclude_id=course.id)
    if "status" in payload and payload["status"]:
        status = str(payload["status"]).strip()
        if status not in {c.value for c in AcademyCourse.Status}:
            raise ValidationError("Invalid status.")
        course.status = status
        if status == AcademyCourse.Status.PUBLISHED and not course.published_at:
            course.published_at = timezone.now()
        if status != AcademyCourse.Status.PUBLISHED:
            # keep published_at history when unpublishing
            pass
    course.save()
    return get_course_admin(str(course.id))


@transaction.atomic
def set_course_status(course_id: str, status: str) -> dict[str, Any]:
    return update_course(course_id, {"status": status})


@transaction.atomic
def delete_course(course_id: str) -> None:
    course = AcademyCourse.objects.filter(pk=course_id).first()
    if course is None:
        raise NotFoundError("Course not found.")
    course.delete()


def _apply_lesson_fields(lesson: AcademyLesson, payload: dict[str, Any]) -> None:
    if "title" in payload and payload["title"] is not None:
        title = str(payload["title"]).strip()
        if not title:
            raise ValidationError("Title is required.")
        lesson.title = title
    if "description" in payload:
        lesson.description = str(payload.get("description") or "")
    if "body" in payload:
        lesson.body = str(payload.get("body") or "")
    if "lesson_type" in payload and payload["lesson_type"]:
        lt = str(payload["lesson_type"])
        if lt not in {c.value for c in AcademyLesson.LessonType}:
            raise ValidationError("Invalid lesson_type.")
        lesson.lesson_type = lt
    for int_field in ("duration_minutes", "sort_order"):
        if int_field in payload and payload[int_field] is not None:
            try:
                setattr(lesson, int_field, max(0, int(payload[int_field])))
            except (TypeError, ValueError) as exc:
                raise ValidationError(f"{int_field} must be a number.") from exc
    for url_field in ("video_url", "download_url"):
        if url_field in payload:
            setattr(lesson, url_field, str(payload.get(url_field) or "").strip())


@transaction.atomic
def create_lesson(course_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    course = AcademyCourse.objects.filter(pk=course_id).first()
    if course is None:
        raise NotFoundError("Course not found.")
    title = str(payload.get("title") or "").strip()
    if not title:
        raise ValidationError("Title is required.")
    lesson = AcademyLesson(course=course, title=title)
    _apply_lesson_fields(lesson, payload)
    status = str(payload.get("status") or AcademyLesson.Status.DRAFT).strip()
    if status not in {c.value for c in AcademyLesson.Status}:
        raise ValidationError("Invalid status.")
    lesson.status = status
    if lesson.sort_order == 0:
        max_order = (
            course.lessons.order_by("-sort_order").values_list("sort_order", flat=True).first()
            or 0
        )
        lesson.sort_order = int(max_order) + 1
    lesson.save()
    return serialize_lesson(lesson)


@transaction.atomic
def update_lesson(lesson_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    lesson = AcademyLesson.objects.select_related("course").filter(pk=lesson_id).first()
    if lesson is None:
        raise NotFoundError("Lesson not found.")
    _apply_lesson_fields(lesson, payload)
    if "status" in payload and payload["status"]:
        status = str(payload["status"]).strip()
        if status not in {c.value for c in AcademyLesson.Status}:
            raise ValidationError("Invalid status.")
        lesson.status = status
    lesson.save()
    return serialize_lesson(lesson, include_course=True)


@transaction.atomic
def delete_lesson(lesson_id: str) -> None:
    lesson = AcademyLesson.objects.filter(pk=lesson_id).first()
    if lesson is None:
        raise NotFoundError("Lesson not found.")
    lesson.delete()
