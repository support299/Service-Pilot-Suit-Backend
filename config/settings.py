"""
Django settings for the Service Pilot Suite backend.

Configuration is 12-factor: everything environment-specific is read from the
environment (see ``.env.example``) via ``django-environ``. Nothing secret is
hard-coded here.
"""
from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import environ

BASE_DIR = Path(__file__).resolve().parent.parent

env = environ.Env(
    DJANGO_DEBUG=(bool, False),
    DJANGO_ALLOWED_HOSTS=(list, ["localhost", "127.0.0.1"]),
    CORS_ALLOWED_ORIGINS=(list, ["http://localhost:5173"]),
    JWT_ACCESS_TOKEN_LIFETIME_MINUTES=(int, 60),
    JWT_REFRESH_TOKEN_LIFETIME_DAYS=(int, 7),
    GHL_SCOPES=(str, "locations.readonly users.readonly companies.readonly"),
    GHL_API_BASE_URL=(str, "https://services.leadconnectorhq.com"),
    GHL_API_VERSION=(str, "2021-07-28"),
    GHL_AUTOLOGIN_SHARED_SECRET=(str, ""),
    GHL_VERSION_ID=(str, ""),
    REDIS_URL=(str, "redis://localhost:6379/0"),
    FRONTEND_BASE_URL=(str, "http://localhost:5173"),
)

# Read .env if present (never committed).
_env_file = BASE_DIR / ".env"
if _env_file.exists():
    env.read_env(str(_env_file))


# ─────────────────────────────────────────────────────────────
# Core
# ─────────────────────────────────────────────────────────────
SECRET_KEY = env("DJANGO_SECRET_KEY", default="insecure-dev-key-change-me")
DEBUG = env("DJANGO_DEBUG")
ALLOWED_HOSTS = env("DJANGO_ALLOWED_HOSTS")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # Third-party
    "rest_framework",
    "rest_framework_simplejwt.token_blacklist",
    "corsheaders",
    "django_filters",
    # Local apps
    "apps.common",
    "apps.rbac",
    "apps.accounts",
    "apps.tenancy",
    "apps.authentication",
    "apps.roi",
    "apps.support",
    "apps.academy",
]

MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    # Resolves the current tenant (request.location / request.location_id).
    "apps.tenancy.middleware.TenantMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"


# ─────────────────────────────────────────────────────────────
# Database
# ─────────────────────────────────────────────────────────────
# Prefer DATABASE_URL when set; otherwise discrete NAME/USER/PASSWORD/HOST
# (also accepts POSTGRES_* aliases).
if env("DATABASE_URL", default=""):
    DATABASES = {"default": env.db("DATABASE_URL")}
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": env("NAME", default=env("POSTGRES_DB", default="service_pilot_suite")),
            "USER": env("USER", default=env("POSTGRES_USER", default="postgres")),
            "PASSWORD": env("PASSWORD", default=env("POSTGRES_PASSWORD", default="")),
            "HOST": env("HOST", default=env("POSTGRES_HOST", default="localhost")),
            "PORT": env("PORT", default=env("POSTGRES_PORT", default="5432")),
        }
    }
DATABASES["default"].setdefault("CONN_MAX_AGE", 60)

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
AUTH_USER_MODEL = "accounts.User"


# ─────────────────────────────────────────────────────────────
# Password validation
# ─────────────────────────────────────────────────────────────
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]


# ─────────────────────────────────────────────────────────────
# I18N
# ─────────────────────────────────────────────────────────────
LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True


# ─────────────────────────────────────────────────────────────
# Static files (WhiteNoise)
# ─────────────────────────────────────────────────────────────
STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
    },
}


# ─────────────────────────────────────────────────────────────
# DRF + JWT
# ─────────────────────────────────────────────────────────────
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": (
        "apps.authentication.jwt.TenantJWTAuthentication",
    ),
    "DEFAULT_PERMISSION_CLASSES": ("rest_framework.permissions.IsAuthenticated",),
    "DEFAULT_PAGINATION_CLASS": "apps.common.pagination.DefaultPagination",
    "PAGE_SIZE": 25,
    "DEFAULT_FILTER_BACKENDS": (
        "django_filters.rest_framework.DjangoFilterBackend",
        "rest_framework.filters.SearchFilter",
        "rest_framework.filters.OrderingFilter",
    ),
    "EXCEPTION_HANDLER": "apps.common.exceptions.api_exception_handler",
    "DEFAULT_RENDERER_CLASSES": ("rest_framework.renderers.JSONRenderer",),
}

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(
        minutes=env("JWT_ACCESS_TOKEN_LIFETIME_MINUTES")
    ),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=env("JWT_REFRESH_TOKEN_LIFETIME_DAYS")),
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": True,
    "UPDATE_LAST_LOGIN": True,
    "USER_ID_FIELD": "id",
    "USER_ID_CLAIM": "user_id",
    "AUTH_HEADER_TYPES": ("Bearer",),
}


