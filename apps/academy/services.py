"""Academy domain services + JSON serialization."""
from __future__ import annotations

from typing import Any, Optional

from django.db import transaction
from django.db.models import Count, Prefetch, Q
from django.utils import timezone
from django.utils.text import slugify

from apps.common.exceptions import NotFoundError, ValidationError
from apps.tenancy.models import Location

from .models import (
    AcademyCourse,
    AcademyCourseCompletion,
    AcademyLesson,
    AcademyLessonProgress,
    AcademySavedContent,
)


def _duration_label(minutes: int) -> str:
    m = int(minutes or 0)
    if m <= 0:
        return ""
    if m < 60:
        return f"{m} min"
    hours, rem = divmod(m, 60)
    if rem == 0:
        return f"{hours}h"
    return f"{hours}h {rem}m"


def serialize_course(
    course: AcademyCourse,
    *,
    lesson_count: Optional[int] = None,
    completion: Optional[AcademyCourseCompletion] = None,
    saved: bool = False,
) -> dict[str, Any]:
    if lesson_count is None:
        lesson_count = getattr(course, "published_lesson_count", None)
        if lesson_count is None:
            lesson_count = course.lessons.filter(
                status=AcademyLesson.Status.PUBLISHED
            ).count()

    data: dict[str, Any] = {
        "id": str(course.id),
        "slug": course.slug,
        "title": course.title,
        "description": course.description,
        "body": course.body,
        "course_type": course.course_type,
        "course_type_label": course.get_course_type_display(),
        "section_key": course.section_key,
        "section_label": course.get_section_key_display(),
        "status": course.status,
        "duration_minutes": course.duration_minutes,
        "duration_label": _duration_label(course.duration_minutes),
        "sort_order": course.sort_order,
        "featured": course.featured,
        "video_url": course.video_url or "",
        "download_url": course.download_url or "",
        "thumbnail_url": course.thumbnail_url or "",
        "published_at": course.published_at.isoformat() if course.published_at else None,
        "lesson_count": int(lesson_count or 0),
        "saved": saved,
        "completion": None,
    }
    if completion is not None:
        data["completion"] = {
            "completed_lesson_count": completion.completed_lesson_count,
            "total_lesson_count": completion.total_lesson_count,
            "percent_complete": completion.percent_complete,
            "completed_at": (
                completion.completed_at.isoformat() if completion.completed_at else None
            ),
        }
    return data


def serialize_lesson(
    lesson: AcademyLesson,
    *,
    progress: Optional[AcademyLessonProgress] = None,
    saved: bool = False,
    include_course: bool = False,
) -> dict[str, Any]:
    data: dict[str, Any] = {
        "id": str(lesson.id),
        "course_id": str(lesson.course_id),
        "title": lesson.title,
        "description": lesson.description,
        "body": lesson.body,
        "lesson_type": lesson.lesson_type,
        "lesson_type_label": lesson.get_lesson_type_display(),
        "status": lesson.status,
        "duration_minutes": lesson.duration_minutes,
        "duration_label": _duration_label(lesson.duration_minutes),
        "sort_order": lesson.sort_order,
        "video_url": lesson.video_url or "",
        "download_url": lesson.download_url or "",
        "saved": saved,
        "progress": None,
    }
    if progress is not None:
        data["progress"] = {
            "status": progress.status,
            "percent_complete": progress.percent_complete,
            "started_at": progress.started_at.isoformat() if progress.started_at else None,
            "completed_at": (
                progress.completed_at.isoformat() if progress.completed_at else None
            ),
        }
    if include_course:
        data["course"] = {
            "id": str(lesson.course_id),
            "title": lesson.course.title,
            "slug": lesson.course.slug,
            "section_key": lesson.course.section_key,
        }
    return data


