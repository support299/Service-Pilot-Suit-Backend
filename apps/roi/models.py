"""Cached Meta (Facebook) + Google Ads insights for the ROI Center.

Meta: GHL ``groupBy=day`` → one row per location+date; campaigns are catalog-only.
Google: GHL ``groupBy=date`` with ``costMicros``; campaigns include range metrics.
"""
from __future__ import annotations

from django.db import models

from apps.common.models import BaseModel


class MetaAdDailyStat(BaseModel):
    """Account-level Facebook metrics for a single calendar day."""

    location = models.ForeignKey(
        "tenancy.Location",
        on_delete=models.CASCADE,
        related_name="meta_ad_daily_stats",
    )
    date = models.DateField(db_index=True)
    ad_account_id = models.CharField(max_length=64, blank=True, default="")

    impressions = models.PositiveIntegerField(default=0)
    clicks = models.PositiveIntegerField(default=0)
    spend = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    conversions = models.PositiveIntegerField(default=0)
    leads = models.PositiveIntegerField(default=0)

    # Day-level rates from GHL (do not sum across days — recompute from totals).
    cpc = models.DecimalField(max_digits=14, decimal_places=6, null=True, blank=True)
    cpm = models.DecimalField(max_digits=14, decimal_places=6, null=True, blank=True)
    ctr = models.DecimalField(max_digits=14, decimal_places=6, null=True, blank=True)
    reach = models.PositiveIntegerField(null=True, blank=True)
    frequency = models.DecimalField(
        max_digits=14, decimal_places=6, null=True, blank=True
    )
    cost_per_conversion = models.DecimalField(
        max_digits=14, decimal_places=6, null=True, blank=True
    )

    results = models.JSONField(default=dict, blank=True)
    cost_per_result_breakdown = models.JSONField(default=dict, blank=True)
    raw = models.JSONField(default=dict, blank=True)
    synced_at = models.DateTimeField()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["location", "date"],
                name="unique_meta_daily_stat_per_location_date",
            )
        ]
        indexes = [
            models.Index(fields=["location", "date"]),
        ]
        ordering = ["-date"]

    def __str__(self) -> str:
        return f"{self.location_id} {self.date}"


class MetaCampaign(BaseModel):
    """Facebook campaign catalog for a location (from GHL reporting/list)."""

    location = models.ForeignKey(
        "tenancy.Location",
        on_delete=models.CASCADE,
        related_name="meta_campaigns",
    )
    campaign_id = models.CharField(max_length=64, db_index=True)
    ad_account_id = models.CharField(max_length=64, blank=True, default="")
    name = models.CharField(max_length=512, blank=True, default="")
    status = models.CharField(max_length=64, blank=True, default="")
    synced_at = models.DateTimeField()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["location", "campaign_id"],
                name="unique_meta_campaign_per_location",
            )
        ]
        indexes = [
            models.Index(fields=["location", "status"]),
        ]
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name or self.campaign_id


class MetaSyncState(BaseModel):
    """Last sync metadata per location (for UI + debugging)."""

    location = models.OneToOneField(
        "tenancy.Location",
        on_delete=models.CASCADE,
        related_name="meta_sync_state",
    )
    last_synced_at = models.DateTimeField(null=True, blank=True)
    daily_from = models.DateField(null=True, blank=True)
    daily_to = models.DateField(null=True, blank=True)
    days_upserted = models.PositiveIntegerField(default=0)
    campaigns_upserted = models.PositiveIntegerField(default=0)
    last_error = models.TextField(blank=True, default="")
    status = models.CharField(
        max_length=32,
        default="idle",
        help_text="idle | syncing | success | error",
    )

    def __str__(self) -> str:
        return f"MetaSyncState({self.location_id})"


class MetaPeriodSnapshot(BaseModel):
    """Exact date-range totals from GHL ``totals`` (matches GHL report cards)."""

    location = models.ForeignKey(
        "tenancy.Location",
        on_delete=models.CASCADE,
        related_name="meta_period_snapshots",
    )
    period_start = models.DateField()
    period_end = models.DateField()

    impressions = models.PositiveIntegerField(default=0)
    clicks = models.PositiveIntegerField(default=0)
    spend = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    conversions = models.PositiveIntegerField(default=0)
    leads = models.PositiveIntegerField(default=0)
    cpc = models.DecimalField(max_digits=14, decimal_places=6, null=True, blank=True)
    cpm = models.DecimalField(max_digits=14, decimal_places=6, null=True, blank=True)
    ctr = models.DecimalField(max_digits=14, decimal_places=6, null=True, blank=True)
    cost_per_conversion = models.DecimalField(
        max_digits=14, decimal_places=6, null=True, blank=True
    )
    raw_totals = models.JSONField(default=dict, blank=True)
    synced_at = models.DateTimeField()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["location", "period_start", "period_end"],
                name="unique_meta_period_snapshot",
            )
        ]
        indexes = [
            models.Index(fields=["location", "period_start", "period_end"]),
        ]

    def __str__(self) -> str:
        return f"{self.location_id} {self.period_start}→{self.period_end}"


