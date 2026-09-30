"""Voice Vibe's link to vvhub (TASK.md §3.2).

One daemon thread runs an asyncio loop holding a single WebSocket to
ws://127.0.0.1:53874/ws. Everything is optional and failure-tolerant:

  * hub not running / `websockets` missing -> `request()` returns None at once
    and Voice Vibe types the text exactly as today (rule 8);
  * the link drops -> reconnect with backoff (1 s doubling to 30 s);
  * a request times out -> None, same fallback.

The hub can also ask *us* for things; each is a callable injected by the app
(`handlers`), so tests never touch the desktop, mic or models:

  confirm      (prompt, timeout)     -> bool      spoken yes/no
  get_context  (deep)                -> dict      §3.3 bundle
  list_mics    ()                    -> dict      {"devices": [...], "current": ...}
  set_mic      (device)              -> None
  transcribe   (audio_bytes, format) -> str       Telegram voice notes
  run_steps    (steps, dry_run)      -> None      actions.py spec (raises on error)
"""

from __future__ import annotations

import asyncio
import base64
import concurrent.futures
import logging
import threading
from pathlib import Path
from typing import Any, Callable

from vvhub import protocol

log = logging.getLogger(__name__)

HOST = "127.0.0.1"
PORT = 53874
BACKOFF_START, BACKOFF_MAX = 1.0, 30.0


def default_token_path() -> Path:
    from .history import data_dir

    return data_dir() / "hub.token"


