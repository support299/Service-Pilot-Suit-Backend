"""Success Center — Community API (hub + channels)."""
from __future__ import annotations

from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

from apps.common.responses import created, ok
from apps.rbac.constants import Permissions
from apps.rbac.permissions import HasPermission, HasTenantContext, IsTenantMember, effective_permissions

from . import services
from .models import CommunityChannel


class CommunityHubView(APIView):
    """GET grouped channel list + recent activity + create meta."""

    permission_classes = [
        IsAuthenticated,
        HasTenantContext,
        IsTenantMember,
        HasPermission.require(Permissions.COMMUNITY_VIEW),
    ]

    def get(self, request):
        include_archived = request.query_params.get("include_archived") in (
            "1",
            "true",
            "True",
        )
        held = effective_permissions(request)
        return ok(
            services.list_hub(
                location=request.location,
                user=request.user,
                held=held,
                include_archived=include_archived,
            )
        )


class CommunityChannelListCreateView(APIView):
    permission_classes = [
        IsAuthenticated,
        HasTenantContext,
        IsTenantMember,
        HasPermission.require(Permissions.COMMUNITY_VIEW),
    ]

    def get(self, request):
        """Flat list helper — same visibility as hub, without grouping."""
        include_archived = request.query_params.get("include_archived") in (
            "1",
            "true",
            "True",
        )
        held = effective_permissions(request)
        hub = services.list_hub(
            location=request.location,
            user=request.user,
            held=held,
            include_archived=include_archived,
        )
        channels = (
            hub["company"]["channels"]
            + hub["service_pilot"]["channels"]
            + hub["industry"]["channels"]
        )
        return ok({"count": len(channels), "channels": channels, "meta": hub["meta"]})

    def post(self, request):
        held = effective_permissions(request)
        data = services.create_channel(
            location=request.location,
            user=request.user,
            held=held,
            name=request.data.get("name", ""),
            description=request.data.get("description", ""),
            channel_type=request.data.get("channel_type")
            or request.data.get("visibility")
            or "",
        )
        return created(data)


class CommunityChannelDetailView(APIView):
    permission_classes = [
        IsAuthenticated,
        HasTenantContext,
        IsTenantMember,
        HasPermission.require(Permissions.COMMUNITY_VIEW),
    ]

    def get(self, request, channel_id):
        held = effective_permissions(request)
        return ok(
            services.get_channel_detail(
                channel_id=str(channel_id),
                location=request.location,
                user=request.user,
                held=held,
            )
        )

    def patch(self, request, channel_id):
        held = effective_permissions(request)
        payload = request.data or {}
        return ok(
            services.update_channel(
                channel_id=str(channel_id),
                location=request.location,
                user=request.user,
                held=held,
                name=payload.get("name"),
                description=payload.get("description"),
                is_archived=payload.get("is_archived"),
                featured=payload.get("featured"),
                sort_order=payload.get("sort_order"),
            )
        )

    def delete(self, request, channel_id):
        """Soft-archive (preferred over hard delete)."""
        held = effective_permissions(request)
        return ok(
            services.archive_channel(
                channel_id=str(channel_id),
                location=request.location,
                user=request.user,
                held=held,
            )
        )


class CommunityChannelMembersView(APIView):
    permission_classes = [
        IsAuthenticated,
        HasTenantContext,
        IsTenantMember,
        HasPermission.require(Permissions.COMMUNITY_VIEW),
    ]

    def get(self, request, channel_id):
        held = effective_permissions(request)
        return ok(
            services.list_members(
                channel_id=str(channel_id),
                location=request.location,
                user=request.user,
                held=held,
            )
        )

    def post(self, request, channel_id):
        held = effective_permissions(request)
        payload = request.data or {}
        return created(
            services.add_channel_member(
                channel_id=str(channel_id),
                location=request.location,
                user=request.user,
                held=held,
                target_user_id=str(payload.get("user_id") or ""),
                role=payload.get("role") or "member",
            )
        )


class CommunityChannelMemberDetailView(APIView):
    permission_classes = [
        IsAuthenticated,
        HasTenantContext,
        IsTenantMember,
        HasPermission.require(Permissions.COMMUNITY_VIEW),
    ]

    def patch(self, request, channel_id, user_id):
        held = effective_permissions(request)
        payload = request.data or {}
        return ok(
            services.update_channel_member_role(
                channel_id=str(channel_id),
                location=request.location,
                user=request.user,
                held=held,
                target_user_id=str(user_id),
                role=payload.get("role") or "",
            )
        )

    def delete(self, request, channel_id, user_id):
        held = effective_permissions(request)
        return ok(
            services.remove_channel_member(
                channel_id=str(channel_id),
                location=request.location,
                user=request.user,
                held=held,
                target_user_id=str(user_id),
            )
        )


