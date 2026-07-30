"""Feature Center — shared Service Pilot product roadmap.

Feature requests are global (one product roadmap). Source agency/location/user
are stored for attribution and staff triage only — customer APIs do not expose
private agency details.
"""
from __future__ import annotations

from django.conf import settings
from django.db import models

from apps.common.models import BaseModel


class FeatureRequest(BaseModel):
    class Status(models.TextChoices):
        SUBMITTED = "submitted", "Submitted"
        UNDER_REVIEW = "under_review", "Under review"
        PLANNED = "planned", "Planned"
        IN_PROGRESS = "in_progress", "In progress"
        TESTING = "testing", "Testing"
        RELEASED = "released", "Released"
        DECLINED = "declined", "Declined"

    class Category(models.TextChoices):
        ROI_CENTER = "roi_center", "ROI Center"
        SUCCESS_CENTER = "success_center", "Success Center"
        MEMBERS = "members", "Members"
        LOCATIONS = "locations", "Locations"
        AGENCY = "agency", "Agency Management"
        BILLING_ONBOARDING = "billing_onboarding", "Billing & Onboarding"
        INTEGRATIONS = "integrations", "Integrations"
        OTHER = "other", "General / Other"

    title = models.CharField(max_length=255)
    description = models.TextField()
    category = models.CharField(
        max_length=32,
        choices=Category.choices,
        default=Category.OTHER,
        db_index=True,
    )
    status = models.CharField(
        max_length=32,
        choices=Status.choices,
        default=Status.SUBMITTED,
        db_index=True,
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="feature_requests_created",
    )
    source_agency = models.ForeignKey(
        "tenancy.Agency",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="feature_requests_sourced",
        help_text="Attribution only — not exposed on customer APIs.",
    )
    source_location = models.ForeignKey(
        "tenancy.Location",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="feature_requests_sourced",
        help_text="Attribution only — not exposed on customer APIs.",
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="feature_requests_updated",
    )

    class Meta:
        ordering = ["-updated_at"]
        indexes = [
            models.Index(fields=["status", "-updated_at"]),
            models.Index(fields=["category", "-updated_at"]),
            models.Index(fields=["-created_at"]),
            models.Index(fields=["-updated_at"]),
        ]

    def __str__(self) -> str:
        return self.title

    @property
    def collaboration_locked(self) -> bool:
        return self.status == self.Status.RELEASED


class FeatureVote(BaseModel):
    """One active vote per user per feature request (hard-delete to remove)."""

    feature_request = models.ForeignKey(
        FeatureRequest,
        on_delete=models.CASCADE,
        related_name="votes",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="feature_votes",
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["feature_request", "user"],
                name="unique_feature_vote_per_user",
            )
        ]
        indexes = [
            models.Index(fields=["feature_request", "created_at"]),
        ]

    def __str__(self) -> str:
        return f"Vote by {self.user_id} on {self.feature_request_id}"


class FeatureComment(BaseModel):
    """Discussion on a feature request.

    Public comments (``is_internal=False``) are visible to all Feature Center
    users. Internal comments (``is_internal=True``) are staff-only and must
    never be returned on customer APIs.
    """

    feature_request = models.ForeignKey(
        FeatureRequest,
        on_delete=models.CASCADE,
        related_name="comments",
    )
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="feature_comments",
    )
    body = models.TextField()
    is_internal = models.BooleanField(
        default=False,
        db_index=True,
        help_text="True = staff-only note; False = public discussion.",
    )

    class Meta:
        ordering = ["created_at"]
        indexes = [
            models.Index(fields=["feature_request", "created_at"]),
            models.Index(fields=["feature_request", "is_internal", "created_at"]),
        ]

    def __str__(self) -> str:
        kind = "internal" if self.is_internal else "public"
        return f"{kind} comment on {self.feature_request_id}"


class FeatureStatusEvent(BaseModel):
    feature_request = models.ForeignKey(
        FeatureRequest,
        on_delete=models.CASCADE,
        related_name="status_events",
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="feature_status_events",
    )
    previous_status = models.CharField(max_length=32, blank=True, default="")
    new_status = models.CharField(max_length=32)

    class Meta:
        ordering = ["created_at"]
        indexes = [
            models.Index(fields=["feature_request", "created_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.previous_status or '—'} → {self.new_status}"


class FeatureReleaseNote(BaseModel):
    class NoteStatus(models.TextChoices):
        DRAFT = "draft", "Draft"
        PUBLISHED = "published", "Published"
        ARCHIVED = "archived", "Archived"

    feature_request = models.ForeignKey(
        FeatureRequest,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="release_notes",
    )
    title = models.CharField(max_length=255)
    body = models.TextField()
    status = models.CharField(
        max_length=16,
        choices=NoteStatus.choices,
        default=NoteStatus.DRAFT,
        db_index=True,
    )
    published_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="feature_release_notes_published",
    )
    published_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-published_at", "-created_at"]
        indexes = [
            models.Index(fields=["status", "-published_at"]),
            models.Index(fields=["feature_request", "status"]),
        ]

    def __str__(self) -> str:
        return self.title