def academy_summary(location: Location, user) -> dict[str, Any]:
    courses = AcademyCourse.objects.filter(status=AcademyCourse.Status.PUBLISHED)
    course_ids = list(courses.values_list("id", flat=True))
    lesson_count = AcademyLesson.objects.filter(
        course_id__in=course_ids, status=AcademyLesson.Status.PUBLISHED
    ).count()
    completions = AcademyCourseCompletion.objects.filter(
        location=location, user=user, course_id__in=course_ids
    )
    completed = completions.filter(percent_complete=100).count()
    in_progress = completions.filter(
        percent_complete__gt=0, percent_complete__lt=100
    ).count()
    saved = AcademySavedContent.objects.filter(location=location, user=user).count()

    by_section: dict[str, int] = {}
    for row in (
        courses.values("section_key")
        .annotate(count=Count("id"))
        .order_by("section_key")
    ):
        by_section[row["section_key"]] = row["count"]

    return {
        "course_count": len(course_ids),
        "lesson_count": lesson_count,
        "completed_count": completed,
        "in_progress_count": in_progress,
        "saved_count": saved,
        "by_section": by_section,
    }


def list_courses(
    location: Location,
    user,
    *,
    section: Optional[str] = None,
    search: Optional[str] = None,
    include_unpublished: bool = False,
) -> list[dict[str, Any]]:
    qs = AcademyCourse.objects.all()
    if not include_unpublished:
        qs = qs.filter(status=AcademyCourse.Status.PUBLISHED)
    section = (section or "").strip()
    if section:
        qs = qs.filter(section_key=section)
    q = (search or "").strip()
    if q:
        qs = qs.filter(Q(title__icontains=q) | Q(description__icontains=q))

    qs = qs.annotate(
        published_lesson_count=Count(
            "lessons",
            filter=Q(lessons__status=AcademyLesson.Status.PUBLISHED),
        )
    ).order_by("sort_order", "title")

    course_ids = [c.id for c in qs]
    completions = {
        str(row.course_id): row
        for row in AcademyCourseCompletion.objects.filter(
            location=location, user=user, course_id__in=course_ids
        )
    }
    saved_ids = set(
        str(cid)
        for cid in AcademySavedContent.objects.filter(
            location=location, user=user, course_id__in=course_ids
        ).values_list("course_id", flat=True)
    )

    return [
        serialize_course(
            course,
            lesson_count=course.published_lesson_count,
            completion=completions.get(str(course.id)),
            saved=str(course.id) in saved_ids,
        )
        for course in qs
    ]


def get_course(
    location: Location,
    user,
    course_id: str,
    *,
    include_unpublished: bool = False,
) -> dict[str, Any]:
    qs = AcademyCourse.objects.prefetch_related(
        Prefetch(
            "lessons",
            queryset=AcademyLesson.objects.order_by("sort_order", "created_at"),
        )
    )
    course = qs.filter(pk=course_id).first()
    if course is None:
        raise NotFoundError("Course not found.")
    if (
        not include_unpublished
        and course.status != AcademyCourse.Status.PUBLISHED
    ):
        raise NotFoundError("Course not found.")

    lesson_qs = course.lessons.all()
    if not include_unpublished:
        lesson_ids = [
            lesson.id
            for lesson in lesson_qs
            if lesson.status == AcademyLesson.Status.PUBLISHED
        ]
    else:
        lesson_ids = [lesson.id for lesson in lesson_qs]

    progress_rows = {
        str(row.lesson_id): row
        for row in AcademyLessonProgress.objects.filter(
            location=location, user=user, lesson_id__in=lesson_ids
        )
    }
    completion = AcademyCourseCompletion.objects.filter(
        location=location, user=user, course=course
    ).first()
    saved = AcademySavedContent.objects.filter(
        location=location, user=user, course=course
    ).exists()

    lessons_out = []
    for lesson in lesson_qs:
        if (
            not include_unpublished
            and lesson.status != AcademyLesson.Status.PUBLISHED
        ):
            continue
        lessons_out.append(
            serialize_lesson(lesson, progress=progress_rows.get(str(lesson.id)))
        )

    data = serialize_course(
        course,
        lesson_count=len(lessons_out),
        completion=completion,
        saved=saved,
    )
    data["lessons"] = lessons_out
    return data


