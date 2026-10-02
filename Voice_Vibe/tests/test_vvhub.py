"""vvhub skeleton: auth, protocol, bus, dispatch safety floor, doctor.

No network beyond the in-process TestClient, no real keyring.
"""

from __future__ import annotations

import asyncio
import os
import tempfile
import unittest

import stubs

stubs.install()

from vvhub import dispatch, doctor, protocol  # noqa: E402
from vvhub.bus import Bus, NotConnected  # noqa: E402
from vvhub.schemas import Decision, Plan, Result, is_critical  # noqa: E402
from vvhub.skills.base import Skill  # noqa: E402
from vvhub.store import Store, today_conversation  # noqa: E402

try:
    from fastapi.testclient import TestClient
    from starlette.websockets import WebSocketDisconnect

    from vvhub.server import Hub, create_app, load_or_create_token
except ImportError:  # hub dependencies not installed
    TestClient = None


class SchemaTests(unittest.TestCase):
    def test_critical_words(self) -> None:
        for action in ("post", "linkedin_post", "git_push", "create_repo", "open_pr",
                       "send_message", "delete-file", "pay"):
            self.assertTrue(is_critical(action), action)
        for action in ("open", "research", "note", "ping", "scroll", "postpone_note"):
            self.assertFalse(is_critical(action), action)

    def test_plan_cannot_unmark_critical(self) -> None:
        self.assertTrue(Plan(skill="social", action="instagram_post", critical=False).critical)

    def test_round_trip_ignores_unknown_keys(self) -> None:
        d = Decision.from_dict({"category": "research", "action": "x", "extra": 1})
        self.assertEqual(d.category, "research")
        self.assertEqual(Decision.from_dict(d.to_dict()), d)


class ProtocolTests(unittest.TestCase):
    def test_reply_links_to_request(self) -> None:
        req = protocol.message("request", text="hi")
        rep = protocol.reply_to(req, "reply", text="ok")
        self.assertEqual(rep["re"], req["id"])
        self.assertEqual(protocol.decode(protocol.encode(rep)), rep)

    def test_rejects_bad_messages(self) -> None:
        for raw in ("not json", "[]", '{"type": "nope", "id": "1"}', '{"type": "ping"}'):
            with self.assertRaises(protocol.ProtocolError):
                protocol.decode(raw)
        with self.assertRaises(protocol.ProtocolError):
            protocol.message("nope")


class BusTests(unittest.TestCase):
    def test_send_waits_for_reply(self) -> None:
        async def go() -> dict:
            bus = Bus()

            async def send(msg: dict) -> None:
                asyncio.get_running_loop().call_soon(
                    bus.deliver, protocol.reply_to(msg, "confirm_result", approved=True))

            bus.attach("voicevibe", send)
            return await bus.send_to("voicevibe", protocol.message("confirm", prompt="?"))

        self.assertTrue(asyncio.run(go())["approved"])

    def test_not_connected_and_timeout(self) -> None:
        async def go() -> None:
            bus = Bus()
            with self.assertRaises(NotConnected):
                await bus.send_to("bot", protocol.message("ping"))

            async def silent(msg: dict) -> None:
                return None

            bus.attach("bot", silent)
            with self.assertRaises(asyncio.TimeoutError):
                await bus.send_to("bot", protocol.message("ping"), timeout=0.05)
            self.assertFalse(bus.deliver({"re": "unknown"}))

        asyncio.run(go())


class _CriticalSkill(Skill):
    name = "danger"
    category = "social"
    actions = {"post": "post something"}
    phrases = {"post it": "post"}

    def __init__(self) -> None:
        super().__init__()
        self.ran = False

    async def run(self, plan, approval=None, dry_run=False):  # noqa: ANN001
        self.ran = True
        return Result(ok=True, text="posted")


class _FakeHub:
    def __init__(self, skills: dict) -> None:
        self.store = Store()
        self.skills = skills
        self.bus = Bus()