class CommunityMetaView(APIView):
    permission_classes = [
        IsAuthenticated,
        HasTenantContext,
        IsTenantMember,
        HasPermission.require(Permissions.COMMUNITY_VIEW),
    ]

    def get(self, request):
        held = effective_permissions(request)
        return ok(
            {
                "channel_types": [
                    {"value": c.value, "label": c.label}
                    for c in CommunityChannel.ChannelType
                ],
                "creatable_types": services.creatable_channel_types(held),
                "permissions": {
                    "view": Permissions.COMMUNITY_VIEW in held,
                    "post": Permissions.COMMUNITY_POST in held
                    or services.can_manage_company(held)
                    or services.can_manage_platform(held),
                    "manage": services.can_manage_company(held),
                    "manage_platform": services.can_manage_platform(held),
                },
            }
        )


class CommunityChannelMessagesView(APIView):
    permission_classes = [
        IsAuthenticated,
        HasTenantContext,
        IsTenantMember,
        HasPermission.require(Permissions.COMMUNITY_VIEW),
    ]

    def get(self, request, channel_id):
        return ok(
            services.list_messages(
                channel_id=str(channel_id),
                location=request.location,
                user=request.user,
                limit=request.query_params.get("limit") or 50,
                before=request.query_params.get("before"),
            )
        )

    def post(self, request, channel_id):
        held = effective_permissions(request)
        data = services.create_message(
            channel_id=str(channel_id),
            location=request.location,
            user=request.user,
            held=held,
            body=request.data.get("body", ""),
            thread_root_id=request.data.get("thread_root_id"),
        )
        return created(data)


class CommunityMessageDetailView(APIView):
    permission_classes = [
        IsAuthenticated,
        HasTenantContext,
        IsTenantMember,
        HasPermission.require(Permissions.COMMUNITY_VIEW),
    ]

    def patch(self, request, message_id):
        held = effective_permissions(request)
        return ok(
            services.update_message(
                message_id=str(message_id),
                location=request.location,
                user=request.user,
                held=held,
                body=request.data.get("body", ""),
            )
        )

    def delete(self, request, message_id):
        held = effective_permissions(request)
        return ok(
            services.delete_message(
                message_id=str(message_id),
                location=request.location,
                user=request.user,
                held=held,
            )
        )


# ─── Phase 2: availability / DMs / pins / saved ───────────────────────────

from . import services_availability  # noqa: E402
from . import services_dms  # noqa: E402
from . import services_pins  # noqa: E402


_VIEW_PERMS = [
    IsAuthenticated,
    HasTenantContext,
    IsTenantMember,
    HasPermission.require(Permissions.COMMUNITY_VIEW),
]


class CommunityAvailabilityMeView(APIView):
    permission_classes = _VIEW_PERMS

    def get(self, request):
        return ok(
            services_availability.get_my_availability(
                location=request.location, user=request.user
            )
        )

    def put(self, request):
        return ok(
            services_availability.set_my_availability(
                location=request.location,
                user=request.user,
                status=request.data.get("status", ""),
                status_message=request.data.get("status_message", ""),
            )
        )


class CommunityChannelAvailabilityView(APIView):
    permission_classes = _VIEW_PERMS

    def get(self, request, channel_id):
        return ok(
            services_availability.list_channel_availability(
                channel_id=str(channel_id),
                location=request.location,
                user=request.user,
            )
        )


class CommunityDmListCreateView(APIView):
    permission_classes = _VIEW_PERMS

    def get(self, request):
        return ok(
            services_dms.list_dms(location=request.location, user=request.user)
        )

    def post(self, request):
        return created(
            services_dms.open_or_create_dm(
                location=request.location,
                user=request.user,
                target_user_id=request.data.get("user_id")
                or request.data.get("target_user_id")
                or "",
            )
        )


class CommunityDmMessagesView(APIView):
    permission_classes = _VIEW_PERMS

    def get(self, request, conversation_id):
        return ok(
            services_dms.list_dm_messages(
                conversation_id=str(conversation_id),
                location=request.location,
                user=request.user,
                limit=request.query_params.get("limit") or 50,
                before=request.query_params.get("before"),
            )
        )

    def post(self, request, conversation_id):
        return created(
            services_dms.create_dm_message(
                conversation_id=str(conversation_id),
                location=request.location,
                user=request.user,
                body=request.data.get("body", ""),
            )
        )


class CommunityDmReadView(APIView):
    permission_classes = _VIEW_PERMS

    def post(self, request, conversation_id):
        return ok(
            services_dms.mark_dm_read(
                conversation_id=str(conversation_id),
                location=request.location,
                user=request.user,
            )
        )


class CommunityChannelPinsView(APIView):
    permission_classes = _VIEW_PERMS

    def get(self, request, channel_id):
        return ok(
            services_pins.list_pins(
                channel_id=str(channel_id),
                location=request.location,
                user=request.user,
            )
        )


