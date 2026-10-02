"""Control app API (vvhub.ui.api): token on every endpoint, secrets never echoed.

What matters: every /ui/api route answers 401 without the hub token while
the static page (no data) loads without one; secrets go to keyring and no
response ever contains them; service actions are a fixed whitelist; chats
merge hub.db and the history JSONL with retention/saved shown; settings are
validated (syntax, types, never Stereo Mix) before config.toml is replaced;
slow doctor checks are time-limited. Everything external is a fake: no
keyring, registry, processes, network or Notion.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

try:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
except ImportError:  # pragma: no cover
    TestClient = None

from vvhub import secrets  # noqa: E402
from vvhub.store import Store  # noqa: E402

TOKEN = "hub-token-123"
AUTH = {"Authorization": f"Bearer {TOKEN}"}
GOOD_TG = "123456789:AAH" + "x" * 32


class FakeBus:
    def __init__(self, roles=("voicevibe",), replies=None):
        self.roles = set(roles)
        self.replies = replies or {}
        self.sent = []

    def connected(self, role):
        return role in self.roles

    async def send_to(self, role, msg, timeout=None):
        if role not in self.roles:
            from vvhub.bus import NotConnected

            raise NotConnected(role)
        self.sent.append((role, msg))
        reply = self.replies.get(msg["type"], {"type": "ok"})
        return reply(msg) if callable(reply) else reply


class FakePairing:
    def __init__(self, owner=None):
        self.owner = owner
        self.unpaired = False

    def new_code(self):
        return "ABCD2345"

    def unpair(self):
        self.unpaired = True
        self.owner = None


class FakeReg:
    HKEY_CURRENT_USER, KEY_READ, REG_SZ = "HKCU", 1, 1

    def __init__(self):
        self.values = {}

    class _K:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def OpenKey(self, *a):  # noqa: N802
        return self._K()

    def CreateKey(self, *a):  # noqa: N802
        return self._K()

    def QueryValueEx(self, key, name):  # noqa: N802
        if name not in self.values:
            raise FileNotFoundError(name)
        return self.values[name], 1

    def SetValueEx(self, key, name, r, kind, value):  # noqa: N802
        self.values[name] = value

    def DeleteValue(self, key, name):  # noqa: N802
        self.values.pop(name)


CHECKS = [
    {"name": "hub server", "ok": True, "detail": "up", "needs_user": False},
    {"name": "freellmapi", "ok": True, "detail": ":3001 up", "needs_user": False},
    {"name": "freellmapi key", "ok": False, "detail": "missing", "needs_user": True},
    {"name": "opencli", "ok": True, "detail": "1.8.8", "needs_user": False},
    {"name": "opencli edge extension", "ok": False, "detail": "not connected", "needs_user": True},
    {"name": "windows-mcp", "ok": True, "detail": "0.8.5", "needs_user": False},
    {"name": "notion token", "ok": False, "detail": "missing", "needs_user": True},
    {"name": "telegram token", "ok": True, "detail": "set", "needs_user": True},
    {"name": "gh CLI", "ok": True, "detail": "gh.exe", "needs_user": False},
]

SNAPSHOT = {"processes": [
    {"name": "hub", "running": True, "pids": [1, 2], "ram_mb": 180.5, "ws_mb": 250.0, "cpu_pct": 0.4},
    {"name": "voicevibe", "running": True, "pids": [3], "ram_mb": 700.0, "ws_mb": 800.0, "cpu_pct": 1.0},
    {"name": "bot", "running": False, "pids": [], "ram_mb": 0.0, "ws_mb": 0.0, "cpu_pct": 0.0},
], "total_ram_mb": 880.5}


@unittest.skipIf(TestClient is None, "fastapi not installed")
class ApiTestCase(unittest.TestCase):
    def setUp(self):
        from vvhub.ui import api

        self.api = api
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name)
        self._old_home = os.environ.get("VVHUB_HOME")
        os.environ["VVHUB_HOME"] = str(self.home)
        self.vault: dict = {}
        secrets.use_backend(self.vault)
        self.opened: list = []
        self.spawned: list = []
        self.pairing = FakePairing()
        self.reg = FakeReg()
        self.config = self.home / "config.toml"
        self.config.write_text('[control]\nenabled = true\n\n[audio]\ninput_priority = ["Microphone Array"]\n',
                               encoding="utf-8")
        self.store = Store(":memory:")
        self.bus = FakeBus(replies={
            "list_mics": {"type": "mics", "devices": ["Microphone Array (Realtek)", "Headset"],
                          "current": "Microphone Array (Realtek)"},
            "set_mic": lambda m: {"type": "ok", "device": m["device"]},
        })
        self.hub = SimpleNamespace(token=TOKEN, store=self.store, bus=self.bus, skills={}, components={})
        self.checks_calls = 0

        def run_checks():
            self.checks_calls += 1
            return [dict(c) for c in CHECKS]

        class Notion:
            async def layout(inner):
                return {"root": "r", "Notes": "n", "Transcripts": "t", "Research": "s", "Reports": "p"}

        self.deps = api.UIDeps(
            config_path=self.config, run_checks=run_checks, snapshot=lambda: SNAPSHOT,
            open_target=lambda kind, target: self.opened.append((kind, target)),
            spawn=lambda argv, cwd=None, env=None: self.spawned.append(argv) or 99,
            registry=self.reg, pairing=lambda: self.pairing, notion=lambda: Notion(),
            gh_status=lambda: (True, "Logged in to github.com account Sndcooper"),
            bot_python=Path(sys.executable))
        app = FastAPI()
        app.state.hub = self.hub
        api.install(app, deps=self.deps)
        self.app = app
        self.client = TestClient(app)

    def tearDown(self):
        secrets.use_backend(None)
        self.store.close()
        if self._old_home is None:
            os.environ.pop("VVHUB_HOME", None)
        else:
            os.environ["VVHUB_HOME"] = self._old_home
        self.tmp.cleanup()

    def get(self, path, **kw):
        return self.client.get(path, headers=AUTH, **kw)


class AuthTests(ApiTestCase):
    def test_every_api_route_needs_the_token(self):
        # FastAPI 0.142 wraps included routers, so walk the API router itself.
        routes = [r for r in self.api.router.routes if getattr(r, "path", "").startswith("/ui/api")]
        self.assertGreater(len(routes), 15)
        for route in routes:
            path = route.path.replace("{cid:path}", "hub/x").replace("{name}", "x").replace(
                "{card}", "x").replace("{action}", "y")
            for method in route.methods - {"HEAD"}:
                for headers in ({}, {"Authorization": "Bearer wrong"}, {"Authorization": TOKEN}):
                    r = self.client.request(method, path, headers=headers, json={})
                    self.assertEqual(r.status_code, 401, f"{method} {path} {headers}")

    def test_static_page_is_public_and_carries_no_token_or_data(self):
        r = self.client.get("/ui/")
        self.assertEqual(r.status_code, 200)
        self.assertIn("text/html", r.headers["content-type"])
        self.assertIn("Voice Vibe", r.text)
        self.assertNotIn(TOKEN, r.text)
        self.assertEqual(self.client.get("/ui/static/app.js").status_code, 200)
        self.assertEqual(self.client.get("/ui/static/vendor/pico.min.css").status_code, 200)
        for bad in ("/ui/static/../api.py", "/ui/static/..%2Fapi.py", "/ui/static/nope.js"):
            self.assertEqual(self.client.get(bad).status_code, 404, bad)


class StatusTests(ApiTestCase):
    def test_status(self):
        today = time.time()
        self.store.add_turn("user", "open notepad", data={"source": "voice"}, ts=today)
        self.store.add_turn("user", "check github", data={"source": "telegram"}, ts=today)
        self.store.add_turn("hub", "Done.", ts=today)
        self.store.add_decision("open notepad", {"category": "app", "needs_approval": False}, ts=today)
        self.store.add_decision("push it", {"category": "github", "needs_approval": True}, ts=today)
        self.store.add_decision("yesterday", {"category": "app"}, ts=today - 3 * 86400)
        self.store.add_approval({"id": "a1", "action": "push", "preview": "Push", "status": "approved",
                                 "created": today})
        body = self.get("/ui/api/status").json()
        self.assertTrue(body["hub"]["ok"])
        self.assertEqual(body["connected"], {"voicevibe": True, "bot": False, "ui": False})
        self.assertEqual(body["today"]["requests"], 2)
        self.assertEqual(body["today"]["by_source"], {"voice": 1, "telegram": 1})
        self.assertEqual((body["today"]["auto"], body["today"]["asked"]), (1, 1))
        self.assertEqual(body["today"]["approvals"]["approved"], 1)
        self.assertEqual(body["processes"][0]["name"], "hub")
        self.assertEqual(body["total_ram_mb"], 880.5)
        self.assertEqual(self.checks_calls, 0)  # status never waits for doctor


class ServicesTests(ApiTestCase):
    def test_cards_from_doctor_checks(self):
        body = self.get("/ui/api/services", params={"refresh": 1}).json()
        cards = {c["id"]: c for c in body["cards"]}
        self.assertEqual(set(cards), {"freellmapi", "edge", "notion", "telegram", "github", "linkedin",
                                      "instagram"})
        self.assertEqual(cards["freellmapi"]["status"], "user")
        self.assertEqual(cards["github"]["status"], "ok")
        self.assertIn("Sndcooper", cards["github"]["detail"])
        self.assertEqual(cards["telegram"]["secret"], "telegram_bot_token")
        self.assertFalse(cards["telegram"]["paired"])
        self.assertTrue(body["checks"])
        # Cached: a plain GET doesn't re-run the checks.
        self.get("/ui/api/services")
        self.assertEqual(self.checks_calls, 1)

    def test_checks_have_a_time_limit(self):
        self.deps.run_checks = lambda: time.sleep(2) or []
        self.deps.check_timeout = 0.2
        started = time.monotonic()
        body = self.get("/ui/api/services", params={"refresh": 1}).json()
        self.assertLess(time.monotonic() - started, 1.5)
        self.assertIn("timed out", body["error"])

    def test_actions_are_whitelisted(self):
        r = self.client.post("/ui/api/services/linkedin/open_linkedin", headers=AUTH)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.opened, [("edge", "https://www.linkedin.com/login")])
        self.assertEqual(self.client.post("/ui/api/services/linkedin/rm_rf", headers=AUTH).status_code, 404)
        self.assertEqual(self.client.post("/ui/api/services/nope/open_linkedin", headers=AUTH).status_code, 404)

    def test_telegram_pair_and_unpair(self):
        body = self.client.post("/ui/api/services/telegram/telegram_pair", headers=AUTH).json()
        self.assertEqual(body["code"], "ABCD2345")
        self.assertIn("/pair ABCD2345", body["message"])
        self.pairing.owner = 555
        body = self.client.post("/ui/api/services/telegram/telegram_pair", headers=AUTH).json()
        self.assertNotIn("code", body)
        self.assertIn("already paired", body["message"].lower())
        self.client.post("/ui/api/services/telegram/telegram_unpair", headers=AUTH)
        self.assertTrue(self.pairing.unpaired)

    def test_telegram_start_needs_token(self):
        body = self.client.post("/ui/api/services/telegram/telegram_start", headers=AUTH).json()
        self.assertFalse(body["ok"])
        self.assertEqual(self.spawned, [])
        self.vault["telegram_bot_token"] = GOOD_TG
        body = self.client.post("/ui/api/services/telegram/telegram_start", headers=AUTH).json()
        self.assertTrue(body["ok"], body)
        self.assertEqual(self.spawned[0][1:], ["-m", "vvbot"])

    def test_notion_setup(self):
        body = self.client.post("/ui/api/services/notion/notion_setup", headers=AUTH).json()
        self.assertTrue(body["ok"])
        self.assertIn("Reports", body["message"])


class SecretTests(ApiTestCase):
    def test_set_status_delete_never_echoed(self):
        value = "ntn_" + "s3cr3t" * 8
        r = self.client.post("/ui/api/secrets/notion_token", headers=AUTH, json={"value": value})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.vault["notion_token"], value)
        for path in ("/ui/api/secrets", "/ui/api/services", "/ui/api/status"):
            self.assertNotIn("s3cr3t", self.get(path).text, path)
        self.assertNotIn("s3cr3t", r.text)
        self.assertEqual(self.get("/ui/api/secrets").json()["notion_token"], True)
        self.client.delete("/ui/api/secrets/notion_token", headers=AUTH)
        self.assertNotIn("notion_token", self.vault)

    def test_unknown_or_malformed(self):
        self.assertEqual(self.client.post("/ui/api/secrets/hub_token", headers=AUTH,
                                          json={"value": "x"}).status_code, 404)
        for name, value in (("telegram_bot_token", "not a token"), ("notion_token", "abc"),
                            ("freellmapi_key", ""), ("freellmapi_key", "a b"), ("freellmapi_key", "x" * 5000)):
            r = self.client.post(f"/ui/api/secrets/{name}", headers=AUTH, json={"value": value})
            self.assertEqual(r.status_code, 422, (name, value))
            self.assertNotIn(value or "@@", r.text)
        self.assertEqual(self.vault, {})


class ChatTests(ApiTestCase):
    def setUp(self):
        super().setUp()
        now = time.time()
        self.store.add_turn("user", "note this: buy milk", conversation="c1", data={"source": "voice"}, ts=now)
        self.store.add_turn("hub", "Noted.", conversation="c1", ts=now + 1)
        self.store.add_turn("user", "research laya onnx", conversation="c2", ts=now - 3600)
        self.store.save_conversation("c2", "Laya research")
        hist = self.home / "history"
        (hist / "saved").mkdir(parents=True)
        day = datetime.now().strftime("%Y-%m-%d")
        rec = {"ts": datetime.now().isoformat(timespec="seconds"), "action": "dictate",
               "heard": "hello from dictation", "spoken": ""}
        (hist / f"{day}.jsonl").write_text(json.dumps(rec) + "\n", encoding="utf-8")
        (hist / "saved" / "2026-01-02.jsonl").write_text(
            json.dumps({"ts": "2026-01-02T10:00:00", "action": "command", "heard": "open blender"}) + "\n",
            encoding="utf-8")
        self.day = day

    def test_list_merges_sources_with_retention(self):
        body = self.get("/ui/api/chats").json()
        self.assertEqual(body["retention_days"], 2)
        items = {i["id"]: i for i in body["items"]}
        self.assertTrue({"hub/c1", "hub/c2", f"history/{self.day}", "saved/2026-01-02"} <= set(items))
        self.assertFalse(items["hub/c1"]["saved"])
        self.assertIsNotNone(items["hub/c1"]["expires"])
        self.assertTrue(items["hub/c2"]["saved"])
        self.assertIsNone(items["hub/c2"]["expires"])
        self.assertEqual(items["hub/c2"]["title"], "Laya research")
        self.assertTrue(items["saved/2026-01-02"]["saved"])

    def test_search(self):
        hits = self.get("/ui/api/chats", params={"q": "milk"}).json()["matches"]
        self.assertEqual([h["id"] for h in hits], ["hub/c1"])
        hits = self.get("/ui/api/chats", params={"q": "BLENDER"}).json()["matches"]
        self.assertEqual([h["id"] for h in hits], ["saved/2026-01-02"])
        hits = self.get("/ui/api/chats", params={"q": "100%_"}).json()["matches"]
        self.assertEqual(hits, [])

    def test_read_save_export(self):
        chat = self.get("/ui/api/chats/hub/c1").json()
        self.assertEqual([t["text"] for t in chat["turns"]], ["note this: buy milk", "Noted."])
        r = self.client.post("/ui/api/chats/hub/c1/save", headers=AUTH, json={"title": "Milk"})
        self.assertTrue(r.json()["ok"])
        self.assertTrue(self.store.is_saved("c1"))
        r = self.client.post(f"/ui/api/chats/history/{self.day}/save", headers=AUTH, json={})
        self.assertTrue(r.json()["ok"])
        self.assertTrue((self.home / "history" / "saved" / f"{self.day}.jsonl").exists())
        md = self.get("/ui/api/chats/hub/c1/export", params={"format": "md"}).json()
        self.assertTrue(md["filename"].endswith(".md"))
        self.assertIn("note this: buy milk", md["text"])
        js = self.get("/ui/api/chats/hub/c1/export", params={"format": "json"}).json()
        self.assertEqual(json.loads(js["text"])["turns"][1]["text"], "Noted.")

    def test_bad_ids(self):
        for cid in ("history/../../x", "saved/..%5Cx", "other/c1", "hub/nope"):
            self.assertEqual(self.get(f"/ui/api/chats/{cid}").status_code, 404, cid)


class FilesTests(ApiTestCase):
    def test_logs_tail_filter_and_names(self):
        logs = self.home / "logs"
        logs.mkdir()
        (logs / "vvhub.log").write_text("\n".join(f"line {i} {'ERROR' if i % 2 else 'INFO'}" for i in range(10)),
                                        encoding="utf-8")
        body = self.get("/ui/api/logs", params={"name": "vvhub", "lines": 2}).json()
        self.assertEqual(body["lines"], ["line 8 INFO", "line 9 ERROR"])
        self.assertIn("vvhub", body["names"])
        body = self.get("/ui/api/logs", params={"name": "vvhub", "q": "error"}).json()
        self.assertEqual(len(body["lines"]), 5)
        self.assertEqual(self.get("/ui/api/logs", params={"name": "../config"}).status_code, 404)

    def test_reports(self):
        rep = self.home / "reports"
        rep.mkdir()
        (rep / "2026-09-30-0800.html").write_text("<h1>Morning report</h1>", encoding="utf-8")
        (rep / "notes.txt").write_text("x", encoding="utf-8")
        items = self.get("/ui/api/reports").json()["items"]
        self.assertEqual([i["name"] for i in items], ["2026-09-30-0800.html"])
        self.assertIn("Morning report", self.get("/ui/api/reports/2026-09-30-0800.html").json()["html"])
        self.assertEqual(self.get("/ui/api/reports/..%5Cconfig.toml").status_code, 404)


class MicTests(ApiTestCase):
    def test_list_and_set(self):
        body = self.get("/ui/api/mics").json()
        self.assertEqual(body["current"], "Microphone Array (Realtek)")
        r = self.client.post("/ui/api/mics", headers=AUTH, json={"device": "Headset"})
        self.assertTrue(r.json()["ok"])
        self.assertEqual(self.bus.sent[-1][1]["device"], "Headset")

    def test_voicevibe_not_running(self):
        self.bus.roles = set()
        r = self.get("/ui/api/mics")
        self.assertEqual(r.status_code, 503)
        self.assertIn("Voice Vibe", r.json()["detail"])


class SettingsTests(ApiTestCase):
    def put(self, text):
        return self.client.put("/ui/api/settings", headers=AUTH, json={"text": text})

    def test_get(self):
        body = self.get("/ui/api/settings").json()
        self.assertIn("[control]", body["text"])
        self.assertEqual(body["errors"], [])

    def test_rejects_bad_toml_types_and_stereo_mix(self):
        before = self.config.read_text(encoding="utf-8")
        for text in ("[control\nenabled = true", "[control]\nenabled = \"yes\"",
                     '[audio]\ninput_priority = ["Stereo Mix (Realtek)"]', "[audio]\ninput_priority = 3"):
            r = self.put(text)
            self.assertEqual(r.status_code, 422, text)
            self.assertTrue(r.json()["detail"]["errors"], text)
        self.assertEqual(self.config.read_text(encoding="utf-8"), before)

    def test_saves_with_backup_and_warns_on_unknown(self):
        text = "[control]\nenabled = false\nmystery = 1\n\n[continuous]\npartials = false\n"
        r = self.put(text)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertTrue(any("mystery" in w for w in r.json()["warnings"]))
        self.assertEqual(self.config.read_text(encoding="utf-8"), text)
        self.assertIn("enabled = true", (self.home / "config.toml.bak").read_text(encoding="utf-8"))

    def test_validate_only(self):
        r = self.client.post("/ui/api/settings/validate", headers=AUTH, json={"text": "[x\n"})
        self.assertTrue(r.json()["errors"])
        self.assertEqual(self.config.read_text(encoding="utf-8").count("enabled = true"), 1)

    def test_autostart(self):
        self.assertFalse(self.get("/ui/api/autostart").json()["enabled"])
        self.client.put("/ui/api/autostart", headers=AUTH, json={"enabled": True})
        self.assertTrue(self.get("/ui/api/autostart").json()["enabled"])
        self.assertEqual(list(self.reg.values), ["VoiceVibe"])


class ApprovalTests(ApiTestCase):
    def test_pending_and_recent(self):
        now = time.time()
        self.store.add_approval({"id": "p1", "action": "push", "preview": "Push feature/x", "channel": "telegram",
                                 "status": "pending", "created": now})
        self.store.add_approval({"id": "d1", "action": "post", "preview": "Post to LinkedIn", "status": "denied",
                                 "created": now - 10})
        body = self.get("/ui/api/approvals").json()
        self.assertEqual([a["id"] for a in body["pending"]], ["p1"])
        self.assertEqual([a["id"] for a in body["recent"]], ["p1", "d1"])
        self.assertFalse(body["ui_connected"])


@unittest.skipIf(TestClient is None, "fastapi not installed")
class ServerIncludeTests(unittest.TestCase):
    def test_create_app_serves_the_ui(self):
        from vvhub.server import Hub, create_app

        hub = Hub(token=TOKEN, store=Store(":memory:"))
        client = TestClient(create_app(hub))
        self.assertEqual(client.get("/ui/api/autostart").status_code, 401)
        self.assertEqual(client.get("/ui/").status_code, 200)


if __name__ == "__main__":
    unittest.main()
