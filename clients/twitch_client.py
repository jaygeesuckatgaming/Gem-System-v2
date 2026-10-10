"""
Twitch Client
Connects directly to Twitch via twitchio 3.x EventSub over WebSocket,
independent of SSN, so Gem can react to live channel events
(subscriptions, follows, raids, bits, gift subs, resubs).

The client emits structured event dicts to a callback set by main.py.

Auth requirements (twitchio 3.x):
  - TWITCH_CLIENT_ID     : app client id (dev.twitch.tv console)
  - TWITCH_CLIENT_SECRET : app secret (for the app access token)
  - TWITCH_OAUTH_TOKEN   : broadcaster user access token
  - TWITCH_REFRESH_TOKEN : broadcaster refresh token (for managed tokens)
  - TWITCH_CHANNEL       : channel login to watch
"""

import asyncio
from typing import Optional, Callable


class TwitchClient:
    def __init__(self, client_id: str = "", client_secret: str = "",
                 oauth_token: str = "", refresh_token: str = "", channel: str = ""):
        self.client_id = client_id
        self.client_secret = client_secret
        self.oauth_token = oauth_token
        self.refresh_token = refresh_token
        self.channel = channel
        self.enabled = False
        self.on_event: Optional[Callable] = None  # async callback(event_dict)
        self._client = None
        self._task = None

    def check_connection(self) -> bool:
        """Verify credentials are present (real connection happens on start())."""
        if not self.channel:
            print("[X] Twitch not configured: channel is empty")
            self.enabled = False
            return False
        if not self.client_id:
            print("[X] Twitch not configured: client_id is empty")
            self.enabled = False
            return False
        self.enabled = True
        print(f"[OK] Twitch configured (channel: {self.channel})")
        return True

    def _register_events(self, client):
        """Register EventSub listeners that forward to self.on_event."""

        async def _emit(event_type: str, data: dict):
            data["event_type"] = event_type
            data.setdefault("channel", self.channel)
            if self.on_event:
                try:
                    await self.on_event(data)
                except Exception as e:
                    print(f"[Twitch] on_event handler failed: {e}")

        def _uname(obj, default="someone"):
            if obj is None:
                return default
            return getattr(obj, "display_name", None) or getattr(obj, "name", None) or default

        @client.listen("event_subscription")
        async def _on_subscription(event):
            await _emit("subscription", {
                "user": _uname(event.user),
                "tier": getattr(event, "tier", "1"),
                "is_gift": bool(getattr(event, "gift", False)),
            })

        @client.listen("event_subscription_message")
        async def _on_resub(event):
            await _emit("resubscription", {
                "user": _uname(event.user),
                "tier": getattr(event, "tier", "1"),
                "months": getattr(event, "cumulative_months", None) or getattr(event, "months", None),
            })

        @client.listen("event_subscription_gift")
        async def _on_gift(event):
            await _emit("gift_sub", {
                "user": _uname(event.user),
                "total": getattr(event, "total", None),
            })

        @client.listen("event_follow")
        async def _on_follow(event):
            await _emit("follow", {"user": _uname(event.user)})

        @client.listen("event_raid")
        async def _on_raid(event):
            await _emit("raid", {
                "user": _uname(event.from_broadcaster),
                "viewers": getattr(event, "viewer_count", None),
            })

        @client.listen("event_cheer")
        async def _on_cheer(event):
            await _emit("cheer", {
                "user": _uname(event.user),
                "bits": getattr(event, "bits", None),
            })

    async def _run(self):
        """Login, subscribe to events, and run the twitchio client."""
        from twitchio import Client

        client = Client(client_id=self.client_id, client_secret=self.client_secret)
        self._register_events(client)
        self._client = client

        # Managed token flow: provide the broadcaster user token + refresh token.
        if self.oauth_token and self.refresh_token:
            await client.add_token(self.oauth_token, self.refresh_token)

        async with client:
            await client.start()
            # Subscribe after login so the app token is available.
            await self._subscribe(client)

            # Run until the client is closed (start() blocks here).
            await client.wait_until_ready()

    async def _subscribe(self, client):
        """Resolve the channel id and subscribe to the six events."""
        from twitchio.eventsub import (
            ChannelSubscribeSubscription,
            ChannelSubscribeMessageSubscription,
            ChannelSubscriptionGiftSubscription,
            ChannelFollowSubscription,
            ChannelRaidSubscription,
            ChannelCheerSubscription,
        )

        try:
            user = await client.fetch_user(login=self.channel)
            if user is None:
                print(f"[Twitch] Could not resolve channel '{self.channel}'")
                return
            broadcaster_id = user.id
        except Exception as e:
            print(f"[Twitch] Failed to resolve channel: {e}")
            return

        subscriptions = [
            ChannelSubscribeSubscription(broadcaster_user_id=broadcaster_id),
            ChannelSubscribeMessageSubscription(broadcaster_user_id=broadcaster_id),
            ChannelSubscriptionGiftSubscription(broadcaster_user_id=broadcaster_id),
            ChannelFollowSubscription(broadcaster_user_id=broadcaster_id),
            ChannelRaidSubscription(broadcaster_user_id=broadcaster_id),
            ChannelCheerSubscription(broadcaster_user_id=broadcaster_id),
        ]

        for sub in subscriptions:
            try:
                await client.subscribe_websocket(sub, token_for=broadcaster_id)
            except Exception as e:
                print(f"[Twitch] Failed to subscribe to {sub.type}: {e}")

        print(f"[Twitch] Subscribed to channel events for '{self.channel}'")

    def start(self):
        """Launch the Twitch client as a background asyncio task."""
        if not self.enabled:
            print("[Twitch] Not started (disabled or not configured)")
            return
        if self._task and not self._task.done():
            print("[Twitch] Already running")
            return
        self._task = asyncio.create_task(self._run())

    async def stop(self):
        if self._client is not None:
            try:
                await self._client.close()
            except Exception:
                pass
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass
