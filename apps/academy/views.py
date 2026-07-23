"""Success Center — Academy API."""
from __future__ import annotations

from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

from apps.common.responses import created, no_content, ok
from apps.rbac.constants import Permissions
from apps.rbac.permissions import HasPermission, HasTenantContext, IsTenantMember

from . import services


class AcademySummaryView(APIView):
    permission_classes = [
        IsAuthenticated,
        HasTenantContext,
        IsTenantMember,
        HasPermission.require(Permissions.ACADEMY_VIEW),
    ]

    def get(self, request):
        data = services.academy_summary(request.location, request.user)
        data["location_id"] = request.location.ghl_location_id
        return ok(data)


class AcademyCourseListView(APIView):
    permission_classes = [
        IsAuthenticated,
        HasTenantContext,
        IsTenantMember,
        HasPermission.require(Permissions.ACADEMY_VIEW),
    ]

    def get(self, request):
        rows = services.list_courses(
            request.location,
            request.user,
            section=request.query_params.get("section"),
            search=request.query_params.get("q"),
        )
        return ok(
            {
                "location_id": request.location.ghl_location_id,
                "count": len(rows),
                "results": rows,
            }
        )


class AcademyCourseDetailView(APIView):
    permission_classes = [
        IsAuthenticated,
        HasTenantContext,
        IsTenantMember,
        HasPermission.require(Permissions.ACADEMY_VIEW),
    ]

    def get(self, request, course_id):
        data = services.get_course(request.location, request.user, str(course_id))
        return ok(data)


class AcademyLessonDetailView(APIView):
    permission_classes = [
        IsAuthenticated,
        HasTenantContext,
        IsTenantMember,
        HasPermission.require(Permissions.ACADEMY_VIEW),
    ]

    def get(self, request, lesson_id):
        data = services.get_lesson(request.location, request.user, str(lesson_id))
        return ok(data)


class AcademyProgressView(APIView):
    permission_classes = [
        IsAuthenticated,
        HasTenantContext,
        IsTenantMember,
        HasPermission.require(Permissions.ACADEMY_VIEW),
    ]

    def post(self, request):
        data = services.upsert_lesson_progress(
            request.location,
            request.user,
            lesson_id=str(request.data.get("lesson_id") or ""),
            status=str(request.data.get("status") or ""),
            percent_complete=request.data.get("percent_complete"),
        )
        return ok(data)


class AcademySavedListCreateView(APIView):
    permission_classes = [
        IsAuthenticated,
        HasTenantContext,
        IsTenantMember,
        HasPermission.require(Permissions.ACADEMY_VIEW),
    ]

    def get(self, request):
        rows = services.list_saved(request.location, request.user)
        return ok({"count": len(rows), "results": rows})

    def post(self, request):
        data = services.save_content(
            request.location,
            request.user,
            course_id=request.data.get("course_id"),
            lesson_id=request.data.get("lesson_id"),
        )
        return created(data)

    def delete(self, request):
        services.unsave_content(
            request.location,
            request.user,
            course_id=request.data.get("course_id")
            or request.query_params.get("course_id"),
            lesson_id=request.data.get("lesson_id")
            or request.query_params.get("lesson_id"),
        )
        return no_content()
