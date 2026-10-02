"""voicevibe.context: the §3.3 context bundle sent with every hub request.

Every OS source is injected, so nothing touches the real desktop, clipboard
or screen. The privacy guard is the real one.
"""

from __future__ import annotations

import os
import tempfile
import time
import unittest
from pathlib import Path

import stubs

stubs.install()

from voicevibe.context import ContextBuilder, LocalScreen, describe_element, purge_crops  # noqa: E402
from voicevibe.focus import FocusPin  # noqa: E402
from voicevibe.privacy import PrivacyGuard  # noqa: E402

MONITOR = (0, 0, 1920, 1200)
CODE = {"hwnd": 11, "title": "main.py - uBipedal - Visual Studio Code", "process": "Code.exe",
        "rect": (0, 0, 1920, 1200)}
EDGE = {"hwnd": 22, "title": "Laya docs and 3 more pages - Personal - Microsoft\u200b Edge",
        "process": "msedge.exe", "rect": (0, 0, 1920, 1200)}
BANK = {"hwnd": 33, "title": "HDFC Bank NetBanking - Microsoft Edge", "process": "msedge.exe",
        "rect": (900, 0, 1920, 1200)}
ELEMENT = {"name": "Run and Debug", "type": "TabItem", "rect": [0, 200, 48, 248],
           "ancestors": [{"name": "Activity Bar", "type": "ToolBar"},
                         {"name": "main.py - uBipedal - Visual Studio Code", "type": "Window"}]}


class FakeFrame:
    def show(self, rect, seconds=None):  # noqa: ANN001, ANN201
        pass

    def hide(self):  # noqa: ANN201
        pass


class FakeImage:
    def __init__(self, rect) -> None:  # noqa: ANN001
        self.rect = rect
        self.saved: list[str] = []

    def save(self, path, format=None):  # noqa: ANN001, A002, ANN201
        Path(path).write_bytes(b"\x89PNG fake")
        self.saved.append(str(path))


class Sources:
    def __init__(self) -> None:
        self.front = dict(CODE)
        self.under = dict(CODE)
        self.others: list[dict] = []
        self.point = (960, 600)
        self.selection_calls = 0
        self.grabs: list = []

    def builder(self, crops: Path, **kw) -> ContextBuilder:  # noqa: ANN003
        self.now = [1000.0]
        pin = FocusPin(seconds=60, frame=FakeFrame(), clock=lambda: self.now[0],
                       pointer=lambda: self.point, monitor_at=lambda p: MONITOR)
        return ContextBuilder(
            {"max_chars": 50}, guard=kw.pop("guard", PrivacyGuard()), pin=pin,
            window=lambda: dict(self.front), window_at=lambda p: dict(self.under),
            windows=lambda: [dict(self.front), *self.others], pointer=lambda: self.point,
            element_at=lambda p: dict(ELEMENT), caret=lambda: "def walk(self):\n    return 1",
            focused=lambda: {"name": "Editor content", "type": "Edit", "class": ""},
            selection=self._selection, grab=self._grab, ocr=lambda img: "Traceback: KeyError",
            browser_url=lambda hwnd: "https://example.org/laya", crops_dir=crops,
            clock=lambda: 1_700_000_000.0, **kw)

    def _selection(self) -> str:
        self.selection_calls += 1
        return "selected words"

    def _grab(self, rect):  # noqa: ANN001, ANN202
        image = FakeImage(rect)
        self.grabs.append(image)
        return image


