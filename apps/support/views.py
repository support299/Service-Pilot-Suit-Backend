"""Success Center — Support API."""
from __future__ import annotations

from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

from apps.common.responses import created, ok
from apps.rbac.constants import Permissions
from apps.rbac.permissions import HasPermission, HasTenantContext, IsTenantMember, effective_permissions

from . import services


def _request_files(request) -> list:
    """Collect uploaded files from ``files`` or ``file`` multipart fields."""
    uploaded = request.FILES.getlist("files") or request.FILES.getlist("file")
    return [f for f in uploaded if f]


class TicketSummaryView(APIView):
    permission_classes = [
        IsAuthenticated,
        HasTenantContext,
        IsTenantMember,
        HasPermission.require(Permissions.SUPPORT_VIEW),
    ]

    def get(self, request):
        data = services.ticket_summary(request.location)
        data["location_id"] = request.location.ghl_location_id
        return ok(data)


class TicketListCreateView(APIView):
    parser_classes = [JSONParser, MultiPartParser, FormParser]
    permission_classes = [
        IsAuthenticated,
        HasTenantContext,
        IsTenantMember,
        HasPermission.require(Permissions.SUPPORT_VIEW),
    ]

    def get(self, request):
        rows = services.list_tickets(
            request.location,
            status=request.query_params.get("status"),
            search=request.query_params.get("q"),
        )
        return ok(
            {
                "location_id": request.location.ghl_location_id,
                "count": len(rows),
                "results": rows,
            }
        )

    def post(self, request):
        data = services.create_ticket_with_uploads(
            request.location,
            user=request.user,
            subject=request.data.get("subject", ""),
            description=request.data.get("description", ""),
            category=request.data.get("category") or "general",
            priority=request.data.get("priority") or "normal",
            files=_request_files(request),
        )
        return created(data)


class TicketDetailView(APIView):
    permission_classes = [
        IsAuthenticated,
        HasTenantContext,
        IsTenantMember,
        HasPermission.require(Permissions.SUPPORT_VIEW),
    ]

    def get(self, request, ticket_id):
        ticket = services.get_ticket(request.location, str(ticket_id))
        return ok(services.serialize_ticket(ticket, include_messages=True))


class TicketStatusView(APIView):
    permission_classes = [
        IsAuthenticated,
        HasTenantContext,
        IsTenantMember,
        HasPermission.require(Permissions.SUPPORT_MANAGE),
    ]

    def patch(self, request, ticket_id):
        data = services.update_ticket_status(
            request.location,
            str(ticket_id),
            status=request.data.get("status", ""),
            user=request.user,
        )
        return ok(data)


class TicketMessageCreateView(APIView):
    parser_classes = [JSONParser, MultiPartParser, FormParser]
    permission_classes = [
        IsAuthenticated,
        HasTenantContext,
        IsTenantMember,
        HasPermission.require(Permissions.SUPPORT_VIEW),
    ]

    def post(self, request, ticket_id):
        perms = effective_permissions(request)
        is_staff = request.user.is_superuser or Permissions.SUPPORT_MANAGE in perms
        data = services.add_message_with_uploads(
            request.location,
            str(ticket_id),
            user=request.user,
            body=request.data.get("body", ""),
            is_staff_reply=is_staff,
            files=_request_files(request),
        )
        return created(data)
