"""Voice Vibe <-> vvhub link (hub_client.py).

The round-trip tests start the real hub (uvicorn, in-memory store, temp token)
on a free localhost port. Nothing touches the desktop, the mic or real data.
"""

from __future__ import annotations

import asyncio
import socket
import threading
import time
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

import stubs

stubs.install()

from voicevibe.hub_client import HubClient  # noqa: E402
from vvhub import protocol  # noqa: E402

try:
    import uvicorn
    import websockets  # noqa: F401

    from vvhub.server import Hub, create_app
    from vvhub.store import Store
except ImportError:
    uvicorn = None


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait(predicate, timeout: float = 5.0) -> bool:  # noqa: ANN001
    end = time.time() + timeout
    while time.time() < end:
        if predicate():
            return True
        time.sleep(0.02)
    return False


@unittest.skipIf(uvicorn is None, "hub dependencies not installed")
class LiveHubTests(unittest.TestCase):
    """A real hub on 127.0.0.1:<free port> for the whole class."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.port = _free_port()
        cls.hub = Hub(token="t0ken", store=Store(), bus=_LoopBus())
        config = uvicorn.Config(create_app(cls.hub), host="127.0.0.1", port=cls.port,
                                log_level="error", lifespan="on")
        cls.server = uvicorn.Server(config)
        cls.thread = threading.Thread(target=cls.server.run, daemon=True)
        cls.thread.start()
        assert _wait(lambda: cls.server.started, 10), "hub did not start"

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.should_exit = True
        cls.thread.join(5)

    def client(self, token: str = "t0ken", handlers: dict | None = None) -> HubClient:
        c = HubClient(handlers, url=f"ws://127.0.0.1:{self.port}/ws", token=lambda: token)
        c.start()
        self.addCleanup(c.stop)
        return c

    def test_ping_hub_round_trip(self) -> None:
        c = self.client()
        self.assertTrue(_wait(lambda: c.connected))
        reply = c.request("ping hub", {"window": {"title": "x"}})
        self.assertEqual(reply["text"], "Hub is online.")
        self.assertTrue(reply["handled"])

    def test_not_handled_reply_passes_through(self) -> None:
        # The hub's "not a hub task" answer must reach the app as handled=False.
        # (Routing real text needs WS2's Laya; that is tested in its own suite.)
        from vvhub import dispatch

        c = self.client()
        self.assertTrue(_wait(lambda: c.connected))
        original = dispatch._decide_and_run

        async def not_mine(hub, text, context, conversation):  # noqa: ANN001
            return dispatch.NOT_HANDLED

        dispatch._decide_and_run = not_mine
        self.addCleanup(setattr, dispatch, "_decide_and_run", original)
        reply = c.request("draft the meeting notes about tuesday")
        self.assertFalse(reply["handled"])

    def test_bad_token_never_connects(self) -> None:
        c = self.client(token="wrong")
        time.sleep(0.5)
        self.assertFalse(c.connected)
        self.assertIsNone(c.request("ping hub"))

    def test_hub_can_ask_for_confirmation(self) -> None:
        confirm = Mock(return_value=True)
        c = self.client(handlers={"confirm": confirm})
        self.assertTrue(_wait(lambda: c.connected and self.hub.bus.connected("voicevibe")))

        async def ask() -> dict:
            return await self.hub.bus.send_to(
                "voicevibe", protocol.message("confirm", prompt="Post it?", timeout=3))

        future = asyncio.run_coroutine_threadsafe(ask(), self._server_loop())
        reply = future.result(5)
        self.assertTrue(reply["approved"])
        confirm.assert_called_once_with("Post it?", 3.0)

    def _server_loop(self) -> asyncio.AbstractEventLoop:
        return self.hub.bus.loop


if uvicorn is not None:
    from vvhub.bus import Bus

    class _LoopBus(Bus):
        """Remembers the server's event loop so the test can schedule on it."""

        loop: asyncio.AbstractEventLoop | None = None

        def attach(self, role, send):  # noqa: ANN001
            self.loop = asyncio.get_running_loop()
            super().attach(role, send)
else:
    _LoopBus = None


