"""Success Center — Feature Center API."""
from __future__ import annotations

from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

from apps.common.responses import created, ok
from apps.rbac.constants import Permissions
from apps.rbac.permissions import HasPermission, HasTenantContext, IsTenantMember

from . import services


def _page_params(request) -> tuple[int, int]:
    try:
        page = int(request.query_params.get("page") or 1)
    except (TypeError, ValueError):
        page = 1
    try:
        page_size = int(request.query_params.get("page_size") or 25)
    except (TypeError, ValueError):
        page_size = 25
    return page, page_size


class FeatureMetaView(APIView):
    permission_classes = [
        IsAuthenticated,
        HasTenantContext,
        IsTenantMember,
        HasPermission.require(Permissions.FEATURE_VIEW),
    ]

    def get(self, request):
        return ok(
            {
                "categories": services.category_catalog(),
                "statuses": services.status_catalog(),
            }
        )


class FeatureSummaryView(APIView):
    permission_classes = [
        IsAuthenticated,
        HasTenantContext,
        IsTenantMember,
        HasPermission.require(Permissions.FEATURE_VIEW),
    ]

    def get(self, request):
        return ok(services.feature_summary(user=request.user))


class FeatureHomeView(APIView):
    permission_classes = [
        IsAuthenticated,
        HasTenantContext,
        IsTenantMember,
        HasPermission.require(Permissions.FEATURE_VIEW),
    ]

    def get(self, request):
        return ok(services.home_payload(user=request.user))


class FeatureRequestListCreateView(APIView):
    permission_classes = [
        IsAuthenticated,
        HasTenantContext,
        IsTenantMember,
        HasPermission.require(Permissions.FEATURE_VIEW),
    ]

    def get(self, request):
        page, page_size = _page_params(request)
        exclude_released = request.query_params.get("exclude_released") in (
            "1",
            "true",
            "True",
        )
        data = services.list_feature_requests(
            user=request.user,
            status=request.query_params.get("status"),
            category=request.query_params.get("category"),
            search=request.query_params.get("q"),
            sort=request.query_params.get("sort") or "votes",
            page=page,
            page_size=page_size,
            include_staff=False,
            exclude_released=exclude_released,
        )
        return ok(data)

    def post(self, request):
        data = services.create_feature_request(
            location=request.location,
            user=request.user,
            title=request.data.get("title", ""),
            description=request.data.get("description", ""),
            category=request.data.get("category") or "other",
        )
        return created(data)


class FeatureRequestDetailView(APIView):
    permission_classes = [
        IsAuthenticated,
        HasTenantContext,
        IsTenantMember,
        HasPermission.require(Permissions.FEATURE_VIEW),
    ]

    def get(self, request, request_id):
        return ok(
            services.get_feature_detail(
                str(request_id),
                user=request.user,
                include_staff=False,
            )
        )


class FeatureVoteView(APIView):
    permission_classes = [
        IsAuthenticated,
        HasTenantContext,
        IsTenantMember,
        HasPermission.require(Permissions.FEATURE_VIEW),
    ]

    def post(self, request, request_id):
        return ok(services.add_vote(request_id=str(request_id), user=request.user))

    def delete(self, request, request_id):
        return ok(services.remove_vote(request_id=str(request_id), user=request.user))


class FeatureCommentCreateView(APIView):
    permission_classes = [
        IsAuthenticated,
        HasTenantContext,
        IsTenantMember,
        HasPermission.require(Permissions.FEATURE_VIEW),
    ]

    def post(self, request, request_id):
        data = services.add_public_comment(
            request_id=str(request_id),
            user=request.user,
            body=request.data.get("body", ""),
        )
        return created(data)


class FeatureAnnouncementsView(APIView):
    permission_classes = [
        IsAuthenticated,
        HasTenantContext,
        IsTenantMember,
        HasPermission.require(Permissions.FEATURE_VIEW),
    ]

    def get(self, request):
        try:
            limit = int(request.query_params.get("limit") or 50)
        except (TypeError, ValueError):
            limit = 50
        return ok(services.list_published_announcements(limit=limit))


