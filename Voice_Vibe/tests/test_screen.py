"""Foreground-window identity and DPI awareness.

The Win32 calls are faked at the `_user32` / `_dwmapi` seam, so these run on a
bare checkout on any OS -- and never depend on which window happens to be
focused while the suite runs.
"""

from __future__ import annotations

import sys
import types
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from voicevibe import __main__ as cli  # noqa: E402
from voicevibe import screen  # noqa: E402


class FakeUser32:
    """Answers the calls window_info makes, filling byref out-params."""

    def __init__(self, foreground=0x1234, title="Untitled - Notepad", pid=4242,
                 rect=(10, 20, 810, 620)) -> None:  # noqa: ANN001
        self.foreground = foreground
        self.title = title
        self.pid = pid
        self.rect = rect
        self.asked_for_foreground = False

    def GetForegroundWindow(self):  # noqa: ANN201, N802
        self.asked_for_foreground = True
        return self.foreground

    def GetWindowRect(self, hwnd, ref) -> int:  # noqa: ANN001, N802
        if self.rect is None:
            return 0
        r = ref._obj
        r.left, r.top, r.right, r.bottom = self.rect
        return 1

    def GetWindowThreadProcessId(self, hwnd, ref) -> int:  # noqa: ANN001, N802
        ref._obj.value = self.pid
        return 1

    def GetWindowTextLengthW(self, hwnd) -> int:  # noqa: ANN001, N802
        return len(self.title)

    def GetWindowTextW(self, hwnd, buffer, size) -> int:  # noqa: ANN001, N802
        buffer.value = self.title[: size - 1]
        return len(buffer.value)


class FakeDwmapi:
    def __init__(self, rect=None, hresult=0) -> None:  # noqa: ANN001
        self.rect = rect
        self.hresult = hresult

    def DwmGetWindowAttribute(self, hwnd, attribute, ref, size) -> int:  # noqa: ANN001, N802
        if self.hresult == 0:
            r = ref._obj
            r.left, r.top, r.right, r.bottom = self.rect
        return self.hresult


def fake_psutil(names: dict[int, str]) -> types.ModuleType:
    module = types.ModuleType("psutil")

    class NoSuchProcess(Exception):
        pass

    class Process:
        def __init__(self, pid: int) -> None:
            if pid not in names:
                raise NoSuchProcess(pid)
            self.pid = pid

        def name(self) -> str:
            return names[self.pid]

    module.NoSuchProcess = NoSuchProcess
    module.Process = Process
    return module


class WindowInfoTest(unittest.TestCase):
    def info(self, user32, dwmapi=None, psutil=None, hwnd=None):  # noqa: ANN001, ANN201
        dwm = dwmapi or FakeDwmapi(hresult=1)  # default: DWM unavailable
        with mock.patch.object(screen.sys, "platform", "win32"), \
                mock.patch.object(screen, "_user32", lambda: user32), \
                mock.patch.object(screen, "_dwmapi", lambda: dwm), \
                mock.patch.dict(sys.modules, {"psutil": psutil or fake_psutil({4242: "notepad.exe"})}):
            return screen.window_info(hwnd)

    def test_describes_the_foreground_window(self) -> None:
        info = self.info(FakeUser32())
        self.assertEqual(
            info,
            {"hwnd": 0x1234, "title": "Untitled - Notepad",
             "process_name": "notepad.exe", "rect": (10, 20, 810, 620)},
        )

    def test_an_explicit_handle_skips_the_foreground_lookup(self) -> None:
        user32 = FakeUser32()
        info = self.info(user32, hwnd=0x9999)
        self.assertEqual(info["hwnd"], 0x9999)
        self.assertFalse(user32.asked_for_foreground)

    def test_prefers_visible_frame_bounds_over_the_padded_window_rect(self) -> None:
        # GetWindowRect includes ~7px of invisible resize border on Windows 10+.
        info = self.info(FakeUser32(rect=(3, 13, 817, 627)),
                         dwmapi=FakeDwmapi(rect=(10, 20, 810, 620)))
        self.assertEqual(info["rect"], (10, 20, 810, 620))

    def test_falls_back_to_window_rect_when_dwm_fails(self) -> None:
        info = self.info(FakeUser32(rect=(3, 13, 817, 627)), dwmapi=FakeDwmapi(hresult=-1))
        self.assertEqual(info["rect"], (3, 13, 817, 627))

    def test_a_vanished_process_leaves_the_name_blank(self) -> None:
        info = self.info(FakeUser32(pid=7), psutil=fake_psutil({}))
        self.assertEqual(info["process_name"], "")
        self.assertEqual(info["title"], "Untitled - Notepad")

    def test_missing_psutil_leaves_the_name_blank(self) -> None:
        dwm = FakeDwmapi(hresult=1)
        # A None entry in sys.modules makes `import psutil` raise ImportError.
        with mock.patch.object(screen.sys, "platform", "win32"), \
                mock.patch.object(screen, "_user32", FakeUser32), \
                mock.patch.object(screen, "_dwmapi", lambda: dwm), \
                mock.patch.dict(sys.modules, {"psutil": None}):
            info = screen.window_info()
        self.assertEqual(info["process_name"], "")

    def test_no_foreground_window_gives_none(self) -> None:
        self.assertIsNone(self.info(FakeUser32(foreground=0)))

    def test_an_unreadable_rect_gives_none(self) -> None:
        self.assertIsNone(self.info(FakeUser32(rect=None)))

    def test_other_platforms_give_none(self) -> None:
        with mock.patch.object(screen.sys, "platform", "linux"):
            self.assertIsNone(screen.window_info())


class DpiAwarenessTest(unittest.TestCase):
    def run_with(self, windll) -> None:  # noqa: ANN001
        with mock.patch.object(cli.sys, "platform", "win32"), \
                mock.patch("ctypes.windll", windll, create=True):
            cli.enable_dpi_awareness()

    def test_requests_per_monitor_awareness(self) -> None:
        windll = mock.Mock()
        self.run_with(windll)
        windll.shcore.SetProcessDpiAwareness.assert_called_once_with(2)
        windll.user32.SetProcessDPIAware.assert_not_called()

    def test_falls_back_to_system_awareness_without_shcore(self) -> None:
        windll = mock.Mock()
        windll.shcore.SetProcessDpiAwareness.side_effect = OSError("no shcore")
        self.run_with(windll)
        windll.user32.SetProcessDPIAware.assert_called_once_with()

    def test_never_raises_when_neither_call_exists(self) -> None:
        windll = mock.Mock()
        windll.shcore.SetProcessDpiAwareness.side_effect = AttributeError
        windll.user32.SetProcessDPIAware.side_effect = AttributeError
        self.run_with(windll)  # must not raise

    def test_does_nothing_off_windows(self) -> None:
        windll = mock.Mock()
        with mock.patch.object(cli.sys, "platform", "linux"), \
                mock.patch("ctypes.windll", windll, create=True):
            cli.enable_dpi_awareness()
        windll.assert_not_called()
        self.assertFalse(windll.shcore.SetProcessDpiAwareness.called)

    def test_main_sets_awareness_before_anything_else(self) -> None:
        order: list[str] = []
        with mock.patch.object(cli, "enable_dpi_awareness", lambda: order.append("dpi")), \
                mock.patch.object(cli, "setup_logging", lambda v: order.append("logging")), \
                mock.patch.object(cli, "load_config", side_effect=SystemExit):
            with self.assertRaises(SystemExit):
                cli.main([])
        self.assertEqual(order, ["dpi", "logging"])


if __name__ == "__main__":
    unittest.main()
