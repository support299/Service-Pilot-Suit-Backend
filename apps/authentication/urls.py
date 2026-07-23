from django.urls import path

from .views import (
    GHLAuthorizeView,
    GHLAutoLoginView,
    GHLCallbackView,
    GHLOAuthSessionView,
    MeView,
    RefreshTokenView,
    SwitchLocationView,
)

urlpatterns = [
    # Canonical ghl paths.
    path("ghl/authorize", GHLAuthorizeView.as_view(), name="ghl-authorize"),
    path("ghl/callback", GHLCallbackView.as_view(), name="ghl-callback"),
    path("ghl/callback/", GHLCallbackView.as_view(), name="ghl-callback-slash"),
    path("ghl/auto-login", GHLAutoLoginView.as_view(), name="ghl-auto-login"),
    path("ghl/oauth-session", GHLOAuthSessionView.as_view(), name="ghl-oauth-session"),
    # Marketplace redirect URI uses /crm/callback/ (trailing slash).
    path("crm/authorize", GHLAuthorizeView.as_view(), name="crm-authorize"),
    path("crm/callback", GHLCallbackView.as_view(), name="crm-callback"),
    path("crm/callback/", GHLCallbackView.as_view(), name="crm-callback-slash"),
    path("crm/auto-login", GHLAutoLoginView.as_view(), name="crm-auto-login"),
    path("crm/oauth-session", GHLOAuthSessionView.as_view(), name="crm-oauth-session"),
    path("token/refresh", RefreshTokenView.as_view(), name="token-refresh"),
    path("me", MeView.as_view(), name="me"),
    path("switch-location", SwitchLocationView.as_view(), name="switch-location"),
]