# ─────────────────────────────────────────────────────────────
# CORS
# ─────────────────────────────────────────────────────────────
CORS_ALLOWED_ORIGINS = env("CORS_ALLOWED_ORIGINS")
CORS_ALLOW_CREDENTIALS = True
# Allow the tenant header used by the frontend to scope requests.
from corsheaders.defaults import default_headers  # noqa: E402

CORS_ALLOW_HEADERS = (*default_headers, "x-location-id", "x-ghl-signature")


# ─────────────────────────────────────────────────────────────
# Cache / Redis / Celery
# ─────────────────────────────────────────────────────────────
REDIS_URL = env("REDIS_URL")
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": REDIS_URL,
    }
}
CELERY_BROKER_URL = env("CELERY_BROKER_URL", default=REDIS_URL)
CELERY_RESULT_BACKEND = env("CELERY_RESULT_BACKEND", default=REDIS_URL)
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_TIMEZONE = TIME_ZONE
CELERY_ENABLE_UTC = True
# Small EC2 (≈1GB / 2 vCPU): keep workers lean; beat jobs are infrequent.
CELERY_BROKER_CONNECTION_RETRY_ON_STARTUP = True
CELERY_WORKER_PREFETCH_MULTIPLIER = 1
CELERY_WORKER_MAX_TASKS_PER_CHILD = 40
CELERY_TASK_ACKS_LATE = True
CELERY_TASK_REJECT_ON_WORKER_LOST = True
CELERY_TASK_TRACK_STARTED = True
CELERY_RESULT_EXPIRES = 3600  # 1h — don't pile results in Redis
CELERY_TASK_SOFT_TIME_LIMIT = 25 * 60  # ads sync can be long
CELERY_TASK_TIME_LIMIT = 30 * 60
# GHL access tokens expire (~24h); refresh agency + location tokens every 10h
# (same cadence as Snapshot JobTracker). Requires: celery -A config beat
CELERY_BEAT_SCHEDULE = {
    "refresh-ghl-tokens-every-10-hours": {
        "task": "apps.authentication.tasks.refresh_ghl_tokens",
        "schedule": timedelta(hours=10),
    },
    # Meta + Google ads daily facts + campaign catalog (ROI Center).
    "sync-meta-ads-every-10-hours": {
        "task": "apps.roi.tasks.sync_all_locations_meta_ads",
        "schedule": timedelta(hours=10),
    },
    "sync-google-ads-every-10-hours": {
        "task": "apps.roi.tasks.sync_all_locations_google_ads",
        "schedule": timedelta(hours=10),
    },
    # CRM opportunities: marketplace webhooks at /api/accounts/webhook/
    # (OpportunityCreate/Update/StageUpdate/Delete). Manual sync endpoint remains.
}


# ─────────────────────────────────────────────────────────────
# GoHighLevel integration
# ─────────────────────────────────────────────────────────────
GHL = {
    "CLIENT_ID": env("GHL_CLIENT_ID", default=""),
    "CLIENT_SECRET": env("GHL_CLIENT_SECRET", default=""),
    "REDIRECT_URI": env(
        "GHL_REDIRECT_URI", default="http://localhost:8000/api/auth/ghl/callback"
    ),
    "SCOPES": env("GHL_SCOPES"),
    "API_BASE_URL": env("GHL_API_BASE_URL"),
    "API_VERSION": env("GHL_API_VERSION"),
    "VERSION_ID": env("GHL_VERSION_ID"),
    "AUTOLOGIN_SHARED_SECRET": env("GHL_AUTOLOGIN_SHARED_SECRET"),
}
FRONTEND_BASE_URL = env("FRONTEND_BASE_URL")


# ─────────────────────────────────────────────────────────────
# Security (tightened when DEBUG is False)
# ─────────────────────────────────────────────────────────────
if not DEBUG:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = 31536000
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True
    SECURE_CONTENT_TYPE_NOSNIFF = True

CSRF_TRUSTED_ORIGINS = env(
    "CSRF_TRUSTED_ORIGINS", default=["http://localhost:5173", "http://localhost:8000"]
)


# ─────────────────────────────────────────────────────────────
# Logging
# ─────────────────────────────────────────────────────────────
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {
            "format": "[{asctime}] {levelname} {name}: {message}",
            "style": "{",
        },
    },
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "verbose"},
    },
    "root": {"handlers": ["console"], "level": "INFO"},
    "loggers": {
        "apps": {"handlers": ["console"], "level": "INFO", "propagate": False},
        "django.request": {"handlers": ["console"], "level": "WARNING"},
    },
}
