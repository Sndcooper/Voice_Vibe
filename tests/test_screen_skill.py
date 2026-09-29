"""vvhub.skills.screen: focus pin and reading, through Voice Vibe's context.

Fake bus returns canned bundles; Windows-MCP is a fake tool caller.
"""

from __future__ import annotations

import asyncio
import unittest

import stubs

stubs.install()

from vvhub.schemas import Decision  # noqa: E402
from vvhub.skills.screen import ScreenSkill, fetch_context  # noqa: E402


def run(coro):  # noqa: ANN001, ANN201
    return asyncio.run(coro)


BUNDLE = {"window": {"hwnd": 5, "title": "app.py - VS Code", "process": "Code.exe"},
          "caret_text": "", "selection": "",
          "region": {"rect": [0, 0, 800, 500], "ocr_text": "KeyError: 'name'\n  line 3",
                     "image_ref": None},
          "pinned": False, "redacted": False}


class FakeBus:
    def __init__(self, bundle: dict | None = None, up: bool = True, wrap: bool = True) -> None:
        self.bundle, self.up, self.wrap = bundle, up, wrap
        self.sent: list[dict] = []

    def connected(self, role: str) -> bool:
        return self.up and role == "voicevibe"

    async def send_to(self, role, msg, timeout=None):  # noqa: ANN001, ANN201
        self.sent.append(msg)
        bundle = dict(self.bundle or BUNDLE)
        if msg.get("pin") is True:
            bundle["pinned"] = True
        if msg.get("pin") is False:
            bundle["pinned"] = False
        if self.wrap:
            return {"type": "context", "re": msg["id"], "context": bundle}
        return {"type": "context", "re": msg["id"], **bundle}


class FakeHub:
    def __init__(self, bus: FakeBus) -> None:
        self.bus, self.skills, self.store = bus, {}, None


def skill(bus: FakeBus, mcp=None) -> ScreenSkill:  # noqa: ANN001
    s = ScreenSkill(mcp=mcp)
    s.bind(FakeHub(bus))
    return s


class FetchTests(unittest.TestCase):
    def test_wrapped_and_flat_replies(self) -> None:
        for wrap in (True, False):
            bus = FakeBus(wrap=wrap)
            got = run(fetch_context(FakeHub(bus), deep=True))
            self.assertEqual(got["window"]["process"], "Code.exe")
            self.assertEqual(bus.sent[-1]["type"], "get_context")
            self.assertTrue(bus.sent[-1]["deep"])
            self.assertNotIn("pin", bus.sent[-1])

    def test_offline_gives_none(self) -> None:
        self.assertIsNone(run(fetch_context(FakeHub(FakeBus(up=False)))))


class FocusTests(unittest.TestCase):
    def test_actions(self) -> None:
        s = ScreenSkill()
        self.assertEqual(s.category, "screen")
        self.assertTrue({"focus", "unfocus", "read"} <= set(s.actions))
        self.assertFalse(s.critical_actions)

    def test_focus_and_unfocus_send_pin(self) -> None:
        bus = FakeBus()
        s = skill(bus)
        result = run(s.run(run(s.plan(Decision(category="screen", action="focus"), {}))))
        self.assertTrue(result.ok)
        self.assertIs(bus.sent[-1]["pin"], True)
        self.assertIn("Focused", result.text)
        result = run(s.run(run(s.plan(Decision(category="screen", action="unfocus"), {}))))
        self.assertIs(bus.sent[-1]["pin"], False)

    def test_dry_run_sends_nothing(self) -> None:
        bus = FakeBus()
        s = skill(bus)
        run(s.run(run(s.plan(Decision(action="focus"), {})), dry_run=True))
        self.assertEqual(bus.sent, [])


class ReadTests(unittest.TestCase):
    def test_read_prefers_selection_then_ocr(self) -> None:
        s = skill(FakeBus(dict(BUNDLE, selection="Hello selected")))
        self.assertEqual(run(s.run(run(s.plan(Decision(action="read"), {})))).text,
                         "Hello selected")
        s = skill(FakeBus())
        text = run(s.run(run(s.plan(Decision(action="read"), {})))).text
        self.assertTrue(text.startswith("KeyError"))

    def test_private_window(self) -> None:
        s = skill(FakeBus({"window": {"process": "msedge.exe"}, "pinned": False,
                           "redacted": True}))
        result = run(s.run(run(s.plan(Decision(action="read"), {}))))
        self.assertFalse(result.ok)
        self.assertIn("private", result.text)

    def test_nothing_to_read(self) -> None:
        s = skill(FakeBus(dict(BUNDLE, region={"rect": [0, 0, 1, 1], "ocr_text": ""})))
        self.assertFalse(run(s.run(run(s.plan(Decision(action="read"), {})))).ok)

    def test_long_text_is_cut_for_speaking(self) -> None:
        s = skill(FakeBus(dict(BUNDLE, selection="word " * 400)))
        text = run(s.run(run(s.plan(Decision(action="read"), {})))).text
        self.assertLessEqual(len(text), ScreenSkill.MAX_SPOKEN + 2)

    def test_voice_vibe_offline(self) -> None:
        s = skill(FakeBus(up=False))
        result = run(s.run(run(s.plan(Decision(action="read"), {}))))
        self.assertFalse(result.ok)
        self.assertIn("Voice Vibe", result.text)


class WindowsMCPTests(unittest.TestCase):
    def test_region_snapshot_is_added_as_data(self) -> None:
        calls = []

        async def mcp(tool, args):  # noqa: ANN001, ANN202
            calls.append((tool, args))
            return "Interactive Elements:\n# Button 'Run'"

        s = skill(FakeBus(), mcp=mcp)
        bundle = run(s.deep_context())
        self.assertEqual(calls[0][0], "Snapshot")
        self.assertEqual(calls[0][1]["region"], [0, 0, 800, 500])
        self.assertFalse(calls[0][1]["use_vision"])
        self.assertFalse(calls[0][1]["use_dom"])
        self.assertIn("Button 'Run'", bundle["region"]["ui_text"])

    def test_browser_uses_dom(self) -> None:
        calls = []

        async def mcp(tool, args):  # noqa: ANN001, ANN202
            calls.append(args)
            return "page text"

        zen = dict(BUNDLE, window={"hwnd": 9, "title": "x", "process": "zen.exe"},
                   browser={"name": "zen", "title": "x", "dom_text": None})
        bundle = run(skill(FakeBus(zen), mcp=mcp).deep_context())
        self.assertTrue(calls[0]["use_dom"])
        self.assertEqual(bundle["browser"]["dom_text"], "page text")

    def test_mcp_missing_or_failing_is_skipped(self) -> None:
        async def broken(tool, args):  # noqa: ANN001, ANN202
            raise RuntimeError("Windows-MCP not installed")

        bundle = run(skill(FakeBus(), mcp=broken).deep_context())
        self.assertNotIn("ui_text", bundle["region"])

    def test_never_called_for_a_private_window(self) -> None:
        calls = []

        async def mcp(tool, args):  # noqa: ANN001, ANN202
            calls.append(tool)
            return ""

        bundle = run(skill(FakeBus({"window": {"process": "x"}, "pinned": False,
                                    "redacted": True}), mcp=mcp).deep_context())
        self.assertTrue(bundle["redacted"])
        self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