class Base(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.crops = Path(self.tmp.name) / "crops"
        self.src = Sources()
        self.ctx = self.src.builder(self.crops)

    def tearDown(self) -> None:
        self.tmp.cleanup()


class BundleTests(Base):
    def test_shallow_bundle_is_cheap(self) -> None:
        b = self.ctx.bundle()
        self.assertEqual(b["window"], {"hwnd": 11, "title": CODE["title"], "process": "Code.exe"})
        self.assertEqual(b["pointer_element"]["name"], "Run and Debug")
        self.assertEqual(len(b["pointer_element"]["ancestors"]), 2)
        self.assertEqual(b["focused_element"]["type"], "Edit")
        self.assertTrue(b["caret_text"].startswith("def walk"))
        self.assertEqual(b["region"]["rect"], [560, 350, 1360, 850])
        self.assertNotIn("ocr_text", b["region"])
        self.assertEqual(b["selection"], "")
        self.assertEqual(self.src.selection_calls, 0)
        self.assertEqual(self.src.grabs, [])
        self.assertFalse(b["pinned"])
        self.assertFalse(b["redacted"])
        self.assertNotIn("browser", b)

    def test_deep_bundle_adds_selection_ocr_and_a_crop(self) -> None:
        b = self.ctx.bundle(deep=True)
        self.assertEqual(b["selection"], "selected words")
        self.assertEqual(b["region"]["ocr_text"], "Traceback: KeyError")
        ref = Path(b["region"]["image_ref"])
        self.assertTrue(ref.is_file())
        self.assertEqual(ref.parent, self.crops)
        self.assertEqual(self.src.grabs[0].rect, (560, 350, 1360, 850))

    def test_text_is_capped(self) -> None:
        self.ctx.caret = lambda: "x" * 500
        self.assertEqual(len(self.ctx.bundle()["caret_text"]), 50)

    def test_pinned_region_wins_over_the_pointer(self) -> None:
        self.ctx.pin.pin()
        self.src.point = (10, 10)
        b = self.ctx.bundle(deep=True)
        self.assertTrue(b["pinned"])
        self.assertEqual(b["region"]["rect"], [560, 350, 1360, 850])

    def test_bundle_can_pin_and_unpin(self) -> None:
        self.assertTrue(self.ctx.bundle(pin=True)["pinned"])
        self.assertFalse(self.ctx.bundle(pin=False)["pinned"])

    def test_browser_part(self) -> None:
        self.src.front = dict(EDGE)
        b = self.ctx.bundle()
        self.assertEqual(b["browser"]["name"], "edge")
        self.assertEqual(b["browser"]["title"], "Laya docs")
        self.assertNotIn("url", b["browser"])
        self.assertIsNone(b["browser"]["dom_text"])
        self.assertEqual(self.ctx.bundle(deep=True)["browser"]["url"], "https://example.org/laya")

    def test_a_failing_source_leaves_its_key_empty(self) -> None:
        def boom(*a):  # noqa: ANN002, ANN202
            raise OSError("uia died")

        self.ctx.element_at = boom
        self.ctx.caret = boom
        b = self.ctx.bundle()
        self.assertEqual(b["caret_text"], "")
        self.assertNotIn("pointer_element", b)
        self.assertEqual(b["window"]["process"], "Code.exe")


class PrivacyTests(Base):
    def assert_redacted(self, b: dict) -> None:
        self.assertTrue(b["redacted"])
        self.assertEqual(set(b), {"window", "pinned", "redacted"})
        self.assertEqual(set(b["window"]), {"process"})
        self.assertEqual(self.src.selection_calls, 0)
        self.assertEqual(self.src.grabs, [])
        self.assertFalse(any(self.crops.glob("*.png")) if self.crops.exists() else False)

    def test_blocked_foreground(self) -> None:
        self.src.front = dict(BANK)
        self.assert_redacted(self.ctx.bundle(deep=True))

    def test_blocked_window_under_the_pointer(self) -> None:
        self.src.under = dict(BANK)
        self.assert_redacted(self.ctx.bundle(deep=True))

    def test_blocked_window_inside_the_region(self) -> None:
        self.src.others = [dict(BANK)]
        self.assert_redacted(self.ctx.bundle(deep=True))

    def test_marked_window(self) -> None:
        self.ctx.guard.mark(CODE)
        self.assert_redacted(self.ctx.bundle())


class CropPurgeTests(unittest.TestCase):
    def test_old_crops_are_deleted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            old, new, other = d / "crop-1.png", d / "crop-2.png", d / "notes.txt"
            for p in (old, new, other):
                p.write_bytes(b"x")
            now = time.time()
            os.utime(old, (now - 3 * 86400, now - 3 * 86400))
            self.assertEqual(purge_crops(d, now=now), 1)
            self.assertFalse(old.exists())
            self.assertTrue(new.exists() and other.exists())


class LocalScreenTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.src = Sources()
        self.local = LocalScreen(self.src.builder(Path(self.tmp.name)))

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_focus_and_unfocus(self) -> None:
        reply = self.local.handle("focus on my cursor")
        self.assertIn("Focused", reply.speak)
        self.assertIsNotNone(self.local.context.pin.current())
        self.assertIn("off", self.local.handle("unfocus").speak.lower())
        self.assertIsNone(self.local.context.pin.current())

    def test_whats_this_names_the_element(self) -> None:
        reply = self.local.handle("What's this?")
        self.assertEqual(reply.speak, "Run and Debug tab, in Activity Bar, Visual Studio Code.")

    def test_whats_this_looks_twice_at_a_sleeping_chromium_tree(self) -> None:
        calls = []

        def element(point):  # noqa: ANN001, ANN202
            calls.append(point)
            if len(calls) == 1:
                return {"name": "", "type": "Group", "ancestors": []}
            return {"name": "Send", "type": "Button", "ancestors": []}

        self.local.retry_delay = 0
        self.local.context.element_at = element
        self.assertEqual(self.local.handle("what's this").speak, "Send button, Visual Studio Code.")

    def test_whats_this_in_a_private_window(self) -> None:
        self.src.under = dict(BANK)
        self.assertIn("private", self.local.handle("what's this").speak)

    def test_mark_private_and_back(self) -> None:
        self.assertIn("won't look", self.local.handle("don't look at this window").speak)
        self.assertTrue(self.local.context.bundle()["redacted"])
        self.local.handle("you can look at this window again")
        self.assertFalse(self.local.context.bundle()["redacted"])

    def test_other_text_is_not_handled(self) -> None:
        self.assertIsNone(self.local.handle("explain this"))
        self.assertIsNone(self.local.handle("focus on the build"))


class DescribeTests(unittest.TestCase):
    def test_describe(self) -> None:
        self.assertEqual(describe_element({"name": "Save", "type": "Button", "ancestors": []},
                                          "Notepad"), "Save button, Notepad.")
        self.assertEqual(describe_element({"name": "", "type": "Edit", "ancestors": []}, ""),
                         "A text box.")
        self.assertEqual(describe_element(None, "Spotify"), "")


class AppWiringTests(unittest.TestCase):
    """The session path: local screen phrases are answered, never typed."""

    def test_phrases_are_handled_locally(self) -> None:
        from types import SimpleNamespace
        from unittest.mock import Mock

        from voicevibe import app
        from voicevibe.control import Router
        from voicevibe.inserter import Inserter

        for text in ("focus on my cursor", "unfocus", "what's this"):
            with self.subTest(text=text), tempfile.TemporaryDirectory() as tmp:
                vv = app.VoiceVibe.__new__(app.VoiceVibe)
                vv.config = SimpleNamespace(output={}, control={}, feedback={}, wake={})
                vv.wake_enabled = False
                vv._last_inserted = ""
                vv._ends_dictation = False
                vv.executor = app.Executor(keyboard=stubs.FakeController(),
                                           desktop=SimpleNamespace(foreground=lambda: 1,
                                                                   process=lambda h: "x.exe"))
                vv.router = Router({"enabled": True}, executor=vv.executor, finder=Mock(),
                                   profiles={})
                vv.router._front = lambda: 1
                vv.local_screen = LocalScreen(Sources().builder(Path(tmp)))
                vv.inserter = Inserter({"mode": "type"}, [])
                vv.history, vv.overlay, vv.beeper, vv.voice = Mock(), Mock(), Mock(), Mock()
                vv._do_session(f"computer {text}", 0.1)
                self.assertEqual(vv.inserter.keyboard.events, [], text)
                vv.voice.say.assert_called_once()
                vv.history.add.assert_called_once()


if __name__ == "__main__":
    unittest.main()