class ReconnectTests(unittest.TestCase):
    """The link must survive the hub going away and coming back.

    Regression: the reconnect task was only weakly referenced, so garbage
    collection during the backoff sleep deleted it and the link never returned.
    """

    @unittest.skipIf(uvicorn is None, "hub dependencies not installed")
    def test_reconnects_after_hub_restart(self) -> None:
        import gc

        import voicevibe.hub_client as hc

        port = _free_port()

        def serve() -> tuple:
            server = uvicorn.Server(uvicorn.Config(
                create_app(Hub(token="k", store=Store())), host="127.0.0.1", port=port,
                log_level="error", lifespan="on"))
            thread = threading.Thread(target=server.run, daemon=True)
            thread.start()
            assert _wait(lambda: server.started, 10)
            return server, thread

        old_start, old_max = hc.BACKOFF_START, hc.BACKOFF_MAX
        hc.BACKOFF_START, hc.BACKOFF_MAX = 0.1, 0.3
        self.addCleanup(setattr, hc, "BACKOFF_START", old_start)
        self.addCleanup(setattr, hc, "BACKOFF_MAX", old_max)

        server, thread = serve()
        client = HubClient(url=f"ws://127.0.0.1:{port}/ws", token=lambda: "k").start()
        self.addCleanup(client.stop)
        self.assertTrue(_wait(lambda: client.connected))

        server.should_exit = True
        thread.join(5)
        self.assertTrue(_wait(lambda: not client.connected))
        for _ in range(5):
            gc.collect()
            time.sleep(0.05)

        server, thread = serve()
        self.addCleanup(thread.join, 5)
        self.addCleanup(setattr, server, "should_exit", True)
        self.assertTrue(_wait(lambda: client.connected, 5), "link did not come back")
        self.assertEqual(client.request("ping hub")["text"], "Hub is online.")


class OfflineTests(unittest.TestCase):
    def test_no_hub_returns_none_immediately(self) -> None:
        c = HubClient(url=f"ws://127.0.0.1:{_free_port()}/ws", token=lambda: "x")
        c.start()
        self.addCleanup(c.stop)
        started = time.time()
        self.assertIsNone(c.request("ping hub"))
        self.assertLess(time.time() - started, 0.5)
        self.assertFalse(c.connected)

    def test_handlers_map_to_replies(self) -> None:
        c = HubClient({"confirm": lambda p, t: True,
                       "get_context": lambda deep, pin=None: {"pinned": deep},
                       "run_steps": Mock(side_effect=ValueError("bad step"))})
        ok = c._handle(protocol.message("confirm", prompt="?", timeout=2))
        self.assertEqual((ok["type"], ok["approved"]), ("confirm_result", True))
        ctx = c._handle(protocol.message("get_context", deep=True))
        self.assertTrue(ctx["pinned"])
        steps = c._handle(protocol.message("run_steps", steps=[{"keys": "x"}]))
        self.assertEqual((steps["ok"], steps["error"]), (False, "bad step"))
        missing = c._handle(protocol.message("list_mics"))
        self.assertEqual(missing["type"], "error")

    def test_broken_confirmer_means_no(self) -> None:
        c = HubClient({"confirm": Mock(side_effect=RuntimeError("mic gone"))})
        reply = c._handle(protocol.message("confirm", prompt="Push?"))
        self.assertFalse(reply["approved"])


class AppFallbackTests(unittest.TestCase):
    def make(self, reply):  # noqa: ANN001, ANN201
        from voicevibe import app

        vv = app.VoiceVibe.__new__(app.VoiceVibe)
        vv.hub = SimpleNamespace(connected=True, request=Mock(return_value=reply))
        vv.context = SimpleNamespace(bundle=lambda: {"pinned": False})
        vv.router = Mock()
        vv.history, vv.overlay, vv.airoot, vv.beeper, vv.voice = (Mock() for _ in range(5))
        return vv

    def test_handled_reply_is_spoken(self) -> None:
        vv = self.make({"type": "reply", "text": "Hub is online.", "speak": True,
                        "handled": True, "ok": True})
        self.assertTrue(vv._do_hub("ping hub", "computer ping hub", 0.1))
        vv.voice.say.assert_called_once_with("Hub is online.")

    def test_not_handled_or_down_falls_back_to_typing(self) -> None:
        for reply in (None, {"type": "reply", "text": "", "handled": False}):
            vv = self.make(reply)
            self.assertFalse(vv._do_hub("draft notes", "computer draft notes", 0.1))
            vv.voice.say.assert_not_called()
        vv = self.make(None)
        vv.hub.connected = False
        self.assertFalse(vv._do_hub("x", "computer x", 0.1))
        vv.hub.request.assert_not_called()

    def test_no_hub_at_all(self) -> None:
        from voicevibe import app

        vv = app.VoiceVibe.__new__(app.VoiceVibe)
        self.assertIsNone(vv.hub)
        self.assertFalse(vv._do_hub("x", "computer x", 0.1))


if __name__ == "__main__":
    unittest.main()
