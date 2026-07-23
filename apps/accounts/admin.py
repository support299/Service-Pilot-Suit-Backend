from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .models import User


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    ordering = ("email",)
    list_display = ("email", "first_name", "last_name", "is_staff", "is_superuser", "ghl_user_type")
    list_filter = ("is_staff", "is_superuser", "is_active", "ghl_user_type")
    search_fields = ("email", "first_name", "last_name", "ghl_user_id", "ghl_company_id")
    readonly_fields = ("created_at", "updated_at", "last_login", "date_joined")

    fieldsets = (
        (None, {"fields": ("email", "password")}),
        ("Personal info", {"fields": ("first_name", "last_name")}),
        (
            "GoHighLevel",
            {
                "fields": (
                    "ghl_user_id",
                    "ghl_user_type",
                    "ghl_company_id",
                    "ghl_location_ids",
                    "ghl_restrict_sub_account",
                )
            },
        ),
        ("Permissions", {"fields": ("is_active", "is_staff", "is_superuser", "groups", "user_permissions")}),
        ("Dates", {"fields": ("last_login", "date_joined", "created_at", "updated_at")}),
    )
    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": ("email", "password1", "password2", "is_staff", "is_superuser"),
            },
        ),
    )