class GoogleAdDailyStat(BaseModel):
    """Account-level Google Ads metrics for a single calendar day."""

    location = models.ForeignKey(
        "tenancy.Location",
        on_delete=models.CASCADE,
        related_name="google_ad_daily_stats",
    )
    date = models.DateField(db_index=True)
    customer_id = models.CharField(max_length=64, blank=True, default="")

    impressions = models.PositiveIntegerField(default=0)
    clicks = models.PositiveIntegerField(default=0)
    # Stored in dollars (GHL returns costMicros / 1e6).
    spend = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    conversions = models.DecimalField(max_digits=14, decimal_places=2, default=0)

    cpc = models.DecimalField(max_digits=14, decimal_places=6, null=True, blank=True)
    cpm = models.DecimalField(max_digits=14, decimal_places=6, null=True, blank=True)
    # Percentage (0–100), recomputed from clicks/impressions when possible.
    ctr = models.DecimalField(max_digits=14, decimal_places=6, null=True, blank=True)
    cost_per_conversion = models.DecimalField(
        max_digits=14, decimal_places=6, null=True, blank=True
    )

    raw = models.JSONField(default=dict, blank=True)
    synced_at = models.DateTimeField()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["location", "date"],
                name="unique_google_daily_stat_per_location_date",
            )
        ]
        indexes = [
            models.Index(fields=["location", "date"]),
        ]
        ordering = ["-date"]

    def __str__(self) -> str:
        return f"{self.location_id} {self.date}"


class GoogleCampaign(BaseModel):
    """Google campaign row with metrics from the last synced date range."""

    location = models.ForeignKey(
        "tenancy.Location",
        on_delete=models.CASCADE,
        related_name="google_campaigns",
    )
    campaign_id = models.CharField(max_length=64, db_index=True)
    customer_id = models.CharField(max_length=64, blank=True, default="")
    name = models.CharField(max_length=512, blank=True, default="")
    status = models.CharField(max_length=64, blank=True, default="")

    impressions = models.PositiveIntegerField(default=0)
    clicks = models.PositiveIntegerField(default=0)
    spend = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    conversions = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    cpc = models.DecimalField(max_digits=14, decimal_places=6, null=True, blank=True)
    cpm = models.DecimalField(max_digits=14, decimal_places=6, null=True, blank=True)
    ctr = models.DecimalField(max_digits=14, decimal_places=6, null=True, blank=True)
    cost_per_conversion = models.DecimalField(
        max_digits=14, decimal_places=6, null=True, blank=True
    )
    metrics_start = models.DateField(null=True, blank=True)
    metrics_end = models.DateField(null=True, blank=True)
    raw = models.JSONField(default=dict, blank=True)
    synced_at = models.DateTimeField()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["location", "campaign_id"],
                name="unique_google_campaign_per_location",
            )
        ]
        indexes = [
            models.Index(fields=["location", "status"]),
        ]
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name or self.campaign_id


class GoogleSyncState(BaseModel):
    """Last Google Ads sync metadata per location."""

    location = models.OneToOneField(
        "tenancy.Location",
        on_delete=models.CASCADE,
        related_name="google_sync_state",
    )
    last_synced_at = models.DateTimeField(null=True, blank=True)
    daily_from = models.DateField(null=True, blank=True)
    daily_to = models.DateField(null=True, blank=True)
    days_upserted = models.PositiveIntegerField(default=0)
    campaigns_upserted = models.PositiveIntegerField(default=0)
    last_error = models.TextField(blank=True, default="")
    status = models.CharField(
        max_length=32,
        default="idle",
        help_text="idle | syncing | success | error",
    )

    def __str__(self) -> str:
        return f"GoogleSyncState({self.location_id})"