# ─── Staff (feature.manage — Super Admin by default seed) ───


class StaffFeatureRequestListView(APIView):
    permission_classes = [
        IsAuthenticated,
        HasTenantContext,
        IsTenantMember,
        HasPermission.require(Permissions.FEATURE_MANAGE),
    ]

    def get(self, request):
        page, page_size = _page_params(request)
        data = services.list_feature_requests(
            user=request.user,
            status=request.query_params.get("status"),
            category=request.query_params.get("category"),
            search=request.query_params.get("q"),
            sort=request.query_params.get("sort") or "updated",
            page=page,
            page_size=page_size,
            include_staff=True,
        )
        return ok(data)


class StaffFeatureRequestDetailView(APIView):
    permission_classes = [
        IsAuthenticated,
        HasTenantContext,
        IsTenantMember,
        HasPermission.require(Permissions.FEATURE_MANAGE),
    ]

    def get(self, request, request_id):
        return ok(
            services.get_feature_detail(
                str(request_id),
                user=request.user,
                include_staff=True,
            )
        )


class StaffFeatureStatusView(APIView):
    permission_classes = [
        IsAuthenticated,
        HasTenantContext,
        IsTenantMember,
        HasPermission.require(Permissions.FEATURE_MANAGE),
    ]

    def patch(self, request, request_id):
        data = services.update_status(
            request_id=str(request_id),
            user=request.user,
            status=request.data.get("status", ""),
        )
        return ok(data)


class StaffFeatureCommentView(APIView):
    permission_classes = [
        IsAuthenticated,
        HasTenantContext,
        IsTenantMember,
        HasPermission.require(Permissions.FEATURE_MANAGE),
    ]

    def post(self, request, request_id):
        data = services.add_internal_comment(
            request_id=str(request_id),
            user=request.user,
            body=request.data.get("body", ""),
        )
        return created(data)


class StaffReleaseNoteListCreateView(APIView):
    permission_classes = [
        IsAuthenticated,
        HasTenantContext,
        IsTenantMember,
        HasPermission.require(Permissions.FEATURE_MANAGE),
    ]

    def get(self, request):
        return ok(
            services.list_release_notes_staff(
                request_id=request.query_params.get("request_id"),
                status=request.query_params.get("status"),
            )
        )

    def post(self, request):
        publish = request.data.get("publish") in (True, "true", "1", 1)
        data = services.create_release_note(
            user=request.user,
            title=request.data.get("title", ""),
            body=request.data.get("body", ""),
            request_id=request.data.get("feature_request_id")
            or request.data.get("request_id"),
            publish=publish,
        )
        return created(data)


class StaffReleaseNoteDetailView(APIView):
    permission_classes = [
        IsAuthenticated,
        HasTenantContext,
        IsTenantMember,
        HasPermission.require(Permissions.FEATURE_MANAGE),
    ]

    def patch(self, request, note_id):
        kwargs: dict = {
            "note_id": str(note_id),
            "user": request.user,
        }
        if "title" in request.data:
            kwargs["title"] = request.data.get("title")
        if "body" in request.data:
            kwargs["body"] = request.data.get("body")
        if "feature_request_id" in request.data or "request_id" in request.data:
            kwargs["request_id"] = request.data.get("feature_request_id") or request.data.get(
                "request_id"
            )
        return ok(services.update_release_note(**kwargs))


class StaffReleaseNotePublishView(APIView):
    permission_classes = [
        IsAuthenticated,
        HasTenantContext,
        IsTenantMember,
        HasPermission.require(Permissions.FEATURE_MANAGE),
    ]

    def post(self, request, note_id):
        return ok(
            services.publish_release_note(note_id=str(note_id), user=request.user)
        )


class StaffReleaseNoteArchiveView(APIView):
    permission_classes = [
        IsAuthenticated,
        HasTenantContext,
        IsTenantMember,
        HasPermission.require(Permissions.FEATURE_MANAGE),
    ]

    def post(self, request, note_id):
        return ok(
            services.archive_release_note(note_id=str(note_id), user=request.user)
        )
