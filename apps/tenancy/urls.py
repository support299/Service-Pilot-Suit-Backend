from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import AgencyViewSet, LocationViewSet, MembershipViewSet, MyLocationsView

router = DefaultRouter()
router.register("agencies", AgencyViewSet, basename="agency")
router.register("locations", LocationViewSet, basename="location")
router.register("memberships", MembershipViewSet, basename="membership")

urlpatterns = [
    path("me/locations/", MyLocationsView.as_view(), name="my-locations"),
    *router.urls,
]
