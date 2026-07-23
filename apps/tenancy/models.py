"""Multi-tenant core: Agency → Location → Membership.

- **Agency**   = a GoHighLevel *company* (agency-level install).
- **Location** = a GoHighLevel *sub-account*; the unit of tenant isolation.
- **Membership** = user ↔ location ↔ role, so one user can access many
  locations, each with a different role.

Never query tenant-scoped data without filtering by the resolved Location.
"""
from __future__ import annotations

from django.conf import settings
from django.db import models
from django.utils import timezone

from apps.common.models import BaseModel


class Agency(BaseModel):
    """A GoHighLevel company (agency)."""

    ghl_company_id = models.CharField(max_length=255, unique=True, db_index=True)
    name = models.CharField(max_length=255, blank=True, default="")
    is_active = models.BooleanField(default=True)

    # Agency-level OAuth credentials (used to mint sub-account location tokens).
    access_token = models.TextField(blank=True, default="")
    refresh_token = models.TextField(blank=True, default="")
    token_expires_at = models.DateTimeField(null=True, blank=True)
    scope = models.TextField(blank=True, default="")

    class Meta:
        verbose_name_plural = "agencies"
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name or self.ghl_company_id


class Location(BaseModel):
    """A GoHighLevel sub-account — the tenant boundary."""

    STATUS_ACTIVE = "active"
    STATUS_SUSPENDED = "suspended"
    STATUS_TRIAL = "trial"
    STATUS_CHURNED = "churned"
    STATUS_CHOICES = [
        (STATUS_ACTIVE, "Active"),
        (STATUS_SUSPENDED, "Suspended"),
        (STATUS_TRIAL, "Trial"),
        (STATUS_CHURNED, "Churned"),
    ]

    ghl_location_id = models.CharField(max_length=255, unique=True, db_index=True)
    agency = models.ForeignKey(
        Agency,
        on_delete=models.CASCADE,
        related_name="locations",
        null=True,
        blank=True,
    )
    name = models.CharField(max_length=255, blank=True, default="")
    timezone = models.CharField(max_length=100, blank=True, default="UTC")
    is_active = models.BooleanField(default=True)
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default=STATUS_ACTIVE
    )

    # Per-location OAuth credentials.
    ghl_user_id = models.CharField(max_length=255, blank=True, default="")
    access_token = models.TextField(blank=True, default="")
    refresh_token = models.TextField(blank=True, default="")
    token_expires_at = models.DateTimeField(null=True, blank=True)
    scope = models.TextField(blank=True, default="")

    onboarded_at = models.DateTimeField(null=True, blank=True)
    last_sync_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name or self.ghl_location_id

    def mark_onboarded(self) -> None:
        if self.onboarded_at is None:
            self.onboarded_at = timezone.now()


class Membership(BaseModel):
    """Assigns a role to a user within a single location."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="memberships",
    )
    location = models.ForeignKey(
        Location,
        on_delete=models.CASCADE,
        related_name="memberships",
    )
    role = models.ForeignKey(
        "rbac.Role",
        on_delete=models.PROTECT,
        related_name="memberships",
    )
    is_active = models.BooleanField(default=True)
    # Per-membership overrides on top of the role bundle (agency portal toggles).
    permission_grants = models.JSONField(
        default=list,
        blank=True,
        help_text="Permission codenames granted beyond the role.",
    )
    permission_denies = models.JSONField(
        default=list,
        blank=True,
        help_text="Permission codenames revoked from the role.",
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["user", "location"], name="unique_user_location_membership"
            )
        ]
        indexes = [
            models.Index(fields=["location", "is_active"]),
            models.Index(fields=["user", "is_active"]),
        ]
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.user} @ {self.location} ({self.role})"


class LocationMediaFolder(BaseModel):
    """Maps a named GHL media-library folder for a location.

    Files are stored in GoHighLevel (``parentId`` = ``ghl_folder_id``). We only
    persist the folder id so uploads land in the right place after onboard.
    """

    FOLDER_SUPPORT_MEDIA = "Support Media"

    location = models.ForeignKey(
        Location,
        on_delete=models.CASCADE,
        related_name="media_folders",
    )
    name = models.CharField(max_length=128)
    ghl_folder_id = models.CharField(
        max_length=128,
        help_text="GHL media folder id — used as upload parentId.",
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["location", "name"],
                name="unique_location_media_folder_name",
            )
        ]
        indexes = [
            models.Index(fields=["location", "name"]),
        ]
        ordering = ["name"]

    def __str__(self) -> str:
        return f"{self.location_id} / {self.name}"
