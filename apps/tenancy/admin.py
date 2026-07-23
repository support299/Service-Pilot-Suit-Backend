from django.contrib import admin

from .models import Agency, Location, LocationMediaFolder, Membership


@admin.register(Agency)
class AgencyAdmin(admin.ModelAdmin):
    list_display = ("name", "ghl_company_id", "is_active", "created_at")
    search_fields = ("name", "ghl_company_id")
    list_filter = ("is_active",)


@admin.register(Location)
class LocationAdmin(admin.ModelAdmin):
    list_display = ("name", "ghl_location_id", "agency", "status", "is_active")
    search_fields = ("name", "ghl_location_id")
    list_filter = ("status", "is_active")
    autocomplete_fields = ("agency",)


@admin.register(Membership)
class MembershipAdmin(admin.ModelAdmin):
    list_display = ("user", "location", "role", "is_active", "created_at")
    search_fields = ("user__email", "location__name", "location__ghl_location_id")
    list_filter = ("is_active", "role")
    autocomplete_fields = ("user", "location", "role")


@admin.register(LocationMediaFolder)
class LocationMediaFolderAdmin(admin.ModelAdmin):
    list_display = ("name", "ghl_folder_id", "location", "is_active", "updated_at")
    search_fields = ("name", "ghl_folder_id", "location__ghl_location_id", "location__name")
    list_filter = ("name", "is_active")
    autocomplete_fields = ("location",)