class CommunityMessagePinView(APIView):
    permission_classes = _VIEW_PERMS

    def post(self, request, message_id):
        held = effective_permissions(request)
        return created(
            services_pins.pin_message(
                message_id=str(message_id),
                location=request.location,
                user=request.user,
                held=held,
            )
        )

    def delete(self, request, message_id):
        held = effective_permissions(request)
        return ok(
            services_pins.unpin_message(
                message_id=str(message_id),
                location=request.location,
                user=request.user,
                held=held,
            )
        )


class CommunitySavedListView(APIView):
    permission_classes = _VIEW_PERMS

    def get(self, request):
        return ok(
            services_pins.list_saved(location=request.location, user=request.user)
        )


class CommunityMessageSaveView(APIView):
    permission_classes = _VIEW_PERMS

    def post(self, request, message_id):
        return created(
            services_pins.save_message(
                message_id=str(message_id),
                location=request.location,
                user=request.user,
            )
        )

    def delete(self, request, message_id):
        return ok(
            services_pins.unsave_message(
                message_id=str(message_id),
                location=request.location,
                user=request.user,
            )
        )


# ─── Phase 3: notifications / reactions / reports ─────────────────────────

from . import services_notifications  # noqa: E402
from . import services_reactions  # noqa: E402
from . import services_reports  # noqa: E402


class CommunityNotificationListView(APIView):
    permission_classes = _VIEW_PERMS

    def get(self, request):
        unread_only = request.query_params.get("unread_only") in (
            "1",
            "true",
            "True",
        )
        return ok(
            services_notifications.list_notifications(
                user=request.user,
                limit=request.query_params.get("limit") or 40,
                unread_only=unread_only,
            )
        )


class CommunityNotificationReadAllView(APIView):
    permission_classes = _VIEW_PERMS

    def post(self, request):
        return ok(services_notifications.mark_all_notifications_read(user=request.user))


class CommunityNotificationReadView(APIView):
    permission_classes = _VIEW_PERMS

    def post(self, request, notification_id):
        read = request.data.get("is_read", True)
        if isinstance(read, str):
            read = read.lower() not in ("0", "false", "no")
        return ok(
            services_notifications.mark_notification_read(
                notification_id=str(notification_id),
                user=request.user,
                read=bool(read),
            )
        )


class CommunityChannelNotificationsReadView(APIView):
    permission_classes = _VIEW_PERMS

    def post(self, request, channel_id):
        return ok(
            services_notifications.mark_channel_notifications_read(
                channel_id=str(channel_id),
                location=request.location,
                user=request.user,
            )
        )


class CommunityChannelNotificationPreferenceView(APIView):
    permission_classes = _VIEW_PERMS

    def get(self, request, channel_id):
        return ok(
            services_notifications.get_channel_preference(
                channel_id=str(channel_id),
                location=request.location,
                user=request.user,
            )
        )

    def put(self, request, channel_id):
        payload = request.data or {}
        return ok(
            services_notifications.update_channel_preference(
                channel_id=str(channel_id),
                location=request.location,
                user=request.user,
                notification_level=payload.get("notification_level"),
                notify_thread_replies=payload.get("notify_thread_replies"),
                is_muted=payload.get("is_muted"),
                is_hidden=payload.get("is_hidden"),
            )
        )


class CommunityReactionMetaView(APIView):
    permission_classes = _VIEW_PERMS

    def get(self, request):
        return ok({"reactions": services_reactions.reaction_meta()})


class CommunityMessageReactionView(APIView):
    permission_classes = _VIEW_PERMS

    def post(self, request, message_id):
        held = effective_permissions(request)
        return ok(
            services_reactions.toggle_channel_reaction(
                message_id=str(message_id),
                location=request.location,
                user=request.user,
                held=held,
                reaction_key=request.data.get("reaction_key")
                or request.data.get("key")
                or "",
            )
        )


class CommunityDmMessageReactionView(APIView):
    permission_classes = _VIEW_PERMS

    def post(self, request, message_id):
        return ok(
            services_reactions.toggle_dm_reaction(
                message_id=str(message_id),
                location=request.location,
                user=request.user,
                reaction_key=request.data.get("reaction_key")
                or request.data.get("key")
                or "",
            )
        )


class CommunityMessageReportView(APIView):
    permission_classes = _VIEW_PERMS

    def post(self, request, message_id):
        return created(
            services_reports.report_message(
                message_id=str(message_id),
                location=request.location,
                user=request.user,
                reason=request.data.get("reason", "other"),
                notes=request.data.get("notes", ""),
            )
        )


class CommunityReportsListView(APIView):
    permission_classes = _VIEW_PERMS

    def get(self, request):
        held = effective_permissions(request)
        return ok(
            services_reports.list_reports(
                location=request.location,
                user=request.user,
                held=held,
                status=request.query_params.get("status") or "open",
            )
        )


class CommunityReportDetailView(APIView):
    permission_classes = _VIEW_PERMS

    def patch(self, request, report_id):
        held = effective_permissions(request)
        return ok(
            services_reports.update_report_status(
                report_id=str(report_id),
                location=request.location,
                user=request.user,
                held=held,
                status=request.data.get("status", ""),
            )
        )
