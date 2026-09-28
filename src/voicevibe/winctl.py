"""Top-level windows: list them, find one by a spoken name, bring it forward.

Plus the few window operations that have no dependable keyboard shortcut.
Win+Down minimises only from the restored state and Win+Up is a no-op on some
windows, so minimise/maximise/restore call ShowWindow directly. Win+L cannot be
synthesised at all -- Windows drops it by design -- so locking calls
LockWorkStation. Everything else in the command set is a shortcut.
"""

from __future__ import annotations

import ctypes
import logging
import os
import re
import sys
from ctypes import wintypes
from typing import Any

from .launcher import Launcher, _normalize
from .screen import _dwmapi, window_info

log = logging.getLogger(__name__)

_GW_OWNER = 4
_GWL_EXSTYLE = -20
_WS_EX_TOOLWINDOW = 0x00000080
_WS_EX_NOACTIVATE = 0x08000000
_DWMWA_CLOAKED = 14
_SW = {"minimize": 6, "maximize": 3, "restore": 9}
# The desktop and taskbar report as foreground windows too. Minimising them
# does nothing useful, and "maximise the taskbar" is never what was meant.
_SHELL_CLASSES = {"Progman", "WorkerW", "Shell_TrayWnd", "Shell_SecondaryTrayWnd"}
# Separators browsers and editors put between page and app in a title.
_TITLE_PARTS = re.compile(r"\s+[-–—|]\s+")


def _user32():  # noqa: ANN201
    user32 = ctypes.windll.user32
    user32.GetForegroundWindow.restype = wintypes.HWND
    user32.GetWindow.restype = wintypes.HWND
    user32.GetWindow.argtypes = [wintypes.HWND, wintypes.UINT]
    user32.GetWindowLongW.restype = wintypes.LONG
    user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    user32.IsIconic.argtypes = [wintypes.HWND]
    user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.SetForegroundWindow.argtypes = [wintypes.HWND]
    user32.BringWindowToTop.argtypes = [wintypes.HWND]
    user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.GetWindowThreadProcessId.restype = wintypes.DWORD
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.AttachThreadInput.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.BOOL]
    return user32


def _class_name(user32, hwnd) -> str:  # noqa: ANN001
    buffer = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, buffer, 256)
    return buffer.value


def _is_switchable(user32, hwnd) -> bool:  # noqa: ANN001
    """What Alt+Tab would show: visible, unowned, not a tool or ghost window."""
    if not user32.IsWindowVisible(hwnd) or user32.GetWindow(hwnd, _GW_OWNER):
        return False
    style = user32.GetWindowLongW(hwnd, _GWL_EXSTYLE)
    if style & (_WS_EX_TOOLWINDOW | _WS_EX_NOACTIVATE):
        return False
    # Suspended UWP apps and windows on other virtual desktops are "visible"
    # but cloaked; switching to one shows nothing.
    cloaked = ctypes.c_int(0)
    try:
        _dwmapi().DwmGetWindowAttribute(
            hwnd, _DWMWA_CLOAKED, ctypes.byref(cloaked), ctypes.sizeof(cloaked)
        )
    except Exception:
        pass
    if cloaked.value:
        return False
    return _class_name(user32, hwnd) not in _SHELL_CLASSES


def top_level_windows() -> list[dict[str, Any]]:
    """Switchable windows, most recently active first (EnumWindows Z-order).

    Each entry is screen.window_info() plus "z", its place in that order.
    This process's own windows (the orb) are left out.
    """
    if sys.platform != "win32":
        return []
    user32 = _user32()
    own = os.getpid()
    handles: list[int] = []

    def visit(hwnd, _lparam) -> bool:  # noqa: ANN001
        try:
            pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if pid.value != own and _is_switchable(user32, hwnd):
                handles.append(hwnd)
        except Exception as exc:
            log.debug("skipping window %s: %s", hwnd, exc)
        return True  # keep enumerating

    # Built per call: WINFUNCTYPE exists only on Windows.
    callback = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)(visit)
    user32.EnumWindows(callback, 0)

    windows = []
    for z, hwnd in enumerate(handles):
        info = window_info(hwnd)
        if info and info["title"]:
            info["z"] = z
            windows.append(info)
    return windows


