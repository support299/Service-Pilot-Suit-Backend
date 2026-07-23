"""Support tickets for the Success Center.

Location-scoped help desk: tickets + threaded messages. Status workflow mirrors
the reference Support module (open → waiting → resolved).
"""
from __future__ import annotations

from django.conf import settings
from django.db import models

from apps.common.models import BaseModel


class SupportTicket(BaseModel):
    class Status(models.TextChoices):
        OPEN = "open", "Open"
        WAITING_ON_CUSTOMER = "waiting_on_customer", "Waiting on you"
        WAITING_ON_SUPPORT = "waiting_on_support", "Waiting on Service Pilot"
        RESOLVED = "resolved", "Resolved"
        CLOSED = "closed", "Closed"

    class Category(models.TextChoices):
        GENERAL = "general", "General"
        ACCOUNT = "account", "Account"
        BUG = "bug", "Bug"
        SETUP = "setup", "Setup"
        BILLING = "billing", "Billing"

    class Priority(models.TextChoices):
        LOW = "low", "Low"
        NORMAL = "normal", "Normal"
        HIGH = "high", "High"

    location = models.ForeignKey(
        "tenancy.Location",
        on_delete=models.CASCADE,
        related_name="support_tickets",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="support_tickets_created",
    )
    number = models.PositiveIntegerField(
        help_text="Per-location sequential ticket number (shown as SP-####).",
    )
    subject = models.CharField(max_length=255)
    description = models.TextField(blank=True, default="")
    status = models.CharField(
        max_length=32,
        choices=Status.choices,
        default=Status.OPEN,
        db_index=True,
    )
    category = models.CharField(
        max_length=32,
        choices=Category.choices,
        default=Category.GENERAL,
    )
    priority = models.CharField(
        max_length=16,
        choices=Priority.choices,
        default=Priority.NORMAL,
    )
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["location", "number"],
                name="unique_support_ticket_number_per_location",
            )
        ]
        indexes = [
            models.Index(fields=["location", "status", "-updated_at"]),
            models.Index(fields=["location", "-created_at"]),
        ]
        ordering = ["-updated_at"]

    def __str__(self) -> str:
        return f"SP-{self.number:04d} {self.subject}"

    @property
    def display_id(self) -> str:
        return f"SP-{self.number:04d}"


class SupportMessage(BaseModel):
    """A reply on a support ticket (customer or staff)."""

    ticket = models.ForeignKey(
        SupportTicket,
        on_delete=models.CASCADE,
        related_name="messages",
    )
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="support_messages",
    )
    body = models.TextField(blank=True, default="")
    is_staff_reply = models.BooleanField(
        default=False,
        help_text="True when authored by someone with support.manage in this context.",
    )

    class Meta:
        ordering = ["created_at"]
        indexes = [
            models.Index(fields=["ticket", "created_at"]),
        ]

    def __str__(self) -> str:
        return f"Message on {self.ticket_id}"


class SupportAttachment(BaseModel):
    """Media attached to a support message — bytes live in GHL, we store refs."""

    message = models.ForeignKey(
        SupportMessage,
        on_delete=models.CASCADE,
        related_name="attachments",
    )
    ghl_file_id = models.CharField(max_length=128, blank=True, default="")
    url = models.URLField(max_length=1024)
    filename = models.CharField(max_length=255, blank=True, default="")
    content_type = models.CharField(max_length=128, blank=True, default="")
    size_bytes = models.PositiveIntegerField(null=True, blank=True)

    class Meta:
        ordering = ["created_at"]

    def __str__(self) -> str:
        return self.filename or self.ghl_file_id or self.url

    @property
    def kind(self) -> str:
        ct = (self.content_type or "").lower()
        name = (self.filename or "").lower()
        if ct.startswith("video/") or name.endswith((".mp4", ".mov", ".webm", ".m4v")):
            return "video"
        if ct.startswith("image/") or name.endswith(
            (".png", ".jpg", ".jpeg", ".gif", ".webp")
        ):
            return "image"
        return "file"
