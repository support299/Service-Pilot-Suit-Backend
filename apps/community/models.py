"""Community Chat — channels, membership, and messages.

Company channels are location-scoped. Service Pilot and Industry channels are
platform-wide (``location`` is null). Messages are persisted for Phase 1 chat;
hub/channels ship first, live composer UI follows.
"""
from __future__ import annotations

from django.conf import settings
from django.db import models

from apps.common.models import BaseModel


class CommunityChannel(BaseModel):
    class ChannelType(models.TextChoices):
        COMPANY = "company", "Company Channel"
        SERVICE_PILOT = "service_pilot", "Service Pilot Channel"
        INDUSTRY = "industry", "Industry Group"

    location = models.ForeignKey(
        "tenancy.Location",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="community_channels",
        help_text="Set for company channels; null for platform (SP / industry).",
    )
    name = models.CharField(max_length=120)
    slug = models.SlugField(max_length=140)
    description = models.TextField(blank=True, default="")
    channel_type = models.CharField(
        max_length=32,
        choices=ChannelType.choices,
        db_index=True,
    )
    is_archived = models.BooleanField(default=False, db_index=True)
    featured = models.BooleanField(default=False)
    sort_order = models.PositiveIntegerField(default=0)
    thumbnail_url = models.URLField(blank=True, default="")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="community_channels_created",
    )

    class Meta:
        ordering = ["sort_order", "name"]
        indexes = [
            models.Index(fields=["channel_type", "is_archived"]),
            models.Index(fields=["location", "channel_type"]),
            models.Index(fields=["-updated_at"]),
        ]
        constraints = [
            # One slug per company location.
            models.UniqueConstraint(
                fields=["location", "slug"],
                condition=models.Q(location__isnull=False),
                name="unique_community_channel_slug_per_location",
            ),
            # One slug among platform channels (location is null).
            models.UniqueConstraint(
                fields=["slug"],
                condition=models.Q(location__isnull=True),
                name="unique_community_platform_channel_slug",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.name} ({self.channel_type})"

    @property
    def is_platform(self) -> bool:
        return self.channel_type in (
            self.ChannelType.SERVICE_PILOT,
            self.ChannelType.INDUSTRY,
        )


class CommunityChannelMember(BaseModel):
    class Role(models.TextChoices):
        OWNER = "owner", "Owner"
        MODERATOR = "moderator", "Moderator"
        MEMBER = "member", "Member"

    channel = models.ForeignKey(
        CommunityChannel,
        on_delete=models.CASCADE,
        related_name="members",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="community_channel_memberships",
    )
    # Home location of the member — used later for same-company DM rules.
    location = models.ForeignKey(
        "tenancy.Location",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="community_channel_memberships",
    )
    role = models.CharField(
        max_length=16,
        choices=Role.choices,
        default=Role.MEMBER,
    )
    joined_at = models.DateTimeField(auto_now_add=True)
    left_at = models.DateTimeField(null=True, blank=True)
    last_read_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["channel", "user"]),
            models.Index(fields=["user", "left_at"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["channel", "user"],
                condition=models.Q(left_at__isnull=True),
                name="unique_active_community_channel_member",
            )
        ]

    def __str__(self) -> str:
        return f"{self.user_id} in {self.channel_id} ({self.role})"

    @property
    def is_active(self) -> bool:
        return self.left_at is None


class CommunityMessage(BaseModel):
    """Persisted chat messages — REST + WS broadcast in the next chat slice."""

    class Status(models.TextChoices):
        PUBLISHED = "published", "Published"
        HIDDEN = "hidden", "Hidden"
        DELETED = "deleted", "Deleted"

    channel = models.ForeignKey(
        CommunityChannel,
        on_delete=models.CASCADE,
        related_name="messages",
    )
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="community_messages",
    )
    body = models.TextField()
    thread_root = models.ForeignKey(
        "self",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="replies",
    )
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.PUBLISHED,
        db_index=True,
    )
    edited_at = models.DateTimeField(null=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["created_at"]
        indexes = [
            models.Index(fields=["channel", "-created_at"]),
            models.Index(fields=["channel", "status", "-created_at"]),
            models.Index(fields=["thread_root", "created_at"]),
        ]

    def __str__(self) -> str:
        return f"msg {self.id} in {self.channel_id}"


class CommunityUserAvailability(BaseModel):
    """Per-location presence — mirrors prototype tenant-scoped availability."""

    class Status(models.TextChoices):
        AVAILABLE = "available", "Available"
        BUSY = "busy", "Busy"
        AWAY = "away", "Away"
        OFFLINE = "offline", "Offline"

    location = models.ForeignKey(
        "tenancy.Location",
        on_delete=models.CASCADE,
        related_name="community_availability",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="community_availability",
    )
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.OFFLINE,
        db_index=True,
    )
    status_message = models.CharField(max_length=160, blank=True, default="")
    expires_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["location", "user"],
                name="unique_community_availability_per_location_user",
            )
        ]
        indexes = [
            models.Index(fields=["location", "status"]),
        ]

    def __str__(self) -> str:
        return f"{self.user_id} @ {self.location_id}: {self.status}"


