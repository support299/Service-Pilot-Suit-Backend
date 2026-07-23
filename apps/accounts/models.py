"""Custom, email-first User model with GoHighLevel metadata.

RBAC roles are *not* stored on the user; they live on ``tenancy.Membership`` so
a single user can hold different roles across many locations. The GHL metadata
here mirrors the reference platform and drives agency-wide access resolution.
"""
from __future__ import annotations

import uuid

from django.contrib.auth.models import AbstractUser
from django.db import models

from .managers import UserManager


class User(AbstractUser):
    # Replace the integer PK with a non-guessable UUID.
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # Email is the login identifier; username is dropped.
    username = None  # type: ignore[assignment]
    email = models.EmailField("email address", unique=True)

    # ── GoHighLevel identity metadata ────────────────────────────
    ghl_user_id = models.CharField(max_length=255, null=True, blank=True, db_index=True)
    ghl_user_type = models.CharField(
        max_length=20,
        blank=True,
        default="",
        help_text="GHL user type: 'agency' or 'account'.",
    )
    ghl_company_id = models.CharField(
        max_length=255,
        blank=True,
        default="",
        db_index=True,
        help_text="GHL company id (limits cross-company access for agency users).",
    )
    ghl_location_ids = models.JSONField(
        default=list,
        blank=True,
        help_text="GHL roles.locationIds when restrictSubAccount is enabled.",
    )
    ghl_restrict_sub_account = models.BooleanField(
        default=False,
        help_text="When True, agency access is limited to ghl_location_ids.",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS: list[str] = []

    objects = UserManager()

    class Meta:
        ordering = ["email"]

    def __str__(self) -> str:
        return self.email

    @property
    def full_name(self) -> str:
        name = f"{self.first_name} {self.last_name}".strip()
        return name or self.email

    @property
    def is_agency_user(self) -> bool:
        return (self.ghl_user_type or "").lower() == "agency"
