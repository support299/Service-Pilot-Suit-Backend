"""Academy LMS models for the Success Center.

Platform catalog (courses/lessons) plus per-user progress scoped to the
current location (tenant), mirroring the reference Academy MVP.
"""
from __future__ import annotations

from django.conf import settings
from django.db import models

from apps.common.models import BaseModel


class AcademyCourse(BaseModel):
    class CourseType(models.TextChoices):
        COURSE = "course", "Course"
        VIDEO = "video", "Video"
        ARTICLE = "article", "Article"
        ONBOARDING = "onboarding", "Onboarding"
        KNOWLEDGE_BASE = "knowledge_base", "Knowledge base"
        LEARNING_PATH = "learning_path", "Learning path"

    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        PUBLISHED = "published", "Published"
        ARCHIVED = "archived", "Archived"

    class Section(models.TextChoices):
        GETTING_STARTED = "getting_started", "Getting started"
        COURSES = "courses", "Courses"
        LESSONS = "lessons", "Lessons"
        KNOWLEDGE_BASE = "knowledge_base", "Knowledge base"
        LEARNING_PATHS = "learning_paths", "Learning paths"
        HOW_TO = "how_to_use_service_pilot", "How to use Service Pilot"

    slug = models.SlugField(max_length=120, unique=True)
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True, default="")
    body = models.TextField(blank=True, default="")
    course_type = models.CharField(
        max_length=32,
        choices=CourseType.choices,
        default=CourseType.COURSE,
        db_index=True,
    )
    section_key = models.CharField(
        max_length=64,
        choices=Section.choices,
        default=Section.COURSES,
        db_index=True,
    )
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.DRAFT,
        db_index=True,
    )
    duration_minutes = models.PositiveIntegerField(default=0)
    sort_order = models.PositiveIntegerField(default=0, db_index=True)
    featured = models.BooleanField(default=False)
    video_url = models.URLField(blank=True, default="", max_length=1024)
    download_url = models.URLField(blank=True, default="", max_length=1024)
    thumbnail_url = models.URLField(blank=True, default="", max_length=1024)
    published_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="academy_courses_created",
    )

    class Meta:
        ordering = ["sort_order", "title"]
        indexes = [
            models.Index(fields=["status", "section_key", "sort_order"]),
        ]

    def __str__(self) -> str:
        return self.title


class AcademyLesson(BaseModel):
    class LessonType(models.TextChoices):
        ARTICLE = "article", "Article"
        VIDEO = "video", "Video"
        CHECKLIST = "checklist", "Checklist"
        DOWNLOAD = "download", "Download"

    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        PUBLISHED = "published", "Published"
        ARCHIVED = "archived", "Archived"

    course = models.ForeignKey(
        AcademyCourse,
        on_delete=models.CASCADE,
        related_name="lessons",
    )
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True, default="")
    body = models.TextField(blank=True, default="")
    lesson_type = models.CharField(
        max_length=32,
        choices=LessonType.choices,
        default=LessonType.ARTICLE,
    )
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.DRAFT,
        db_index=True,
    )
    duration_minutes = models.PositiveIntegerField(default=0)
    sort_order = models.PositiveIntegerField(default=0)
    video_url = models.URLField(blank=True, default="", max_length=1024)
    download_url = models.URLField(blank=True, default="", max_length=1024)

    class Meta:
        ordering = ["sort_order", "created_at"]
        indexes = [
            models.Index(fields=["course", "status", "sort_order"]),
        ]

    def __str__(self) -> str:
        return f"{self.course.title}: {self.title}"


class AcademyLessonProgress(BaseModel):
    class ProgressStatus(models.TextChoices):
        NOT_STARTED = "not_started", "Not started"
        IN_PROGRESS = "in_progress", "In progress"
        COMPLETED = "completed", "Completed"

    location = models.ForeignKey(
        "tenancy.Location",
        on_delete=models.CASCADE,
        related_name="academy_lesson_progress",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="academy_lesson_progress",
    )
    course = models.ForeignKey(
        AcademyCourse,
        on_delete=models.CASCADE,
        related_name="lesson_progress",
    )
    lesson = models.ForeignKey(
        AcademyLesson,
        on_delete=models.CASCADE,
        related_name="progress_rows",
    )
    status = models.CharField(
        max_length=16,
        choices=ProgressStatus.choices,
        default=ProgressStatus.NOT_STARTED,
        db_index=True,
    )
    percent_complete = models.PositiveSmallIntegerField(default=0)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["location", "user", "lesson"],
                name="unique_academy_lesson_progress",
            )
        ]
        indexes = [
            models.Index(fields=["location", "user", "course"]),
        ]

    def __str__(self) -> str:
        return f"{self.user_id} · {self.lesson_id} · {self.status}"


class AcademyCourseCompletion(BaseModel):
    location = models.ForeignKey(
        "tenancy.Location",
        on_delete=models.CASCADE,
        related_name="academy_course_completions",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="academy_course_completions",
    )
    course = models.ForeignKey(
        AcademyCourse,
        on_delete=models.CASCADE,
        related_name="completions",
    )
    completed_lesson_count = models.PositiveIntegerField(default=0)
    total_lesson_count = models.PositiveIntegerField(default=0)
    percent_complete = models.PositiveSmallIntegerField(default=0)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["location", "user", "course"],
                name="unique_academy_course_completion",
            )
        ]

    def __str__(self) -> str:
        return f"{self.user_id} · {self.course_id} · {self.percent_complete}%"


class AcademySavedContent(BaseModel):
    location = models.ForeignKey(
        "tenancy.Location",
        on_delete=models.CASCADE,
        related_name="academy_saved",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="academy_saved",
    )
    course = models.ForeignKey(
        AcademyCourse,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="saves",
    )
    lesson = models.ForeignKey(
        AcademyLesson,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="saves",
    )

    class Meta:
        constraints = [
            models.CheckConstraint(
                check=(
                    models.Q(course__isnull=False, lesson__isnull=True)
                    | models.Q(course__isnull=True, lesson__isnull=False)
                ),
                name="academy_saved_exactly_one_target",
            ),
            models.UniqueConstraint(
                fields=["location", "user", "course"],
                condition=models.Q(course__isnull=False),
                name="unique_academy_saved_course",
            ),
            models.UniqueConstraint(
                fields=["location", "user", "lesson"],
                condition=models.Q(lesson__isnull=False),
                name="unique_academy_saved_lesson",
            ),
        ]

    def __str__(self) -> str:
        target = self.course_id or self.lesson_id
        return f"saved {target} by {self.user_id}"
