"""WebSocket consumers for community channel + DM rooms."""
from __future__ import annotations

import logging
from urllib.parse import parse_qs

from asgiref.sync import sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer
from django.contrib.auth import get_user_model
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError
from rest_framework_simplejwt.tokens import AccessToken

from apps.tenancy.models import Location, Membership

from . import services
from . import services_dms

logger = logging.getLogger("apps.community")
User = get_user_model()


class _CommunitySocketMixin:
    user = None
    location = None
    group_name: str = ""

    def _extract_token(self) -> str | None:
        query = parse_qs(self.scope.get("query_string", b"").decode())
        raw = (query.get("token") or [None])[0]
        if raw:
            return raw
        headers = {
            k.decode().lower(): v.decode()
            for k, v in (self.scope.get("headers") or [])
        }
        auth = headers.get("authorization") or ""
        if auth.lower().startswith("bearer "):
            return auth[7:].strip()
        return None

    @sync_to_async
    def _authenticate(self, token: str):
        try:
            access = AccessToken(token)
        except (InvalidToken, TokenError):
            return None, None

        user_id = access.get("user_id")
        ghl_location_id = access.get("location_id")
        query = parse_qs(self.scope.get("query_string", b"").decode())
        explicit_location = (query.get("location_id") or [None])[0]
        location_key = explicit_location or ghl_location_id

        try:
            user = User.objects.get(pk=user_id, is_active=True)
        except User.DoesNotExist:
            return None, None

        if not location_key:
            return user, None

        location = Location.objects.filter(
            ghl_location_id=location_key, is_active=True
        ).first()
        if location is None:
            return user, None

        if not user.is_superuser:
            member = Membership.objects.filter(
                user=user, location=location, is_active=True
            ).exists()
            if not member:
                return user, None

        return user, location


class CommunityChatConsumer(_CommunitySocketMixin, AsyncJsonWebsocketConsumer):
    channel_id: str = ""

    async def connect(self):
        self.channel_id = str(self.scope["url_route"]["kwargs"].get("channel_id") or "")
        if not self.channel_id:
            await self.close(code=4000)
            return

        token = self._extract_token()
        if not token:
            await self.close(code=4401)
            return

        user, location = await self._authenticate(token)
        if user is None or location is None:
            await self.close(code=4401)
            return

        allowed = await self._authorize_channel(user, location, self.channel_id)
        if not allowed:
            await self.close(code=4403)
            return

        self.user = user
        self.location = location
        self.group_name = services.channel_group_name(self.channel_id)
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()
        await self.send_json(
            {
                "type": "community.socket.ready",
                "channel_id": self.channel_id,
                "location_id": str(location.id),
            }
        )

    async def disconnect(self, code):
        if self.group_name:
            await self.channel_layer.group_discard(self.group_name, self.channel_name)

    async def receive_json(self, content, **kwargs):
        event = (content or {}).get("type")
        if event == "ping":
            await self.send_json({"type": "pong"})

    async def community_event(self, event):
        payload = event.get("payload") or {}
        await self.send_json(payload)

    @sync_to_async
    def _authorize_channel(self, user, location, channel_id: str) -> bool:
        try:
            channel = services.get_channel(channel_id)
        except Exception:
            return False
        return services.user_can_view_channel(channel, location=location, user=user)


class CommunityDmConsumer(_CommunitySocketMixin, AsyncJsonWebsocketConsumer):
    conversation_id: str = ""

    async def connect(self):
        self.conversation_id = str(
            self.scope["url_route"]["kwargs"].get("conversation_id") or ""
        )
        if not self.conversation_id:
            await self.close(code=4000)
            return

        token = self._extract_token()
        if not token:
            await self.close(code=4401)
            return

        user, location = await self._authenticate(token)
        if user is None or location is None:
            await self.close(code=4401)
            return

        allowed = await self._authorize_dm(user, location, self.conversation_id)
        if not allowed:
            await self.close(code=4403)
            return

        self.user = user
        self.location = location
        self.group_name = services_dms.dm_group_name(self.conversation_id)
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()
        await self.send_json(
            {
                "type": "community.dm.socket.ready",
                "conversation_id": self.conversation_id,
                "location_id": str(location.id),
            }
        )

    async def disconnect(self, code):
        if self.group_name:
            await self.channel_layer.group_discard(self.group_name, self.channel_name)

    async def receive_json(self, content, **kwargs):
        event = (content or {}).get("type")
        if event == "ping":
            await self.send_json({"type": "pong"})

    async def community_event(self, event):
        payload = event.get("payload") or {}
        await self.send_json(payload)

    @sync_to_async
    def _authorize_dm(self, user, location, conversation_id: str) -> bool:
        return services_dms.user_can_access_dm(
            conversation_id=conversation_id, location=location, user=user
        )
