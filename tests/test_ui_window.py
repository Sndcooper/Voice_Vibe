"""Control panel window + tray entry (vvhub.ui.window, launcher.add_tray_entry).

What matters: the page gets the hub token only while the window shows the
hub's own /ui/ page (never a page it navigated to), exports are written
only where the user picked in the Save dialog with a cleaned file name, a
second launch focuses the open window instead of opening another, and the
tray gets a default "Control panel" item above the existing ones. No window,
no WebView2, no real tray icon.
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from vvhub.ui import launcher, window  # noqa: E402


class FakeWindow:
    def __init__(self, url="http://127.0.0.1:53874/ui/"):
        self.url = url

    def get_current_url(self):
        return self.url


class JsApiTests(unittest.TestCase):
    def test_token_only_on_our_page(self):
        api = window.JsApi(token_reader=lambda: "T")
        self.assertEqual(api.token(), "")  # no window yet
        api.window = FakeWindow()
        self.assertEqual(api.token(), "T")
        for url in ("https://evil.example/ui/", "http://127.0.0.1:53874/ui.evil/", "http://127.0.0.1:9999/ui/",
                    "http://localhost.evil:53874/ui/", None):
            api.window = FakeWindow(url)
            self.assertEqual(api.token(), "", url)

    def test_save_text_uses_dialog_and_cleans_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            seen = {}

            def dialog(win, name):
                seen["name"] = name
                return str(Path(tmp) / name)

            api = window.JsApi(token_reader=lambda: "T", dialog=dialog)
            api.window = FakeWindow()
            path = api.save_text(r'..\..\evil:name?.md', "hello")
            self.assertEqual(seen["name"], "-..-evil-name-.md")  # no separators, no leading dots
            self.assertEqual(Path(path).read_text(encoding="utf-8"), "hello")
            api_cancel = window.JsApi(token_reader=lambda: "T", dialog=lambda w, n: None)
            api_cancel.window = FakeWindow()
            self.assertIsNone(api_cancel.save_text("a.md", "x"))

    def test_save_refused_off_our_page(self):
        called = []
        api = window.JsApi(token_reader=lambda: "T", dialog=lambda w, n: called.append(n))
        api.window = FakeWindow("https://evil.example/")
        self.assertIsNone(api.save_text("a.md", "x"))
        self.assertEqual(called, [])


class SingleInstanceTests(unittest.TestCase):
    def test_focuses_existing(self):
        shown = []
        self.assertTrue(window.focus_existing(find=lambda title: 42, show=shown.append))
        self.assertEqual(shown, [42])
        self.assertFalse(window.focus_existing(find=lambda title: 0, show=shown.append))

    def test_main_exits_when_already_open(self):
        opened = []
        rc = window.main(focus=lambda: True, ensure=lambda: opened.append("hub"), start=lambda *a: opened.append("ui"))
        self.assertEqual(rc, 0)
        self.assertEqual(opened, [])

    def test_main_starts_hub_then_window(self):
        calls = []
        rc = window.main(focus=lambda: False, ensure=lambda: calls.append("hub") or "running",
                         start=lambda url, api: calls.append(("ui", url)))
        self.assertEqual(rc, 0)
        self.assertEqual(calls, ["hub", ("ui", "http://127.0.0.1:53874/ui/")])


class TrayTests(unittest.TestCase):
    def setUp(self):
        try:
            import pystray
        except ImportError:
            self.skipTest("pystray not installed")
        self.pystray = pystray

    def test_entry_added_first_and_default(self):
        quit_calls, opened = [], []
        icon = SimpleNamespace(menu=self.pystray.Menu(self.pystray.MenuItem("Quit", lambda: quit_calls.append(1))))
        tray = SimpleNamespace(icon=icon)
        self.assertTrue(launcher.add_tray_entry(tray, opener=lambda: opened.append(1)))
        items = list(icon.menu.items)
        self.assertEqual([i.text for i in items], ["Control panel", "Quit"])
        self.assertTrue(items[0].default)
        items[0](icon)
        self.assertEqual(opened, [1])
        self.assertEqual(quit_calls, [])

    def test_no_icon_no_entry(self):
        self.assertFalse(launcher.add_tray_entry(SimpleNamespace(icon=None), opener=lambda: None))

    def test_open_control_panel_spawns_detached_ui(self):
        seen = []
        launcher.open_control_panel(spawn=lambda argv, cwd=None, env=None: seen.append((argv, cwd)) or 1)
        argv, cwd = seen[0]
        self.assertEqual(argv[1:], ["-m", "vvhub.ui"])
        self.assertTrue(argv[0].lower().endswith("pythonw.exe"))
        self.assertEqual(Path(cwd), launcher.REPO)


if __name__ == "__main__":
    unittest.main()