class GooglePeriodSnapshot(BaseModel):
    """Exact date-range totals from GHL Google ``totals``."""

    location = models.ForeignKey(
        "tenancy.Location",
        on_delete=models.CASCADE,
        related_name="google_period_snapshots",
    )
    period_start = models.DateField()
    period_end = models.DateField()

    impressions = models.PositiveIntegerField(default=0)
    clicks = models.PositiveIntegerField(default=0)
    spend = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    conversions = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    cpc = models.DecimalField(max_digits=14, decimal_places=6, null=True, blank=True)
    cpm = models.DecimalField(max_digits=14, decimal_places=6, null=True, blank=True)
    ctr = models.DecimalField(max_digits=14, decimal_places=6, null=True, blank=True)
    cost_per_conversion = models.DecimalField(
        max_digits=14, decimal_places=6, null=True, blank=True
    )
    raw_totals = models.JSONField(default=dict, blank=True)
    synced_at = models.DateTimeField()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["location", "period_start", "period_end"],
                name="unique_google_period_snapshot",
            )
        ]
        indexes = [
            models.Index(fields=["location", "period_start", "period_end"]),
        ]

    def __str__(self) -> str:
        return f"{self.location_id} {self.period_start}→{self.period_end}"


class RoiCrmSetup(BaseModel):
    """Per-location GHL pipeline selection for opportunity-based ROAS."""

    class SetupStatus(models.TextChoices):
        NEEDS_PIPELINE = "needs_pipeline", "Needs pipeline"
        CONFIRMED = "confirmed", "Confirmed"

    location = models.OneToOneField(
        "tenancy.Location",
        on_delete=models.CASCADE,
        related_name="roi_crm_setup",
    )
    pipeline_id = models.CharField(max_length=64, blank=True, default="")
    pipeline_name = models.CharField(max_length=255, blank=True, default="")
    setup_status = models.CharField(
        max_length=32,
        choices=SetupStatus.choices,
        default=SetupStatus.NEEDS_PIPELINE,
        db_index=True,
    )
    confirmed_at = models.DateTimeField(null=True, blank=True)
    last_synced_at = models.DateTimeField(null=True, blank=True)
    opportunities_synced = models.PositiveIntegerField(default=0)
    last_sync_error = models.TextField(blank=True, default="")
    sync_status = models.CharField(
        max_length=32,
        default="idle",
        help_text="idle | syncing | success | error",
    )

    def __str__(self) -> str:
        return f"RoiCrmSetup({self.location_id} {self.pipeline_name or self.pipeline_id})"


class GhlOpportunity(BaseModel):
    """Cached GHL opportunity used for CRM returns / ROAS."""

    class Status(models.TextChoices):
        OPEN = "open", "Open"
        WON = "won", "Won"
        LOST = "lost", "Lost"
        ABANDONED = "abandoned", "Abandoned"
        OTHER = "other", "Other"

    class SourceChannel(models.TextChoices):
        FACEBOOK = "facebook", "Facebook"
        GOOGLE = "google", "Google"
        OTHER = "other", "Other"

    location = models.ForeignKey(
        "tenancy.Location",
        on_delete=models.CASCADE,
        related_name="ghl_opportunities",
    )
    ghl_opportunity_id = models.CharField(max_length=64, db_index=True)
    pipeline_id = models.CharField(max_length=64, blank=True, default="", db_index=True)
    pipeline_stage_id = models.CharField(max_length=64, blank=True, default="")
    pipeline_stage_name = models.CharField(max_length=255, blank=True, default="")
    name = models.CharField(max_length=512, blank=True, default="")
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.OTHER,
        db_index=True,
    )
    status_raw = models.CharField(max_length=64, blank=True, default="")
    monetary_value = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    source_raw = models.CharField(max_length=255, blank=True, default="")
    source_channel = models.CharField(
        max_length=16,
        choices=SourceChannel.choices,
        default=SourceChannel.OTHER,
        db_index=True,
    )
    contact_id = models.CharField(max_length=64, blank=True, default="")
    ghl_created_at = models.DateTimeField(null=True, blank=True, db_index=True)
    ghl_updated_at = models.DateTimeField(null=True, blank=True)
    last_status_change_at = models.DateTimeField(null=True, blank=True, db_index=True)
    raw = models.JSONField(default=dict, blank=True)
    synced_at = models.DateTimeField()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["location", "ghl_opportunity_id"],
                name="unique_ghl_opportunity_per_location",
            )
        ]
        indexes = [
            models.Index(fields=["location", "status", "source_channel"]),
            models.Index(fields=["location", "pipeline_id", "status"]),
            models.Index(fields=["location", "last_status_change_at"]),
            models.Index(fields=["location", "ghl_created_at"]),
        ]
        ordering = ["-ghl_created_at", "-created_at"]

    def __str__(self) -> str:
        return self.name or self.ghl_opportunity_id
