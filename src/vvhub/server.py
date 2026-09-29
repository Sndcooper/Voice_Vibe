"""HTTP + WebSocket front of the hub (TASK.md §3.1-3.2).

Binds 127.0.0.1 only. Every HTTP call needs `Authorization: Bearer <token>`;
a WebSocket must send a `hello` carrying the token first or it is closed with
4401. The token lives in %LOCALAPPDATA%\\VoiceVibe\\hub.token.
"""

from __future__ import annotations

import asyncio
import contextlib
import hmac
import logging
import secrets as _random
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Header, HTTPException, WebSocket, WebSocketDisconnect

from . import __version__, data_dir, dispatch, protocol
from .bus import Bus
from .skills import discover
from .store import Store

log = logging.getLogger(__name__)

PURGE_INTERVAL = 3600.0


def token_path() -> Path:
    return data_dir() / "hub.token"


def load_or_create_token(path: Path | None = None) -> str:
    path = path or token_path()
    try:
        token = path.read_text(encoding="utf-8").strip()
        if token:
            return token
    except OSError:
        pass
    path.parent.mkdir(parents=True, exist_ok=True)
    token = _random.token_urlsafe(32)
    path.write_text(token, encoding="utf-8")
    return token


@dataclass
class Hub:
    """Everything a skill can reach: `hub.store`, `hub.bus`, `hub.skills`."""

    token: str
    store: Store
    bus: Bus = field(default_factory=Bus)
    skills: dict = field(default_factory=dict)
    components: dict = field(default_factory=dict)


def _authorized(hub: Hub, presented: str | None) -> bool:
    return bool(presented) and hmac.compare_digest(presented, hub.token)


def create_app(hub: Hub) -> FastAPI:
    @contextlib.asynccontextmanager
    async def lifespan(_app: FastAPI):  # noqa: ANN202
        async def purge_loop() -> None:
            while True:
                try:
                    counts = hub.store.purge()
                    if any(counts.values()):
                        log.info("Purged %s", counts)
                except Exception:  # noqa: BLE001
                    log.exception("Purge failed")
                await asyncio.sleep(PURGE_INTERVAL)

        task = asyncio.create_task(purge_loop())
        try:
            yield
        finally:
            task.cancel()

    app = FastAPI(title="vvhub", version=__version__, docs_url=None, redoc_url=None,
                  openapi_url=None, lifespan=lifespan)
    app.state.hub = hub
    if not hub.skills:
        hub.skills = discover(hub)

    @app.get("/health")
    async def health(authorization: str | None = Header(default=None)) -> dict:
        presented = (authorization or "").removeprefix("Bearer ").strip()
        if not _authorized(hub, presented):
            raise HTTPException(status_code=401, detail="bad or missing token")
        return {
            "ok": True,
            "version": __version__,
            "skills": sorted(hub.skills),
            "connected": sorted(r for r in protocol.ROLES if hub.bus.connected(r)),
            "components": hub.components,
        }

    @app.websocket("/ws")
    async def ws(socket: WebSocket) -> None:
        await socket.accept()
        try:
            hello = protocol.decode(await asyncio.wait_for(socket.receive_text(), 5.0))
        except (asyncio.TimeoutError, protocol.ProtocolError, WebSocketDisconnect):
            await _close(socket, protocol.CLOSE_BAD_HELLO)
            return
        if hello["type"] != "hello" or hello.get("role") not in protocol.ROLES:
            await _close(socket, protocol.CLOSE_BAD_HELLO)
            return
        if not _authorized(hub, hello.get("token")):
            await _close(socket, protocol.CLOSE_UNAUTHORIZED)
            return

        role = hello["role"]
        lock = asyncio.Lock()

        async def send(msg: dict) -> None:
            async with lock:
                await socket.send_text(protocol.encode(msg))

        hub.bus.attach(role, send)
        await send(protocol.reply_to(hello, "welcome", version=__version__))
        log.info("%s connected", role)
        tasks: set[asyncio.Task] = set()
        try:
            while True:
                try:
                    msg = protocol.decode(await socket.receive_text())
                except protocol.ProtocolError as exc:
                    await send(protocol.message("error", message=str(exc), code="bad_message"))
                    continue
                if msg.get("re") and hub.bus.deliver(msg):
                    continue
                task = asyncio.create_task(_answer(hub, msg, send))
                tasks.add(task)
                task.add_done_callback(tasks.discard)
        except WebSocketDisconnect:
            pass
        finally:
            hub.bus.detach(role, send)
            for task in tasks:
                task.cancel()
            log.info("%s disconnected", role)

    return app


async def _answer(hub: Hub, msg: dict, send: Any) -> None:
    kind = msg["type"]
    if kind == "ping":
        await send(protocol.reply_to(msg, "pong"))
    elif kind == "request":
        result = await dispatch.handle(
            hub, str(msg.get("text", "")), msg.get("context") or {},
            conversation=msg.get("conversation"), source=str(msg.get("source", "voice")),
        )
        await send(protocol.reply_to(
            msg, "reply", text=result.text, speak=result.speak,
            handled=bool(result.data.get("handled", True)), ok=result.ok,
        ))
    elif kind == "transcribe":
        # The bot sends voice notes here; Voice Vibe owns the Whisper model.
        try:
            reply = await hub.bus.send_to("voicevibe", protocol.message(
                "transcribe", audio_b64=msg.get("audio_b64", ""), format=msg.get("format", "ogg")))
            await send(protocol.reply_to(msg, "text", text=reply.get("text", "")))
        except Exception as exc:  # noqa: BLE001
            await send(protocol.reply_to(msg, "error", message=str(exc), code="no_transcriber"))
    elif kind == "notify":
        for role in ("bot", "ui"):
            await hub.bus.notify(role, msg)
    else:
        await send(protocol.reply_to(msg, "error", message=f"unexpected {kind}", code="unexpected"))


async def _close(socket: WebSocket, code: int) -> None:
    try:
        await socket.close(code=code)
    except RuntimeError:
        pass


def build_hub(store_path: Path | None = None) -> Hub:
    return Hub(token=load_or_create_token(), store=Store(store_path or data_dir() / "hub.db"))