def _labels(window: dict[str, Any]) -> list[str]:
    """Names a window answers to: its exe, its title, and each title part.

    "Inbox - Gmail - Google Chrome" answers to "gmail" and "google chrome" as
    well as "chrome", which is how people actually refer to it.
    """
    stem = os.path.splitext(str(window.get("process_name") or ""))[0]
    title = str(window.get("title") or "")
    labels = [stem, title, *_TITLE_PARTS.split(title)]
    return [n for n in (_normalize(label) for label in labels) if n]


def match_window(
    spoken: str,
    windows: list[dict[str, Any]],
    threshold: float = 0.84,
    foreground: int | None = None,
) -> dict[str, Any] | None:
    """Best window for a spoken name, or None if nothing is close enough.

    Scored the way the launcher scores app names. An exact name beats a
    contained word, so "code" picks VS Code over a browser tab that mentions
    code. Ties go to a window that is not already in front, then to the most
    recently used.

    Stricter than the launcher's 0.78: plain similarity puts "photoshop" at
    0.80 against Photos.exe, and focusing the wrong window is worse than
    saying it is not open. Word matches score 0.84 and up, so they still pass.
    """
    wanted = _normalize(spoken)
    if not wanted:
        return None
    words = wanted.split()
    best: tuple[tuple[float, bool, int], dict[str, Any]] | None = None
    for window in windows:
        labels = _labels(window)
        if not labels:
            continue
        score = max(1.0 if label == wanted else Launcher._score(label, wanted, words)
                    for label in labels)
        rank = (score, window.get("hwnd") != foreground, -int(window.get("z", 0)))
        if best is None or rank > best[0]:
            best = (rank, window)
    if best is None or best[0][0] < threshold:
        return None
    return best[1]


def foreground() -> int | None:
    if sys.platform != "win32":
        return None
    return _user32().GetForegroundWindow() or None


def focus(hwnd: int) -> bool:
    """Bring `hwnd` to the front. True if it actually got there.

    Windows only lets the foreground process hand focus away, and this app is
    in the background by design. Attaching to the foreground thread's input
    queue makes the call count as coming from it -- the standard way around
    the focus-steal rule, and nothing is left attached afterwards.
    """
    if sys.platform != "win32":
        return False
    user32 = _user32()
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, _SW["restore"])
    if user32.SetForegroundWindow(hwnd) and user32.GetForegroundWindow() == hwnd:
        return True

    current = user32.GetForegroundWindow()
    theirs = user32.GetWindowThreadProcessId(current, None) if current else 0
    mine = ctypes.windll.kernel32.GetCurrentThreadId()
    attached = bool(theirs and theirs != mine and user32.AttachThreadInput(mine, theirs, True))
    try:
        user32.BringWindowToTop(hwnd)
        user32.SetForegroundWindow(hwnd)
    finally:
        if attached:
            user32.AttachThreadInput(mine, theirs, False)
    return user32.GetForegroundWindow() == hwnd


def show(op: str) -> bool:
    """Minimise, maximise or restore the foreground window."""
    if sys.platform != "win32" or op not in _SW:
        return False
    user32 = _user32()
    hwnd = user32.GetForegroundWindow()
    if not hwnd or _class_name(user32, hwnd) in _SHELL_CLASSES:
        return False
    user32.ShowWindow(hwnd, _SW[op])
    return True


def lock() -> bool:
    if sys.platform != "win32":
        return False
    return bool(ctypes.windll.user32.LockWorkStation())


def process(hwnd: int | None) -> str:
    """Executable name of the process owning `hwnd`, lowercase, or ""."""
    if not hwnd:
        return ""
    info = window_info(hwnd) or {}
    return str(info.get("process_name") or "").lower()


class Desktop:
    """The window operations the executor needs, as one replaceable object."""

    windows = staticmethod(top_level_windows)
    foreground = staticmethod(foreground)
    focus = staticmethod(focus)
    show = staticmethod(show)
    lock = staticmethod(lock)
    process = staticmethod(process)
