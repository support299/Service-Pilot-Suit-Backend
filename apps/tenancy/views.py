"""Tenant management endpoints.

All list/detail querysets are tenant-scoped: a user only ever sees agencies,
locations and memberships they are entitled to, unless they are a superuser.
"""
from __future__ import annotations

from rest_framework import mixins, viewsets
from rest_framework.permissions import BasePermission, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.exceptions import NotFoundError, PermissionDeniedError, ValidationError
from apps.common.responses import created, ok
from apps.rbac.constants import Permissions
from apps.rbac.models import Role
from apps.rbac.permissions import HasPermission, IsSuperAdmin, IsTenantMember
from apps.rbac.serializers import RoleSerializer

from .models import Agency, Location, Membership
from .serializers import (
    AccessibleLocationSerializer,
    AgencySerializer,
    LocationSerializer,
    MembershipSerializer,
)
from .services import accessible_locations_for_user
from .services.agency_portal import (
    agency_locations_qs,
    agency_users_payload,
    assignable_roles_qs,
    resolve_agency_for_request,
    serialize_membership_permissions,
    set_membership_permissions,
    user_can_manage_agency_portal,
    user_can_view_agency_portal,
)


class CanViewAgencyPortal(BasePermission):
    message = "Agency portal access is required."

    def has_permission(self, request, view) -> bool:
        agency = resolve_agency_for_request(request)
        return user_can_view_agency_portal(request.user, agency)


class CanManageAgencyPortal(BasePermission):
    message = "Agency manage permission is required."

    def has_permission(self, request, view) -> bool:
        agency = resolve_agency_for_request(request)
        return user_can_manage_agency_portal(request.user, agency)