class HubClient:
    def __init__(self, handlers: dict[str, Callable[..., Any]] | None = None, *,
                 url: str = f"ws://{HOST}:{PORT}/ws",
                 token: Callable[[], str | None] | None = None,
                 connect: Callable[..., Any] | None = None) -> None:
        self.url = url
        self.handlers = dict(handlers or {})
        self._token = token or self._read_token
        self._connect = connect
        self._loop: asyncio.AbstractEventLoop | None = None
        self._ws: Any = None
        self._ready = threading.Event()
        self._stopping = False
        self._thread: threading.Thread | None = None
        self._waiting: dict[str, asyncio.Future] = {}
        self._main: asyncio.Task | None = None
        self._tasks: set[asyncio.Task] = set()

    # ------------------------------------------------------------ lifecycle
    @staticmethod
    def _read_token() -> str | None:
        try:
            return default_token_path().read_text(encoding="utf-8").strip() or None
        except OSError:
            return None

    @property
    def connected(self) -> bool:
        return self._ready.is_set()

    def start(self) -> "HubClient":
        if self._connect is None:
            try:
                from websockets.asyncio.client import connect
            except ImportError:
                log.info("Hub link off: the websockets package is not installed.")
                return self
            self._connect = connect
        self._thread = threading.Thread(target=self._run, name="hub-link", daemon=True)
        self._thread.start()
        return self

    def stop(self) -> None:
        self._stopping = True
        loop = self._loop
        if loop is not None and loop.is_running():
            loop.call_soon_threadsafe(lambda: asyncio.ensure_future(self._close()))
        if self._thread is not None:
            self._thread.join(timeout=2)

    async def _close(self) -> None:
        if self._ws is not None:
            try:
                await self._ws.close()
            except Exception:  # noqa: BLE001
                pass
        current = asyncio.current_task()
        tasks = [t for t in asyncio.all_tasks() if t is not current]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        asyncio.get_running_loop().stop()

    def _run(self) -> None:
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        # asyncio only holds weak references to tasks: without this one the
        # reconnect loop is garbage-collected mid-sleep and never retries.
        self._main = self._loop.create_task(self._keep_connected())
        try:
            self._loop.run_forever()
        finally:
            self._loop.close()

    async def _keep_connected(self) -> None:
        delay = BACKOFF_START
        while not self._stopping:
            try:
                await self._session()
                delay = BACKOFF_START
            except Exception as exc:  # noqa: BLE001 - any failure means "retry later"
                log.debug("Hub link: %s", exc)
            self._ready.clear()
            self._ws = None
            for future in self._waiting.values():
                if not future.done():
                    future.set_result(None)
            if self._stopping:
                break
            await asyncio.sleep(delay)
            delay = min(delay * 2, BACKOFF_MAX)

    async def _session(self) -> None:
        token = self._token()
        if not token:
            raise ConnectionError("no hub token yet (hub never started)")
        async with self._connect(self.url, open_timeout=3, max_size=16 * 2**20) as ws:
            await ws.send(protocol.encode(protocol.message(
                "hello", token=token, role="voicevibe", version=protocol.VERSION)))
            welcome = protocol.decode(await asyncio.wait_for(ws.recv(), 5))
            if welcome["type"] != "welcome":
                raise ConnectionError(f"hub refused: {welcome}")
            self._ws = ws
            self._ready.set()
            log.info("Hub link up (%s)", self.url)
            async for raw in ws:
                try:
                    msg = protocol.decode(raw)
                except protocol.ProtocolError as exc:
                    log.debug("Hub sent a bad message: %s", exc)
                    continue
                future = self._waiting.get(msg.get("re") or "")
                if future is not None and not future.done():
                    future.set_result(msg)
                else:
                    task = asyncio.ensure_future(self._answer(msg))
                    self._tasks.add(task)
                    task.add_done_callback(self._tasks.discard)

    # ------------------------------------------------------------- outbound
    def request(self, text: str, context: dict | None = None,
                timeout: float | None = None) -> dict | None:
        """Send a `request`; block for the `reply`. None when the hub is
        unavailable, errored or too slow — the caller then types the text."""
        if not self._ready.is_set() or self._loop is None:
            return None
        msg = protocol.message("request", text=text, context=context or {}, source="voice")
        wait = protocol.timeout_for("request") if timeout is None else timeout
        future = asyncio.run_coroutine_threadsafe(self._send_wait(msg, wait), self._loop)
        try:
            reply = future.result(wait + 1)
        except (concurrent.futures.TimeoutError, Exception) as exc:  # noqa: BLE001
            log.debug("Hub request failed: %s", exc)
            future.cancel()
            return None
        if not reply or reply.get("type") != "reply":
            return None
        return reply

    def request_async(self, text: str, context: dict | None = None) -> None:
        """Fire and forget (e.g. "save this conversation" on the hub too)."""
        if self._ready.is_set() and self._loop is not None:
            msg = protocol.message("request", text=text, context=context or {}, source="voice")
            self._submit(self._send_wait(msg, 10.0))

    def armed(self, on_reply: Callable[[dict], Any]) -> None:
        """Tell the hub a session just armed. A reply with text (the unspoken
        report summary) goes to `on_reply` on a worker thread. Never blocks."""
        if not self._ready.is_set():
            return

        async def go() -> None:
            reply = await self._send_wait(protocol.message("armed"), 5.0)
            if reply and reply.get("type") == "reply" and reply.get("text"):
                await asyncio.get_running_loop().run_in_executor(None, on_reply, reply)

        self._submit(go())

    def _submit(self, coro: Any) -> None:
        """Run `coro` on the link's loop, strongly referenced until done."""
        loop = self._loop

        def spawn() -> None:
            task = asyncio.ensure_future(coro)
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)

        try:
            if loop is None:
                raise RuntimeError("no loop")
            loop.call_soon_threadsafe(spawn)
        except RuntimeError:
            coro.close()

    async def _send_wait(self, msg: dict, wait: float) -> dict | None:
        if self._ws is None:
            return None
        future = asyncio.get_running_loop().create_future()
        self._waiting[msg["id"]] = future
        try:
            await self._ws.send(protocol.encode(msg))
            return await asyncio.wait_for(future, wait)
        except asyncio.TimeoutError:
            return None
        finally:
            self._waiting.pop(msg["id"], None)

    # -------------------------------------------------------------- inbound
    async def _answer(self, msg: dict) -> None:
        reply = await asyncio.get_running_loop().run_in_executor(None, self._handle, msg)
        if reply is not None and self._ws is not None:
            try:
                await self._ws.send(protocol.encode(reply))
            except Exception as exc:  # noqa: BLE001
                log.debug("Could not answer the hub: %s", exc)

    def _handle(self, msg: dict) -> dict | None:
        """Run one hub->Voice Vibe message on a worker thread (may block)."""
        kind = msg["type"]
        try:
            if kind == "ping":
                return protocol.reply_to(msg, "pong")
            if kind == "confirm":
                fn = self._need("confirm")
                result = fn(str(msg.get("prompt", "")),
                            float(msg.get("timeout") or protocol.timeout_for("confirm")))
                if isinstance(result, dict):
                    fields = {"approved": result.get("approved") is True,
                              "answer": str(result.get("answer") or "")}
                    if result.get("unavailable"):
                        # Nobody can hear the question: the hub asks elsewhere.
                        fields["unavailable"] = True
                else:
                    fields = {"approved": result is True, "answer": ""}
                return protocol.reply_to(msg, "confirm_result", **fields)
            if kind == "get_context":
                bundle = self._need("get_context")(bool(msg.get("deep")), msg.get("pin"))
                return protocol.reply_to(msg, "context", **bundle)
            if kind == "list_mics":
                return protocol.reply_to(msg, "mics", **self._need("list_mics")())
            if kind == "set_mic":
                self._need("set_mic")(msg.get("device"))
                return protocol.reply_to(msg, "ok")
            if kind == "transcribe":
                audio = base64.b64decode(msg.get("audio_b64") or "")
                text = self._need("transcribe")(audio, str(msg.get("format", "ogg")))
                return protocol.reply_to(msg, "text", text=text)
            if kind == "run_steps":
                self._need("run_steps")(msg.get("steps") or [], bool(msg.get("dry_run")))
                return protocol.reply_to(msg, "steps_result", ok=True)
            if kind in ("notify", "error", "welcome", "pong"):
                return None
            return protocol.reply_to(msg, "error", message=f"unexpected {kind}", code="unexpected")
        except Exception as exc:  # noqa: BLE001 - report, never crash the link
            log.debug("Hub %s failed: %s", kind, exc)
            if kind == "confirm":  # a broken confirmer is a "no" (rule 10)
                return protocol.reply_to(msg, "confirm_result", approved=False, answer="")
            if kind == "run_steps":
                return protocol.reply_to(msg, "steps_result", ok=False, error=str(exc))
            return protocol.reply_to(msg, "error", message=str(exc), code="failed")

    def _need(self, name: str) -> Callable[..., Any]:
        fn = self.handlers.get(name)
        if fn is None:
            raise LookupError(f"Voice Vibe has no {name} handler")
        return fn
