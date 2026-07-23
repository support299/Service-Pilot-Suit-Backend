"""Shared abstract models used across every app."""
from __future__ import annotations

import uuid

from django.db import models


class TimeStampedModel(models.Model):
    """Adds self-managing ``created_at`` / ``updated_at`` timestamps."""

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class BaseModel(TimeStampedModel):
    """Canonical base model: UUID primary key + timestamps.

    Using a UUID primary key keeps identifiers non-guessable across tenants and
    safe to expose in URLs.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    class Meta:
        abstract = True
        ordering = ["-created_at"]
