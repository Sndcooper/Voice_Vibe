"""How hub code reaches connected clients (Voice Vibe, the bot, the UI).

`await bus.send_to("voicevibe", message("confirm", prompt=...))` sends and waits
for the message whose `re` is that id. The server feeds every incoming reply
to `deliver`.
"""

from __future__ import annotations

import asyncio
from typing import Awaitable, Callable

from . import protocol

Sender = Callable[[dict], Awaitable[None]]


class NotConnected(RuntimeError):
    pass


class Bus:
    def __init__(self) -> None:
        self._senders: dict[str, Sender] = {}
        self._waiting: dict[str, asyncio.Future] = {}

    def attach(self, role: str, send: Sender) -> None:
        self._senders[role] = send

    def detach(self, role: str, send: Sender | None = None) -> None:
        if send is None or self._senders.get(role) is send:
            self._senders.pop(role, None)

    def connected(self, role: str) -> bool:
        return role in self._senders

    async def send_to(self, role: str, msg: dict, timeout: float | None = None) -> dict:
        """Send `msg` to `role` and return its reply. Raises NotConnected or
        asyncio.TimeoutError."""
        send = self._senders.get(role)
        if send is None:
            raise NotConnected(role)
        future = asyncio.get_running_loop().create_future()
        self._waiting[msg["id"]] = future
        try:
            await send(msg)
            wait = protocol.timeout_for(msg["type"]) if timeout is None else timeout
            return await asyncio.wait_for(future, wait)
        finally:
            self._waiting.pop(msg["id"], None)

    async def notify(self, role: str, msg: dict) -> bool:
        """Fire and forget. False if `role` is not connected."""
        send = self._senders.get(role)
        if send is None:
            return False
        await send(msg)
        return True

    def deliver(self, msg: dict) -> bool:
        """Resolve the waiter for a reply. False if nobody was waiting."""
        future = self._waiting.get(msg.get("re") or "")
        if future is None or future.done():
            return False
        future.set_result(msg)
        return True