def get_lesson(
    location: Location,
    user,
    lesson_id: str,
    *,
    include_unpublished: bool = False,
) -> dict[str, Any]:
    lesson = (
        AcademyLesson.objects.select_related("course")
        .filter(pk=lesson_id)
        .first()
    )
    if lesson is None:
        raise NotFoundError("Lesson not found.")
    if not include_unpublished:
        if (
            lesson.status != AcademyLesson.Status.PUBLISHED
            or lesson.course.status != AcademyCourse.Status.PUBLISHED
        ):
            raise NotFoundError("Lesson not found.")

    progress = AcademyLessonProgress.objects.filter(
        location=location, user=user, lesson=lesson
    ).first()
    saved = AcademySavedContent.objects.filter(
        location=location, user=user, lesson=lesson
    ).exists()
    return serialize_lesson(
        lesson, progress=progress, saved=saved, include_course=True
    )


def recompute_course_completion(
    location: Location, user, course: AcademyCourse
) -> AcademyCourseCompletion:
    published = list(
        course.lessons.filter(status=AcademyLesson.Status.PUBLISHED)
    )
    total = len(published)
    if total == 0 and course.course_type == AcademyCourse.CourseType.VIDEO:
        # Video-only course with no lessons: treat explicit course completion
        # via a synthetic 100% when marked — handled by upsert with no lessons.
        total = 0

    completed_ids = set(
        AcademyLessonProgress.objects.filter(
            location=location,
            user=user,
            course=course,
            status=AcademyLessonProgress.ProgressStatus.COMPLETED,
            lesson_id__in=[l.id for l in published],
        ).values_list("lesson_id", flat=True)
    )
    done = len(completed_ids)
    percent = 100 if total == 0 else int(round((done / total) * 100))
    if total > 0 and done >= total:
        percent = 100

    defaults = {
        "completed_lesson_count": done,
        "total_lesson_count": total,
        "percent_complete": percent,
        "completed_at": timezone.now() if percent == 100 and total > 0 else None,
    }
    obj, _ = AcademyCourseCompletion.objects.update_or_create(
        location=location,
        user=user,
        course=course,
        defaults=defaults,
    )
    if percent < 100 and obj.completed_at is not None:
        obj.completed_at = None
        obj.save(update_fields=["completed_at", "updated_at"])
    return obj


@transaction.atomic
def upsert_lesson_progress(
    location: Location,
    user,
    *,
    lesson_id: str,
    status: str,
    percent_complete: Optional[int] = None,
) -> dict[str, Any]:
    lesson = (
        AcademyLesson.objects.select_related("course")
        .filter(pk=lesson_id, status=AcademyLesson.Status.PUBLISHED)
        .first()
    )
    if lesson is None or lesson.course.status != AcademyCourse.Status.PUBLISHED:
        raise NotFoundError("Lesson not found.")

    status = (status or "").strip()
    valid = {c.value for c in AcademyLessonProgress.ProgressStatus}
    if status not in valid:
        raise ValidationError("Invalid progress status.")

    if percent_complete is None:
        if status == AcademyLessonProgress.ProgressStatus.COMPLETED:
            percent_complete = 100
        elif status == AcademyLessonProgress.ProgressStatus.IN_PROGRESS:
            percent_complete = 50
        else:
            percent_complete = 0
    else:
        try:
            percent_complete = int(percent_complete)
        except (TypeError, ValueError) as exc:
            raise ValidationError("percent_complete must be a number.") from exc
    percent_complete = max(0, min(100, int(percent_complete)))

    now = timezone.now()
    row = AcademyLessonProgress.objects.filter(
        location=location, user=user, lesson=lesson
    ).first()
    if row is None:
        row = AcademyLessonProgress(
            location=location,
            user=user,
            course=lesson.course,
            lesson=lesson,
        )

    row.status = status
    row.percent_complete = percent_complete
    if status != AcademyLessonProgress.ProgressStatus.NOT_STARTED and not row.started_at:
        row.started_at = now
    if status == AcademyLessonProgress.ProgressStatus.COMPLETED:
        row.completed_at = now
        row.percent_complete = 100
    else:
        row.completed_at = None
    row.save()

    completion = recompute_course_completion(location, user, lesson.course)
    data = serialize_lesson(lesson, progress=row, include_course=True)
    data["course_completion"] = {
        "completed_lesson_count": completion.completed_lesson_count,
        "total_lesson_count": completion.total_lesson_count,
        "percent_complete": completion.percent_complete,
        "completed_at": (
            completion.completed_at.isoformat() if completion.completed_at else None
        ),
    }
    return data


