from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import GhlMarketplaceWebhookView, UserViewSet

router = DefaultRouter()
router.register("users", UserViewSet, basename="user")

urlpatterns = [
    path(
        "accounts/webhook/",
        GhlMarketplaceWebhookView.as_view(),
        name="ghl-marketplace-webhook",
    ),
    *router.urls,
]
