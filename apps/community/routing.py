from django.urls import re_path

from .consumers import CommunityChatConsumer, CommunityDmConsumer, CommunityInboxConsumer

websocket_urlpatterns = [
    re_path(
        r"^ws/community/channels/(?P<channel_id>[0-9a-f-]+)/$",
        CommunityChatConsumer.as_asgi(),
    ),
    re_path(
        r"^ws/community/dms/(?P<conversation_id>[0-9a-f-]+)/$",
        CommunityDmConsumer.as_asgi(),
    ),
    re_path(
        r"^ws/community/inbox/$",
        CommunityInboxConsumer.as_asgi(),
    ),
]