class DispatchTests(unittest.TestCase):
    def test_unknown_text_is_not_handled(self) -> None:
        # With no smart_router module yet, nothing is swallowed (rule 8).
        hub = _FakeHub({})
        if dispatch._optional("smart_router") is not None:
            self.skipTest("smart_router present; covered by WS2 tests")
        result = asyncio.run(dispatch.handle(hub, "draft the meeting notes"))
        self.assertFalse(result.data.get("handled", True))

    def test_critical_without_approvals_is_refused(self) -> None:
        if dispatch._optional("approvals") is not None:
            self.skipTest("approvals present; covered by WS2 tests")
        skill = _CriticalSkill()
        hub = _FakeHub({"danger": skill})
        result = asyncio.run(dispatch.handle(hub, "Post it!"))
        self.assertFalse(result.ok)
        self.assertFalse(skill.ran)
        self.assertEqual(len(hub.store.decisions()), 1)

    def test_phrase_normalization(self) -> None:
        self.assertEqual(dispatch.normalize("  Ping, the HUB! "), "ping the hub")


class DoctorTests(unittest.TestCase):
    def test_render_and_errors(self) -> None:
        def boom() -> tuple[bool, str]:
            raise RuntimeError("broken")

        checks = [doctor.Check("good", lambda: (True, "fine")),
                  doctor.Check("bad", boom),
                  doctor.Check("account", lambda: (False, "not linked"), needs_user=True)]
        results = doctor.run_checks(checks)
        self.assertEqual([ok for _, ok, _ in results], [True, False, False])
        text = doctor.render(results)
        self.assertIn("OK    good", text)
        self.assertIn("FAIL  bad", text)
        self.assertIn("RuntimeError: broken", text)
        self.assertIn("USER  account", text)

    def test_missing_command(self) -> None:
        ok, detail = doctor.command_ok(["definitely-not-a-real-command-xyz"])
        self.assertFalse(ok)
        self.assertIn("not on PATH", detail)


@unittest.skipIf(TestClient is None, "hub dependencies (fastapi) not installed")
class ServerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        old = os.environ.get("VVHUB_HOME")
        os.environ["VVHUB_HOME"] = self.tmp.name
        self.addCleanup(lambda: os.environ.__setitem__("VVHUB_HOME", old) if old
                        else os.environ.pop("VVHUB_HOME", None))
        self.hub = Hub(token="secret-token", store=Store())
        self.client = TestClient(create_app(self.hub))

    def test_health_requires_token(self) -> None:
        self.assertEqual(self.client.get("/health").status_code, 401)
        bad = self.client.get("/health", headers={"Authorization": "Bearer wrong"})
        self.assertEqual(bad.status_code, 401)
        good = self.client.get("/health", headers={"Authorization": "Bearer secret-token"})
        self.assertEqual(good.status_code, 200)
        self.assertIn("echo", good.json()["skills"])

    def test_ws_rejects_bad_token(self) -> None:
        with self.client.websocket_connect("/ws") as ws:
            ws.send_text(protocol.encode(protocol.message(
                "hello", token="wrong", role="voicevibe")))
            with self.assertRaises(WebSocketDisconnect) as caught:
                ws.receive_text()
        self.assertEqual(caught.exception.code, protocol.CLOSE_UNAUTHORIZED)

    def test_ws_ping_hub_round_trip(self) -> None:
        with self.client.websocket_connect("/ws") as ws:
            ws.send_text(protocol.encode(protocol.message(
                "hello", token="secret-token", role="voicevibe")))
            self.assertEqual(protocol.decode(ws.receive_text())["type"], "welcome")
            req = protocol.message("request", text="ping hub", context={})
            ws.send_text(protocol.encode(req))
            rep = protocol.decode(ws.receive_text())
        self.assertEqual(rep["re"], req["id"])
        self.assertEqual(rep["text"], "Hub is online.")
        self.assertTrue(rep["handled"])
        roles = [t["role"] for t in self.hub.store.turns(today_conversation())]
        self.assertEqual(roles, ["user", "hub"])

    def test_token_file_created_once(self) -> None:
        first = load_or_create_token()
        self.assertEqual(load_or_create_token(), first)
        self.assertGreaterEqual(len(first), 32)


if __name__ == "__main__":
    unittest.main()