class CommunityDmConversation(BaseModel):
    """Same-location only direct message thread."""

    location = models.ForeignKey(
        "tenancy.Location",
        on_delete=models.CASCADE,
        related_name="community_dm_conversations",
    )
    # Sorted "uuidA:uuidB" — unique per location.
    participant_pair_key = models.CharField(max_length=80, db_index=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="community_dms_created",
    )
    last_message_at = models.DateTimeField(null=True, blank=True)
    last_message_preview = models.CharField(max_length=240, blank=True, default="")

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["location", "participant_pair_key"],
                name="unique_community_dm_pair_per_location",
            )
        ]
        indexes = [
            models.Index(fields=["location", "-last_message_at"]),
        ]
        ordering = ["-last_message_at", "-updated_at"]

    def __str__(self) -> str:
        return f"dm {self.id} @ {self.location_id}"


class CommunityDmParticipant(BaseModel):
    conversation = models.ForeignKey(
        CommunityDmConversation,
        on_delete=models.CASCADE,
        related_name="participants",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="community_dm_participations",
    )
    last_read_at = models.DateTimeField(null=True, blank=True)
    is_muted = models.BooleanField(default=False)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["conversation", "user"],
                name="unique_community_dm_participant",
            )
        ]

    def __str__(self) -> str:
        return f"{self.user_id} in dm {self.conversation_id}"


class CommunityDmMessage(BaseModel):
    class Status(models.TextChoices):
        PUBLISHED = "published", "Published"
        HIDDEN = "hidden", "Hidden"
        DELETED = "deleted", "Deleted"

    conversation = models.ForeignKey(
        CommunityDmConversation,
        on_delete=models.CASCADE,
        related_name="messages",
    )
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="community_dm_messages",
    )
    body = models.TextField()
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.PUBLISHED,
        db_index=True,
    )
    edited_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["created_at"]
        indexes = [
            models.Index(fields=["conversation", "-created_at"]),
            models.Index(fields=["conversation", "status", "-created_at"]),
        ]

    def __str__(self) -> str:
        return f"dm-msg {self.id}"


class CommunityPinnedMessage(BaseModel):
    channel = models.ForeignKey(
        CommunityChannel,
        on_delete=models.CASCADE,
        related_name="pins",
    )
    message = models.ForeignKey(
        CommunityMessage,
        on_delete=models.CASCADE,
        related_name="pins",
    )
    pinned_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="community_pins_created",
    )
    is_active = models.BooleanField(default=True, db_index=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["channel", "message"],
                condition=models.Q(is_active=True),
                name="unique_active_community_pin",
            )
        ]
        indexes = [
            models.Index(fields=["channel", "is_active", "-created_at"]),
        ]

    def __str__(self) -> str:
        return f"pin {self.message_id} in {self.channel_id}"


class CommunitySavedMessage(BaseModel):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="community_saved_messages",
    )
    message = models.ForeignKey(
        CommunityMessage,
        on_delete=models.CASCADE,
        related_name="saves",
    )
    # Snapshot of home location when saved (for scoping the saved list).
    location = models.ForeignKey(
        "tenancy.Location",
        on_delete=models.CASCADE,
        related_name="community_saved_messages",
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["user", "message"],
                name="unique_community_saved_message",
            )
        ]
        indexes = [
            models.Index(fields=["user", "location", "-created_at"]),
        ]
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"saved {self.message_id} by {self.user_id}"
