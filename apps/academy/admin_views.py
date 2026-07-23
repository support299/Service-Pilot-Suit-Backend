"""Agency-portal Academy catalog admin endpoints."""
from __future__ import annotations

from rest_framework.permissions import BasePermission, IsAuthenticated
from rest_framework.views import APIView

from apps.common.responses import created, no_content, ok
from apps.rbac.constants import Permissions
from apps.rbac.permissions import effective_permissions
from apps.tenancy.services.agency_portal import (
    resolve_agency_for_request,
    user_can_manage_agency_portal,
)

from . import admin_services


class CanManageAcademyCatalog(BasePermission):
    """Agency admins / academy.manage holders can edit the shared catalog."""

    message = "Academy manage permission is required."

    def has_permission(self, request, view) -> bool:
        user = request.user
        if not user or not user.is_authenticated:
            return False
        if user.is_superuser:
            return True
        if Permissions.ACADEMY_MANAGE in effective_permissions(request):
            return True
        agency = resolve_agency_for_request(request)
        return user_can_manage_agency_portal(user, agency)


class AcademyAdminMetaView(APIView):
    permission_classes = [IsAuthenticated, CanManageAcademyCatalog]

    def get(self, request):
        return ok(admin_services.meta_options())


class AcademyAdminCourseListCreateView(APIView):
    permission_classes = [IsAuthenticated, CanManageAcademyCatalog]

    def get(self, request):
        rows = admin_services.list_courses_admin(
            section=request.query_params.get("section"),
            status=request.query_params.get("status"),
            search=request.query_params.get("q"),
        )
        return ok({"count": len(rows), "results": rows})

    def post(self, request):
        data = admin_services.create_course(request.data, user=request.user)
        return created(data)


class AcademyAdminCourseDetailView(APIView):
    permission_classes = [IsAuthenticated, CanManageAcademyCatalog]

    def get(self, request, course_id):
        return ok(admin_services.get_course_admin(str(course_id)))

    def patch(self, request, course_id):
        return ok(admin_services.update_course(str(course_id), request.data))

    def delete(self, request, course_id):
        admin_services.delete_course(str(course_id))
        return no_content()


class AcademyAdminCoursePublishView(APIView):
    permission_classes = [IsAuthenticated, CanManageAcademyCatalog]

    def post(self, request, course_id):
        status = str(request.data.get("status") or "published").strip()
        return ok(admin_services.set_course_status(str(course_id), status))


class AcademyAdminLessonListCreateView(APIView):
    permission_classes = [IsAuthenticated, CanManageAcademyCatalog]

    def post(self, request, course_id):
        data = admin_services.create_lesson(str(course_id), request.data)
        return created(data)


class AcademyAdminLessonDetailView(APIView):
    permission_classes = [IsAuthenticated, CanManageAcademyCatalog]

    def patch(self, request, lesson_id):
        return ok(admin_services.update_lesson(str(lesson_id), request.data))

    def delete(self, request, lesson_id):
        admin_services.delete_lesson(str(lesson_id))
        return no_content()
