from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import (
    AgencyPortalLocationsView,
    AgencyPortalMembershipPermissionsView,
    AgencyPortalMembershipView,
    AgencyPortalOverviewView,
    AgencyPortalRolesView,
    AgencyPortalUsersView,
    AgencyViewSet,
    LocationViewSet,
    MembershipViewSet,
    MyLocationsView,
)

router = DefaultRouter()
router.register("agencies", AgencyViewSet, basename="agency")
router.register("locations", LocationViewSet, basename="location")
router.register("memberships", MembershipViewSet, basename="membership")

urlpatterns = [
    path("me/locations/", MyLocationsView.as_view(), name="my-locations"),
    path("agency/portal/", AgencyPortalOverviewView.as_view(), name="agency-portal"),
    path(
        "agency/locations/",
        AgencyPortalLocationsView.as_view(),
        name="agency-portal-locations",
    ),
    path("agency/users/", AgencyPortalUsersView.as_view(), name="agency-portal-users"),
    path("agency/roles/", AgencyPortalRolesView.as_view(), name="agency-portal-roles"),
    path(
        "agency/memberships/",
        AgencyPortalMembershipView.as_view(),
        name="agency-portal-memberships",
    ),
    path(
        "agency/memberships/<uuid:membership_id>/",
        AgencyPortalMembershipView.as_view(),
        name="agency-portal-membership-detail",
    ),
    path(
        "agency/memberships/<uuid:membership_id>/permissions/",
        AgencyPortalMembershipPermissionsView.as_view(),
        name="agency-portal-membership-permissions",
    ),
    *router.urls,
]
