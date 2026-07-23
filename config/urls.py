"""Root URL configuration.

All application endpoints live under ``/api/`` so the whole app can be served
from a single domain (frontend at ``/``, backend at ``/api/``).
"""
from django.contrib import admin
from django.http import JsonResponse
from django.urls import include, path


def healthcheck(_request):
    return JsonResponse({"status": "ok"})


api_patterns = [
    path("auth/", include("apps.authentication.urls")),
    path("", include("apps.accounts.urls")),
    path("", include("apps.tenancy.urls")),
    path("", include("apps.roi.urls")),
    path("", include("apps.support.urls")),
    path("", include("apps.academy.urls")),
]

urlpatterns = [
    path("api/admin/", admin.site.urls),
    path("api/health/", healthcheck, name="health"),
    path("api/", include((api_patterns, "api"))),
]