class MyLocationsView(APIView):
    """Locations the current user can access — powers the tenant switcher."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        locations = accessible_locations_for_user(request.user)
        data = AccessibleLocationSerializer(locations, many=True).data
        return Response({"results": data})


class AgencyViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    serializer_class = AgencySerializer
    search_fields = ("name", "ghl_company_id")
    ordering_fields = ("name", "created_at")

    def get_permissions(self):
        if self.action in ("update", "partial_update"):
            return [IsAuthenticated(), IsSuperAdmin()]
        return [IsAuthenticated(), IsSuperAdmin()]

    def get_queryset(self):
        return Agency.objects.all()


class LocationViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    serializer_class = LocationSerializer
    search_fields = ("name", "ghl_location_id")
    ordering_fields = ("name", "created_at", "status")
    lookup_field = "ghl_location_id"

    def get_permissions(self):
        if self.action in ("update", "partial_update"):
            return [
                IsAuthenticated(),
                IsTenantMember(),
                HasPermission.require(Permissions.LOCATION_MANAGE)(),
            ]
        return [IsAuthenticated()]

    def get_queryset(self):
        return accessible_locations_for_user(self.request.user)


class MembershipViewSet(viewsets.ModelViewSet):
    """Members of the *current* location (X-Location-Id)."""

    serializer_class = MembershipSerializer
    search_fields = ("user__email", "user__first_name", "user__last_name")
    ordering_fields = ("created_at",)

    def get_permissions(self):
        if self.action in ("list", "retrieve"):
            return [
                IsAuthenticated(),
                IsTenantMember(),
                HasPermission.require(Permissions.MEMBER_VIEW)(),
            ]
        return [
            IsAuthenticated(),
            IsTenantMember(),
            HasPermission.require(Permissions.MEMBER_MANAGE)(),
        ]

    def get_queryset(self):
        location = getattr(self.request, "location", None)
        if location is None:
            return Membership.objects.none()
        return (
            Membership.objects.filter(location=location)
            .select_related("user", "role", "location")
        )

    def perform_create(self, serializer):
        serializer.save(location=self.request.location)


class AgencyPortalOverviewView(APIView):
    """Agency home summary for the portal."""

    permission_classes = [IsAuthenticated, CanViewAgencyPortal]

    def get(self, request):
        agency = resolve_agency_for_request(request)
        if agency is None:
            raise NotFoundError("No agency found for this account.", code="agency_not_found")
        locations = agency_locations_qs(agency)
        users = agency_users_payload(agency)
        return ok(
            {
                "agency": AgencySerializer(agency).data,
                "stats": {
                    "locations": locations.count(),
                    "users": len(users),
                    "memberships": sum(len(u["access"]) for u in users),
                },
                "can_manage": user_can_manage_agency_portal(request.user, agency),
            }
        )


class AgencyPortalLocationsView(APIView):
    permission_classes = [IsAuthenticated, CanViewAgencyPortal]

    def get(self, request):
        agency = resolve_agency_for_request(request)
        if agency is None:
            raise NotFoundError("No agency found for this account.", code="agency_not_found")
        rows = []
        for loc in agency_locations_qs(agency):
            data = LocationSerializer(loc).data
            data["member_count"] = getattr(loc, "member_count", 0)
            rows.append(data)
        return ok({"agency_id": str(agency.id), "count": len(rows), "results": rows})


class AgencyPortalUsersView(APIView):
    """Users and which locations they can access under the agency."""

    permission_classes = [IsAuthenticated, CanViewAgencyPortal]

    def get(self, request):
        agency = resolve_agency_for_request(request)
        if agency is None:
            raise NotFoundError("No agency found for this account.", code="agency_not_found")
        q = (request.query_params.get("search") or "").strip().lower()
        users = agency_users_payload(agency)
        if q:
            users = [
                u
                for u in users
                if q in (u.get("full_name") or "").lower()
                or q in (u.get("email") or "").lower()
            ]
        return ok(
            {
                "agency_id": str(agency.id),
                "count": len(users),
                "results": users,
                "can_manage": user_can_manage_agency_portal(request.user, agency),
            }
        )


class AgencyPortalRolesView(APIView):
    permission_classes = [IsAuthenticated, CanViewAgencyPortal]

    def get(self, request):
        roles = assignable_roles_qs(request.user)
        return ok({"results": RoleSerializer(roles, many=True).data})


class AgencyPortalMembershipView(APIView):
    """Assign / update / revoke location access from the agency portal."""

    def get_permissions(self):
        if self.request.method == "POST":
            return [IsAuthenticated(), CanManageAgencyPortal()]
        if self.request.method in ("PATCH", "DELETE"):
            return [IsAuthenticated(), CanManageAgencyPortal()]
        return [IsAuthenticated(), CanViewAgencyPortal()]

    def post(self, request):
        agency = resolve_agency_for_request(request)
        if agency is None:
            raise NotFoundError("No agency found for this account.", code="agency_not_found")

        user_id = request.data.get("user_id")
        role_id = request.data.get("role_id")
        location_id = (
            request.data.get("location_id")
            or request.data.get("ghl_location_id")
            or ""
        )
        if not user_id or not role_id or not location_id:
            raise ValidationError(
                "user_id, role_id, and location_id are required.",
                code="agency_membership_invalid",
            )

        from django.contrib.auth import get_user_model

        User = get_user_model()
        try:
            target_user = User.objects.get(pk=user_id)
        except User.DoesNotExist as exc:
            raise NotFoundError("User not found.", code="user_not_found") from exc

        location = (
            Location.objects.filter(agency=agency, pk=location_id).first()
            or Location.objects.filter(agency=agency, ghl_location_id=str(location_id)).first()
        )
        if location is None:
            raise NotFoundError(
                "Location not found under this agency.",
                code="location_not_found",
            )

        try:
            role = Role.objects.get(pk=role_id)
        except Role.DoesNotExist as exc:
            raise NotFoundError("Role not found.", code="role_not_found") from exc

        if role.slug == "super_admin" and not request.user.is_superuser:
            raise PermissionDeniedError("Cannot assign Super Admin.", code="role_forbidden")

        membership, created_flag = Membership.objects.update_or_create(
            user=target_user,
            location=location,
            defaults={
                "role": role,
                "is_active": bool(request.data.get("is_active", True)),
            },
        )
        membership = (
            Membership.objects.select_related("user", "role", "location", "location__agency")
            .get(pk=membership.pk)
        )
        return created(MembershipSerializer(membership).data) if created_flag else ok(
            MembershipSerializer(membership).data
        )

    def patch(self, request, membership_id=None):
        agency = resolve_agency_for_request(request)
        if agency is None:
            raise NotFoundError("No agency found for this account.", code="agency_not_found")
        membership = (
            Membership.objects.select_related("user", "role", "location")
            .filter(pk=membership_id, location__agency=agency)
            .first()
        )
        if membership is None:
            raise NotFoundError("Membership not found.", code="membership_not_found")

        role_id = request.data.get("role_id")
        if role_id is not None:
            try:
                role = Role.objects.get(pk=role_id)
            except Role.DoesNotExist as exc:
                raise NotFoundError("Role not found.", code="role_not_found") from exc
            if role.slug == "super_admin" and not request.user.is_superuser:
                raise PermissionDeniedError("Cannot assign Super Admin.", code="role_forbidden")
            membership.role = role
            # Role change resets toggles — start from the new role baseline.
            membership.permission_grants = []
            membership.permission_denies = []
        if "is_active" in request.data:
            membership.is_active = bool(request.data.get("is_active"))
        membership.save()
        membership.refresh_from_db()
        membership = (
            Membership.objects.select_related("user", "role", "location", "location__agency")
            .get(pk=membership.pk)
        )
        return ok(MembershipSerializer(membership).data)

    def delete(self, request, membership_id=None):
        agency = resolve_agency_for_request(request)
        if agency is None:
            raise NotFoundError("No agency found for this account.", code="agency_not_found")
        membership = Membership.objects.filter(
            pk=membership_id, location__agency=agency
        ).first()
        if membership is None:
            raise NotFoundError("Membership not found.", code="membership_not_found")
        membership.delete()
        return Response(status=204)


class AgencyPortalMembershipPermissionsView(APIView):
    """Get / set per-membership permission toggles."""

    def get_permissions(self):
        if self.request.method == "PUT":
            return [IsAuthenticated(), CanManageAgencyPortal()]
        return [IsAuthenticated(), CanViewAgencyPortal()]

    def get(self, request, membership_id):
        agency = resolve_agency_for_request(request)
        if agency is None:
            raise NotFoundError("No agency found for this account.", code="agency_not_found")
        membership = (
            Membership.objects.select_related("user", "role", "location")
            .filter(pk=membership_id, location__agency=agency)
            .first()
        )
        if membership is None:
            raise NotFoundError("Membership not found.", code="membership_not_found")
        return ok(serialize_membership_permissions(membership))

    def put(self, request, membership_id):
        agency = resolve_agency_for_request(request)
        if agency is None:
            raise NotFoundError("No agency found for this account.", code="agency_not_found")
        membership = (
            Membership.objects.select_related("user", "role", "location")
            .filter(pk=membership_id, location__agency=agency)
            .first()
        )
        if membership is None:
            raise NotFoundError("Membership not found.", code="membership_not_found")
        enabled = request.data.get("enabled")
        if enabled is None and "permissions" in request.data:
            enabled = request.data.get("permissions")
        data = set_membership_permissions(
            membership,
            enabled=enabled,
            grants=request.data.get("permission_grants"),
            denies=request.data.get("permission_denies"),
        )
        return ok(data)
