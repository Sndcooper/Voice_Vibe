"""Focus pin: "computer focus on my cursor" -> this region is the context.

An ~800x500 rectangle around the pointer, clamped to the monitor it is on,
becomes the region every hub request describes (OCR, crop for vision,
Windows-MCP Snapshot) until "computer unfocus" or the timeout. A thin frame in
the orb's session colour is drawn around it, click-through and never
focused, the way the numbered badges are (overlay._create_layered_window).

Without a pin the region still follows the pointer; the pin is for "look at
*this*" when the pointer has to move on (to the Voice Vibe orb, a terminal).
"""

from __future__ import annotations

import ctypes
import logging
import sys
import threading
import time
from typing import Any, Callable

log = logging.getLogger(__name__)

REGION_SIZE = (800, 500)
DEFAULT_SECONDS = 180.0
FRAME_PAD = 3
FRAME_WIDTH = 3
FRAME_COLOR = (70, 160, 235, 230)  # overlay.COLORS["session"]

Rect = tuple[int, int, int, int]


def region_around(point: tuple[int, int], monitor: Rect,
                  size: tuple[int, int] = REGION_SIZE) -> Rect:
    """`size` rectangle centred on `point`, slid (not shrunk) to fit `monitor`."""
    left, top, right, bottom = monitor
    width, height = min(size[0], right - left), min(size[1], bottom - top)
    x = min(max(point[0] - width // 2, left), right - width)
    y = min(max(point[1] - height // 2, top), bottom - height)
    return x, y, x + width, y + height


# ------------------------------------------------------------- win32
def pointer_position() -> tuple[int, int]:
    if sys.platform != "win32":
        return 0, 0
    from ctypes import wintypes

    point = wintypes.POINT()
    ctypes.windll.user32.GetCursorPos(ctypes.byref(point))
    return point.x, point.y


class _MonitorInfo(ctypes.Structure):
    _fields_ = [("cbSize", ctypes.c_ulong), ("rcMonitor", ctypes.c_long * 4),
                ("rcWork", ctypes.c_long * 4), ("dwFlags", ctypes.c_ulong)]


def monitor_at(point: tuple[int, int]) -> Rect:
    """Bounds of the monitor showing `point` (nearest one if off-screen)."""
    if sys.platform != "win32":
        return 0, 0, 1920, 1080
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    user32.MonitorFromPoint.restype = wintypes.HMONITOR
    user32.MonitorFromPoint.argtypes = [wintypes.POINT, wintypes.DWORD]
    user32.GetMonitorInfoW.argtypes = [wintypes.HMONITOR, ctypes.POINTER(_MonitorInfo)]
    monitor = user32.MonitorFromPoint(wintypes.POINT(*point), 2)  # MONITOR_DEFAULTTONEAREST
    info = _MonitorInfo()
    info.cbSize = ctypes.sizeof(_MonitorInfo)
    if not monitor or not user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
        return 0, 0, user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)
    return tuple(info.rcMonitor)  # type: ignore[return-value]


# ------------------------------------------------------------- frame
def render_frame(rect: Rect) -> tuple[Any, tuple[int, int]]:
    """(RGBA image, screen origin) of an outline just outside `rect`."""
    from PIL import Image, ImageDraw

    width = rect[2] - rect[0] + 2 * FRAME_PAD
    height = rect[3] - rect[1] + 2 * FRAME_PAD
    image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    ImageDraw.Draw(image).rounded_rectangle((0, 0, width - 1, height - 1), radius=8,
                                            outline=FRAME_COLOR, width=FRAME_WIDTH)
    return image, (rect[0] - FRAME_PAD, rect[1] - FRAME_PAD)


class Frame:
    """The outline window, on its own thread (like overlay.Badges)."""

    def __init__(self) -> None:
        self.enabled = sys.platform == "win32"
        self._lock = threading.Lock()
        self._rect: Rect | None = None
        self._until = 0.0
        self._version = 0
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def show(self, rect: Rect, seconds: float | None = None) -> None:
        with self._lock:
            self._rect = tuple(rect)  # type: ignore[assignment]
            self._until = time.monotonic() + (seconds or DEFAULT_SECONDS)
            self._version += 1
        if self.enabled and self._thread is None:
            self._thread = threading.Thread(target=self._run, name="focus-frame", daemon=True)
            self._thread.start()

    def hide(self) -> None:
        with self._lock:
            if self._rect is not None:
                self._rect = None
                self._version += 1

    def stop(self) -> None:
        self._stop.set()

    def _run(self) -> None:
        from .overlay import (_HWND_TOPMOST, _SW_HIDE, _SW_SHOWNOACTIVATE, _SWP_NOACTIVATE,
                              _SWP_NOMOVE, _SWP_NOSIZE, _blit, _create_layered_window)

        try:
            hwnd, wndproc_ref = _create_layered_window("VoiceVibeFocus", "Voice Vibe focus")
        except Exception as exc:  # noqa: BLE001
            log.debug("focus frame unavailable: %s", exc)
            self.enabled = False
            return
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        user32.ShowWindow(hwnd, _SW_HIDE)
        msg = wintypes.MSG()
        drawn = 0
        try:
            while not self._stop.is_set():
                while user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 1):
                    user32.TranslateMessage(ctypes.byref(msg))
                    user32.DispatchMessageW(ctypes.byref(msg))
                with self._lock:
                    if self._rect is not None and time.monotonic() >= self._until:
                        self._rect = None
                        self._version += 1
                    version, rect = self._version, self._rect
                if version != drawn:
                    drawn = version
                    if rect is None:
                        user32.ShowWindow(hwnd, _SW_HIDE)
                    else:
                        image, (x, y) = render_frame(rect)
                        _blit(hwnd, image, x, y)
                        user32.ShowWindow(hwnd, _SW_SHOWNOACTIVATE)
                        user32.SetWindowPos(hwnd, _HWND_TOPMOST, 0, 0, 0, 0,
                                            _SWP_NOMOVE | _SWP_NOSIZE | _SWP_NOACTIVATE)
                time.sleep(0.05)
        finally:
            user32.DestroyWindow(hwnd)
            del wndproc_ref


# --------------------------------------------------------------- pin
class FocusPin:
    def __init__(self, seconds: float = DEFAULT_SECONDS, size: tuple[int, int] = REGION_SIZE,
                 frame: Any = None, clock: Callable[[], float] = time.monotonic,
                 pointer: Callable[[], tuple[int, int]] = pointer_position,
                 monitor_at: Callable[[tuple[int, int]], Rect] = monitor_at) -> None:
        self.seconds = float(seconds)
        self.size = tuple(size)
        self.frame = frame if frame is not None else Frame()
        self.clock = clock
        self.pointer = pointer
        self.monitor_at = monitor_at
        self._rect: Rect | None = None
        self._until = 0.0
        self._lock = threading.Lock()

    def region_at_pointer(self) -> Rect:
        point = self.pointer()
        return region_around(point, self.monitor_at(point), self.size)  # type: ignore[arg-type]

    def pin(self, rect: Rect | None = None) -> Rect:
        rect = tuple(rect) if rect else self.region_at_pointer()  # type: ignore[assignment]
        with self._lock:
            self._rect, self._until = rect, self.clock() + self.seconds
        self.frame.show(rect, self.seconds)
        log.info("Focus pinned on %s for %.0fs", rect, self.seconds)
        return rect

    def unpin(self) -> bool:
        with self._lock:
            had, self._rect = self._rect is not None, None
        if had:
            self.frame.hide()
        return had

    def current(self) -> Rect | None:
        with self._lock:
            if self._rect is not None and self.clock() >= self._until:
                self._rect = None
                expired = True
            else:
                expired = False
            rect = self._rect
        if expired:
            self.frame.hide()
            log.info("Focus pin expired")
        return rect

    def remaining(self) -> float:
        return max(0.0, self._until - self.clock()) if self.current() else 0.0

    def stop(self) -> None:
        stop = getattr(self.frame, "stop", None)
        if callable(stop):
            stop()
