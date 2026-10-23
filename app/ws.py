"""WebSocket hub: live updates for group dashboards and private panels."""
# How it works: each open browser window keeps one WebSocket. The hub remembers the
# sockets per user, so the server can push an event (new message, new alert, updated
# tasks) to exactly the people who should see it, e.g. only the members of one group,
# or only the asker for private AI help.

from __future__ import annotations

import asyncio
from collections import defaultdict
from typing import Any

from fastapi import WebSocket


class Hub:
    """Tracks open WebSockets per user and pushes events to them."""
    def __init__(self) -> None:
        """Start with no connections."""
        self._by_user: dict[str, set[WebSocket]] = defaultdict(set)
        self._lock = asyncio.Lock()

    async def connect(self, ws: WebSocket, user_id: str) -> None:
        """Accept a socket and register it for the user."""
        await ws.accept()
        async with self._lock:
            self._by_user[user_id].add(ws)

    async def disconnect(self, ws: WebSocket, user_id: str) -> None:
        """Forget a closed socket."""
        async with self._lock:
            self._by_user[user_id].discard(ws)
            if not self._by_user[user_id]:
                self._by_user.pop(user_id, None)

    async def send_user(self, user_id: str, event: str, payload: Any) -> None:
        """Push an event to every open window of one user."""
        await self._send(self._targets(user_id), event, payload)

    async def send_users(self, user_ids: list[str], event: str, payload: Any) -> None:
        """Push an event to every open window of several users."""
        targets: list[WebSocket] = []
        for uid in set(user_ids):
            targets += self._targets(uid)
        await self._send(targets, event, payload)

    def _targets(self, user_id: str) -> list[WebSocket]:
        """Open sockets of one user."""
        return list(self._by_user.get(user_id, ()))

    async def _send(self, targets: list[WebSocket], event: str, payload: Any) -> None:
        """Send to each socket and drop the ones that have closed."""
        # The browser receives {event, payload} and api.js re-emits it as 'ws:<event>'.
        message = {"event": event, "payload": payload}
        dead: list[WebSocket] = []
        for ws in targets:
            try:
                await ws.send_json(message)
            except Exception:
                dead.append(ws)
        if dead:
            async with self._lock:
                for uid, conns in list(self._by_user.items()):
                    for ws in dead:
                        conns.discard(ws)
                    if not conns:
                        self._by_user.pop(uid, None)

    def online(self) -> set[str]:
        """Ids of users with at least one open window."""
        return set(self._by_user.keys())


# The single shared hub imported by app/main.py.
hub = Hub()
