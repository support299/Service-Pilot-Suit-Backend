from django.contrib import admin

from .models import (
    AcademyCourse,
    AcademyCourseCompletion,
    AcademyLesson,
    AcademyLessonProgress,
    AcademySavedContent,
)


class AcademyLessonInline(admin.TabularInline):
    model = AcademyLesson
    extra = 0
    fields = (
        "title",
        "lesson_type",
        "status",
        "duration_minutes",
        "sort_order",
        "video_url",
    )


@admin.register(AcademyCourse)
class AcademyCourseAdmin(admin.ModelAdmin):
    list_display = (
        "title",
        "section_key",
        "course_type",
        "status",
        "featured",
        "sort_order",
        "published_at",
    )
    list_filter = ("status", "section_key", "course_type", "featured")
    search_fields = ("title", "slug", "description")
    prepopulated_fields = {"slug": ("title",)}
    inlines = [AcademyLessonInline]


@admin.register(AcademyLesson)
class AcademyLessonAdmin(admin.ModelAdmin):
    list_display = ("title", "course", "lesson_type", "status", "sort_order")
    list_filter = ("status", "lesson_type")
    search_fields = ("title", "course__title")


@admin.register(AcademyLessonProgress)
class AcademyLessonProgressAdmin(admin.ModelAdmin):
    list_display = ("user", "lesson", "location", "status", "percent_complete", "updated_at")
    list_filter = ("status",)


@admin.register(AcademyCourseCompletion)
class AcademyCourseCompletionAdmin(admin.ModelAdmin):
    list_display = (
        "user",
        "course",
        "location",
        "percent_complete",
        "completed_lesson_count",
        "total_lesson_count",
    )


@admin.register(AcademySavedContent)
class AcademySavedContentAdmin(admin.ModelAdmin):
    list_display = ("user", "location", "course", "lesson", "created_at")
