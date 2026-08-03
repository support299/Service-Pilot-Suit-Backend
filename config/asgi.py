"""ASGI application — HTTP (Django) + WebSocket (Channels).

Run with Daphne (preferred once Community is enabled)::

    daphne -b 0.0.0.0 -p 8000 config.asgi:application

Plain ``runserver`` works for HTTP after Daphne is in INSTALLED_APPS, but
production and WebSocket testing should use Daphne/Uvicorn against this module.
"""
import os

from channels.auth import AuthMiddlewareStack
from channels.routing import ProtocolTypeRouter, URLRouter
from channels.security.websocket import AllowedHostsOriginValidator
from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

django_asgi_app = get_asgi_application()

# Import after Django setup so models/apps are ready.
from apps.community.routing import websocket_urlpatterns  # noqa: E402

application = ProtocolTypeRouter(
    {
        "http": django_asgi_app,
        "websocket": AllowedHostsOriginValidator(
            AuthMiddlewareStack(URLRouter(websocket_urlpatterns))
        ),
    }
)