def list_saved(location: Location, user) -> list[dict[str, Any]]:
    rows = (
        AcademySavedContent.objects.filter(location=location, user=user)
        .select_related("course", "lesson", "lesson__course")
        .order_by("-created_at")
    )
    out: list[dict[str, Any]] = []
    for row in rows:
        if row.course_id:
            out.append(
                {
                    "id": str(row.id),
                    "kind": "course",
                    "saved_at": row.created_at.isoformat(),
                    "course": serialize_course(row.course, saved=True),
                }
            )
        elif row.lesson_id:
            out.append(
                {
                    "id": str(row.id),
                    "kind": "lesson",
                    "saved_at": row.created_at.isoformat(),
                    "lesson": serialize_lesson(
                        row.lesson, saved=True, include_course=True
                    ),
                }
            )
    return out


@transaction.atomic
def save_content(
    location: Location,
    user,
    *,
    course_id: Optional[str] = None,
    lesson_id: Optional[str] = None,
) -> dict[str, Any]:
    course_id = (course_id or "").strip() or None
    lesson_id = (lesson_id or "").strip() or None
    if bool(course_id) == bool(lesson_id):
        raise ValidationError("Provide exactly one of course_id or lesson_id.")

    if course_id:
        course = AcademyCourse.objects.filter(
            pk=course_id, status=AcademyCourse.Status.PUBLISHED
        ).first()
        if course is None:
            raise NotFoundError("Course not found.")
        obj, _ = AcademySavedContent.objects.get_or_create(
            location=location, user=user, course=course, defaults={"lesson": None}
        )
        return {
            "id": str(obj.id),
            "kind": "course",
            "course_id": str(course.id),
        }

    lesson = (
        AcademyLesson.objects.select_related("course")
        .filter(pk=lesson_id, status=AcademyLesson.Status.PUBLISHED)
        .first()
    )
    if lesson is None or lesson.course.status != AcademyCourse.Status.PUBLISHED:
        raise NotFoundError("Lesson not found.")
    obj, _ = AcademySavedContent.objects.get_or_create(
        location=location, user=user, lesson=lesson, defaults={"course": None}
    )
    return {
        "id": str(obj.id),
        "kind": "lesson",
        "lesson_id": str(lesson.id),
        "course_id": str(lesson.course_id),
    }


@transaction.atomic
def unsave_content(
    location: Location,
    user,
    *,
    course_id: Optional[str] = None,
    lesson_id: Optional[str] = None,
) -> None:
    course_id = (course_id or "").strip() or None
    lesson_id = (lesson_id or "").strip() or None
    if bool(course_id) == bool(lesson_id):
        raise ValidationError("Provide exactly one of course_id or lesson_id.")
    qs = AcademySavedContent.objects.filter(location=location, user=user)
    if course_id:
        qs.filter(course_id=course_id).delete()
    else:
        qs.filter(lesson_id=lesson_id).delete()


def ensure_unique_slug(title: str, *, exclude_id=None) -> str:
    base = slugify(title)[:100] or "course"
    slug = base
    n = 2
    while True:
        qs = AcademyCourse.objects.filter(slug=slug)
        if exclude_id:
            qs = qs.exclude(pk=exclude_id)
        if not qs.exists():
            return slug
        slug = f"{base}-{n}"
        n += 1
