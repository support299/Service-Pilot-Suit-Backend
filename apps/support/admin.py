from django.contrib import admin

from .models import SupportAttachment, SupportMessage, SupportTicket


class SupportAttachmentInline(admin.TabularInline):
    model = SupportAttachment
    extra = 0
    readonly_fields = ("created_at", "updated_at", "url", "ghl_file_id")


class SupportMessageInline(admin.TabularInline):
    model = SupportMessage
    extra = 0
    readonly_fields = ("created_at", "updated_at")


@admin.register(SupportTicket)
class SupportTicketAdmin(admin.ModelAdmin):
    list_display = (
        "display_id",
        "subject",
        "status",
        "category",
        "priority",
        "location",
        "updated_at",
    )
    list_filter = ("status", "category", "priority")
    search_fields = ("subject", "description", "location__ghl_location_id", "location__name")
    readonly_fields = ("created_at", "updated_at", "number")
    inlines = [SupportMessageInline]

    @admin.display(description="ID")
    def display_id(self, obj: SupportTicket) -> str:
        return obj.display_id


@admin.register(SupportMessage)
class SupportMessageAdmin(admin.ModelAdmin):
    list_display = ("ticket", "author", "is_staff_reply", "created_at")
    list_filter = ("is_staff_reply",)
    search_fields = ("body", "ticket__subject")
    readonly_fields = ("created_at", "updated_at")
    inlines = [SupportAttachmentInline]


@admin.register(SupportAttachment)
class SupportAttachmentAdmin(admin.ModelAdmin):
    list_display = ("filename", "content_type", "message", "created_at")
    search_fields = ("filename", "ghl_file_id", "url")
    readonly_fields = ("created_at", "updated_at")
