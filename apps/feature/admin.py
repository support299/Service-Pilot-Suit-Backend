from django.contrib import admin

from .models import (
    FeatureComment,
    FeatureReleaseNote,
    FeatureRequest,
    FeatureStatusEvent,
    FeatureVote,
)


class FeatureVoteInline(admin.TabularInline):
    model = FeatureVote
    extra = 0
    readonly_fields = ("created_at", "updated_at")


class FeatureCommentInline(admin.TabularInline):
    model = FeatureComment
    extra = 0
    readonly_fields = ("created_at", "updated_at")
    fields = ("author", "body", "is_internal", "created_at")


class FeatureStatusEventInline(admin.TabularInline):
    model = FeatureStatusEvent
    extra = 0
    readonly_fields = ("created_at", "updated_at", "actor", "previous_status", "new_status")
    can_delete = False


@admin.register(FeatureRequest)
class FeatureRequestAdmin(admin.ModelAdmin):
    list_display = (
        "title",
        "category",
        "status",
        "source_location",
        "created_by",
        "updated_at",
    )
    list_filter = ("status", "category")
    search_fields = ("title", "description")
    readonly_fields = ("created_at", "updated_at")
    inlines = [FeatureStatusEventInline, FeatureCommentInline, FeatureVoteInline]


@admin.register(FeatureVote)
class FeatureVoteAdmin(admin.ModelAdmin):
    list_display = ("feature_request", "user", "created_at")
    search_fields = ("feature_request__title", "user__email")
    readonly_fields = ("created_at", "updated_at")


@admin.register(FeatureComment)
class FeatureCommentAdmin(admin.ModelAdmin):
    list_display = ("feature_request", "author", "is_internal", "created_at")
    list_filter = ("is_internal",)
    search_fields = ("body", "feature_request__title")
    readonly_fields = ("created_at", "updated_at")


@admin.register(FeatureStatusEvent)
class FeatureStatusEventAdmin(admin.ModelAdmin):
    list_display = ("feature_request", "previous_status", "new_status", "actor", "created_at")
    list_filter = ("new_status",)
    readonly_fields = ("created_at", "updated_at")


@admin.register(FeatureReleaseNote)
class FeatureReleaseNoteAdmin(admin.ModelAdmin):
    list_display = ("title", "status", "feature_request", "published_at", "updated_at")
    list_filter = ("status",)
    search_fields = ("title", "body")
    readonly_fields = ("created_at", "updated_at")
