from django.contrib import admin

from .models import (
    GhlOpportunity,
    GoogleAdDailyStat,
    GoogleCampaign,
    GooglePeriodSnapshot,
    GoogleSyncState,
    MetaAdDailyStat,
    MetaCampaign,
    MetaPeriodSnapshot,
    MetaSyncState,
    RoiCrmSetup,
)


@admin.register(MetaAdDailyStat)
class MetaAdDailyStatAdmin(admin.ModelAdmin):
    list_display = (
        "date",
        "location",
        "spend",
        "impressions",
        "clicks",
        "leads",
        "conversions",
        "synced_at",
    )
    list_filter = ("date",)
    search_fields = ("location__name", "location__ghl_location_id", "ad_account_id")
    readonly_fields = ("created_at", "updated_at", "synced_at", "raw")


@admin.register(MetaCampaign)
class MetaCampaignAdmin(admin.ModelAdmin):
    list_display = ("name", "status", "campaign_id", "location", "synced_at")
    list_filter = ("status",)
    search_fields = ("name", "campaign_id", "location__ghl_location_id")


@admin.register(MetaSyncState)
class MetaSyncStateAdmin(admin.ModelAdmin):
    list_display = (
        "location",
        "status",
        "last_synced_at",
        "daily_from",
        "daily_to",
        "days_upserted",
        "campaigns_upserted",
    )
    readonly_fields = ("created_at", "updated_at")


@admin.register(MetaPeriodSnapshot)
class MetaPeriodSnapshotAdmin(admin.ModelAdmin):
    list_display = (
        "period_start",
        "period_end",
        "location",
        "spend",
        "impressions",
        "clicks",
        "leads",
        "synced_at",
    )
    list_filter = ("period_start", "period_end")
    search_fields = ("location__name", "location__ghl_location_id")
    readonly_fields = ("created_at", "updated_at", "synced_at", "raw_totals")


@admin.register(GoogleAdDailyStat)
class GoogleAdDailyStatAdmin(admin.ModelAdmin):
    list_display = (
        "date",
        "location",
        "spend",
        "impressions",
        "clicks",
        "conversions",
        "synced_at",
    )
    list_filter = ("date",)
    search_fields = ("location__name", "location__ghl_location_id", "customer_id")
    readonly_fields = ("created_at", "updated_at", "synced_at", "raw")


@admin.register(GoogleCampaign)
class GoogleCampaignAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "status",
        "campaign_id",
        "spend",
        "conversions",
        "location",
        "synced_at",
    )
    list_filter = ("status",)
    search_fields = ("name", "campaign_id", "location__ghl_location_id")


@admin.register(GoogleSyncState)
class GoogleSyncStateAdmin(admin.ModelAdmin):
    list_display = (
        "location",
        "status",
        "last_synced_at",
        "daily_from",
        "daily_to",
        "days_upserted",
        "campaigns_upserted",
    )
    readonly_fields = ("created_at", "updated_at")


@admin.register(GooglePeriodSnapshot)
class GooglePeriodSnapshotAdmin(admin.ModelAdmin):
    list_display = (
        "period_start",
        "period_end",
        "location",
        "spend",
        "impressions",
        "clicks",
        "conversions",
        "synced_at",
    )
    list_filter = ("period_start", "period_end")
    search_fields = ("location__name", "location__ghl_location_id")
    readonly_fields = ("created_at", "updated_at", "synced_at", "raw_totals")


@admin.register(RoiCrmSetup)
class RoiCrmSetupAdmin(admin.ModelAdmin):
    list_display = (
        "location",
        "pipeline_name",
        "pipeline_id",
        "setup_status",
        "sync_status",
        "opportunities_synced",
        "last_synced_at",
    )
    list_filter = ("setup_status", "sync_status")
    search_fields = ("location__name", "location__ghl_location_id", "pipeline_name")
    readonly_fields = ("created_at", "updated_at", "confirmed_at", "last_synced_at")


@admin.register(GhlOpportunity)
class GhlOpportunityAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "status",
        "source_channel",
        "monetary_value",
        "source_raw",
        "location",
        "synced_at",
    )
    list_filter = ("status", "source_channel")
    search_fields = (
        "name",
        "ghl_opportunity_id",
        "source_raw",
        "location__ghl_location_id",
    )
    readonly_fields = ("created_at", "updated_at", "synced_at", "raw")
