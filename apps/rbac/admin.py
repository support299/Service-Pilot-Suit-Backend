from django.contrib import admin

from .models import Permission, Role


@admin.register(Permission)
class PermissionAdmin(admin.ModelAdmin):
    list_display = ("codename", "name")
    search_fields = ("codename", "name")


@admin.register(Role)
class RoleAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "is_system", "is_superuser_role")
    list_filter = ("is_system", "is_superuser_role")
    search_fields = ("name", "slug")
    filter_horizontal = ("permissions",)
