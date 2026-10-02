"""The bot's WebSocket link to the hub (role "bot", TASK.md §3.1-3.2).

Reconnects with exponential backoff; the hub token is re-read from
%LOCALAPPDATA%\\VoiceVibe\\hub.token on every attempt (the hub creates it on
first start). Replies are matched to calls by `re`; everything else the hub
sends (approval_request, notify, ping) goes to `on_message`.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any, Awaitable, Callable

from vvhub import HOST, PORT, data_dir, protocol

from . import __version__

log = logging.getLogger(__name__)

URL = f"ws://{HOST}:{PORT}/ws"


class HubUnavailable(RuntimeError):
    pass


class ConnectionClosedLike(Exception):
    """What a fake socket raises in tests; real sockets raise websockets' ConnectionClosed."""

    def __init__(self, code: int) -> None:
        super().__init__(f"closed {code}")
        self.code = code


def read_token(path: Path | None = None) -> str | None:
    path = path or data_dir() / "hub.token"
    try:
        return path.read_text(encoding="utf-8").strip() or None
    except OSError:
        return None


def _close_code(exc: BaseException) -> int | None:
    code = getattr(exc, "code", None)
    if isinstance(code, int):
        return code
    rcvd = getattr(exc, "rcvd", None)
    return getattr(rcvd, "code", None)


async def _ws_connect(url: str) -> Any:
    from websockets.asyncio.client import connect

    return await connect(url, max_size=8 * 2**20, open_timeout=10, ping_interval=20)


class HubClient:
    def __init__(self, url: str = URL, token: Callable[[], str | None] = read_token,
                 on_message: Callable[[dict], Awaitable[None]] | None = None,
                 connect: Callable[[str], Awaitable[Any]] | None = None, role: str = "bot",
                 backoff: tuple[float, float] = (1.0, 30.0)) -> None:
        self.url = url
        self.token = token
        self.on_message = on_message
        self._connect = connect or _ws_connect
        self.role = role
        self.backoff = backoff
        self.last_error = ""
        self._ws: Any = None
        self._connected = asyncio.Event()
        self._waiting: dict[str, asyncio.Future] = {}
        self._tasks: set[asyncio.Task] = set()
        self._stopping = False

    @property
    def connected(self) -> bool:
        return self._connected.is_set()

    async def wait_connected(self) -> None:
        await self._connected.wait()

    async def run_forever(self) -> None:
        delay = self.backoff[0]
        while not self._stopping:
            try:
                await self._session()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - any failure means "reconnect later"
                code = _close_code(exc)
                if code == protocol.CLOSE_UNAUTHORIZED:
                    self.last_error = "hub rejected the token (hub.token changed?)"
                else:
                    self.last_error = str(exc) or type(exc).__name__
                log.info("hub link down: %s", self.last_error)
            finally:
                self._drop()
            if self._stopping:
                break
            await asyncio.sleep(delay)
            delay = min(delay * 2, self.backoff[1])

    def _drop(self) -> None:
        was = self.connected
        self._connected.clear()
        self._ws = None
        for fut in self._waiting.values():
            if not fut.done():
                fut.set_exception(HubUnavailable("hub disconnected"))
        self._waiting.clear()
        if was:
            log.info("hub disconnected")

    async def _session(self) -> None:
        token = self.token()
        if not token:
            raise HubUnavailable("no hub token yet (is the hub running?)")
        ws = await self._connect(self.url)
        self._ws = ws
        try:
            hello = protocol.message("hello", token=token, role=self.role, version=__version__)
            await ws.send(protocol.encode(hello))
            first = protocol.decode(await asyncio.wait_for(ws.recv(), 10))
            if first["type"] != "welcome":
                raise HubUnavailable(f"hub answered {first['type']} to hello")
            self._connected.set()
            self.last_error = ""
            log.info("connected to hub")
            while True:
                raw = await ws.recv()
                try:
                    msg = protocol.decode(raw)
                except protocol.ProtocolError:
                    continue
                fut = self._waiting.get(msg.get("re") or "")
                if fut is not None and not fut.done():
                    fut.set_result(msg)
                    continue
                if self.on_message is not None:
                    task = asyncio.create_task(self._dispatch(msg))
                    self._tasks.add(task)
                    task.add_done_callback(self._tasks.discard)
        finally:
            try:
                await ws.close()
            except Exception:  # noqa: BLE001
                pass

    async def _dispatch(self, msg: dict) -> None:
        try:
            await self.on_message(msg)  # type: ignore[misc]
        except Exception:  # noqa: BLE001
            log.exception("handling hub message %s failed", msg.get("type"))

    async def call(self, type_: str, timeout: float | None = None, **fields: Any) -> dict:
        """Send a request and wait for its reply. Raises HubUnavailable."""
        ws = self._ws
        if ws is None or not self.connected:
            raise HubUnavailable(self.last_error or "not connected to the hub")
        msg = protocol.message(type_, **fields)
        fut = asyncio.get_running_loop().create_future()
        self._waiting[msg["id"]] = fut
        try:
            await ws.send(protocol.encode(msg))
            wait = timeout if timeout is not None else protocol.timeout_for(type_) + 2
            return await asyncio.wait_for(fut, wait)
        except asyncio.TimeoutError:
            raise HubUnavailable("the hub didn't answer in time") from None
        finally:
            self._waiting.pop(msg["id"], None)

    async def send(self, msg: dict) -> None:
        ws = self._ws
        if ws is None or not self.connected:
            raise HubUnavailable(self.last_error or "not connected to the hub")
        await ws.send(protocol.encode(msg))

    async def stop(self) -> None:
        self._stopping = True
        ws = self._ws
        if ws is not None:
            try:
                await ws.close()
            except Exception:  # noqa: BLE001
                pass
