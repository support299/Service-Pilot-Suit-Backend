from django.contrib import admin

from .models import (
    CommunityChannel,
    CommunityChannelMember,
    CommunityDmConversation,
    CommunityDmMessage,
    CommunityDmParticipant,
    CommunityMessage,
    CommunityPinnedMessage,
    CommunitySavedMessage,
    CommunityUserAvailability,
)


class CommunityChannelMemberInline(admin.TabularInline):
    model = CommunityChannelMember
    extra = 0
    readonly_fields = ("joined_at", "created_at", "updated_at")
    fields = ("user", "location", "role", "left_at", "last_read_at", "joined_at")


@admin.register(CommunityChannel)
class CommunityChannelAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "channel_type",
        "location",
        "is_archived",
        "featured",
        "sort_order",
        "updated_at",
    )
    list_filter = ("channel_type", "is_archived", "featured")
    search_fields = ("name", "slug", "description")
    readonly_fields = ("created_at", "updated_at")
    inlines = [CommunityChannelMemberInline]


@admin.register(CommunityChannelMember)
class CommunityChannelMemberAdmin(admin.ModelAdmin):
    list_display = ("channel", "user", "role", "location", "left_at", "joined_at")
    list_filter = ("role",)
    search_fields = ("channel__name", "user__email")
    readonly_fields = ("created_at", "updated_at", "joined_at")


@admin.register(CommunityMessage)
class CommunityMessageAdmin(admin.ModelAdmin):
    list_display = ("channel", "author", "status", "created_at")
    list_filter = ("status",)
    search_fields = ("body", "channel__name", "author__email")
    readonly_fields = ("created_at", "updated_at")


@admin.register(CommunityUserAvailability)
class CommunityUserAvailabilityAdmin(admin.ModelAdmin):
    list_display = ("user", "location", "status", "updated_at")
    list_filter = ("status",)
    search_fields = ("user__email",)


class CommunityDmParticipantInline(admin.TabularInline):
    model = CommunityDmParticipant
    extra = 0
    readonly_fields = ("created_at", "updated_at")


@admin.register(CommunityDmConversation)
class CommunityDmConversationAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "location",
        "participant_pair_key",
        "last_message_at",
        "updated_at",
    )
    search_fields = ("participant_pair_key",)
    readonly_fields = ("created_at", "updated_at")
    inlines = [CommunityDmParticipantInline]


@admin.register(CommunityDmMessage)
class CommunityDmMessageAdmin(admin.ModelAdmin):
    list_display = ("conversation", "author", "status", "created_at")
    list_filter = ("status",)
    search_fields = ("body", "author__email")
    readonly_fields = ("created_at", "updated_at")


@admin.register(CommunityPinnedMessage)
class CommunityPinnedMessageAdmin(admin.ModelAdmin):
    list_display = ("channel", "message", "pinned_by", "is_active", "created_at")
    list_filter = ("is_active",)
    readonly_fields = ("created_at", "updated_at")


@admin.register(CommunitySavedMessage)
class CommunitySavedMessageAdmin(admin.ModelAdmin):
    list_display = ("user", "message", "location", "created_at")
    search_fields = ("user__email",)
    readonly_fields = ("created_at", "updated_at")
