"""Siri-style status orb: a frameless, click-through window pinned above everything.

Implemented as a Win32 *layered* window driven by `UpdateLayeredWindow`, with
every frame painted in Pillow. That combination is what allows real per-pixel
transparency -- a soft glow that fades into whatever is behind it -- instead of
a rectangle with a colour-keyed hole in it.

Pillow already ships as a dependency (pystray needs it), so this adds no new
package, and the whole thing costs a few megabytes: the point is to stay usable
on the low-spec laptops this targets.

Everything here is best effort. If any Win32 call fails the orb disables itself
and the app carries on with the tray icon alone.
"""

from __future__ import annotations

import ctypes
import logging
import math
import sys
import threading
import time
from ctypes import wintypes

import numpy as np
from PIL import Image, ImageDraw, ImageFont

log = logging.getLogger(__name__)

# Matches feedback.Tray so both indicators always agree.
COLORS = {
    "idle": (90, 90, 96),
    "armed": (95, 120, 150),
    "recording": (220, 60, 60),
    "busy": (230, 170, 40),
    "session": (70, 160, 235),
    "error": (200, 50, 50),
}

_WS_POPUP = 0x80000000
_WS_EX_LAYERED = 0x00080000
_WS_EX_TRANSPARENT = 0x00000020
_WS_EX_TOPMOST = 0x00000008
_WS_EX_TOOLWINDOW = 0x00000080
_WS_EX_NOACTIVATE = 0x08000000

_ULW_ALPHA = 0x00000002
_AC_SRC_OVER = 0x00
_AC_SRC_ALPHA = 0x01
_SW_SHOWNOACTIVATE = 4
_HWND_TOPMOST = -1
_SWP_NOMOVE = 0x0002
_SWP_NOSIZE = 0x0001
_SWP_NOACTIVATE = 0x0010
_WM_DESTROY = 0x0002


class _Point(ctypes.Structure):
    _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]


class _Size(ctypes.Structure):
    _fields_ = [("cx", wintypes.LONG), ("cy", wintypes.LONG)]


class _BlendFunction(ctypes.Structure):
    _fields_ = [
        ("BlendOp", ctypes.c_byte),
        ("BlendFlags", ctypes.c_byte),
        ("SourceConstantAlpha", ctypes.c_byte),
        ("AlphaFormat", ctypes.c_byte),
    ]


class _BitmapInfoHeader(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD),
        ("biWidth", wintypes.LONG),
        ("biHeight", wintypes.LONG),
        ("biPlanes", wintypes.WORD),
        ("biBitCount", wintypes.WORD),
        ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD),
        ("biXPelsPerMeter", wintypes.LONG),
        ("biYPelsPerMeter", wintypes.LONG),
        ("biClrUsed", wintypes.DWORD),
        ("biClrImportant", wintypes.DWORD),
    ]


class _WndClassEx(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.UINT),
        ("style", wintypes.UINT),
        ("lpfnWndProc", ctypes.c_void_p),
        ("cbClsExtra", ctypes.c_int),
        ("cbWndExtra", ctypes.c_int),
        ("hInstance", wintypes.HINSTANCE),
        ("hIcon", wintypes.HANDLE),
        ("hCursor", wintypes.HANDLE),
        ("hbrBackground", wintypes.HANDLE),
        ("lpszMenuName", wintypes.LPCWSTR),
        ("lpszClassName", wintypes.LPCWSTR),
        ("hIconSm", wintypes.HANDLE),
    ]


_WNDPROC = ctypes.WINFUNCTYPE(
    ctypes.c_longlong, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM
)


def _load_font(size: int):  # noqa: ANN201
    for name in ("segoeui.ttf", "arial.ttf", "DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


class Overlay:
    """The orb. `set_state` and `show` are safe to call from any thread."""

    def __init__(self, cfg: dict | None = None) -> None:
        cfg = cfg or {}
        self.enabled = bool(cfg.get("enabled", True)) and sys.platform == "win32"
        self.orb_size = int(cfg.get("size", 58))
        self.margin = int(cfg.get("margin", 28))
        self.opacity = max(0.1, min(1.0, float(cfg.get("opacity", 0.95))))
        self.hold_seconds = float(cfg.get("expand_seconds", 4.0))
        self.position = str(cfg.get("position", "bottom-right"))
        self.max_width = int(cfg.get("max_width", 460))

        self._state = "idle"
        self._caption = ""
        self._caption_until = 0.0
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._hwnd = None

        self._font = _load_font(15)
        # Must outlive the window: Windows would otherwise call freed memory.
        self._wndproc_ref = None

    # ------------------------------------------------------------------ public
    def start(self) -> None:
        if not self.enabled or self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, name="overlay", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def set_state(self, state: str) -> None:
        with self._lock:
            self._state = state

    def show(self, caption: str, seconds: float | None = None) -> None:
        """Display a line of text beside the orb for a few seconds."""
        text = " ".join(str(caption).split())
        with self._lock:
            self._caption = text
            self._caption_until = time.monotonic() + (
                self.hold_seconds if seconds is None else seconds
            )

    # ----------------------------------------------------------------- drawing
    def _snapshot(self) -> tuple[str, str]:
        with self._lock:
            if self._caption and time.monotonic() >= self._caption_until:
                self._caption = ""
            return self._state, self._caption

    def _render(self, state: str, caption: str, phase: float) -> Image.Image:
        color = COLORS.get(state, COLORS["idle"])
        size = self.orb_size
        pad = size // 2  # room for the glow to fade out

        text_width = 0
        if caption:
            probe = Image.new("RGBA", (1, 1))
            box = ImageDraw.Draw(probe).textbbox((0, 0), caption, font=self._font)
            text_width = min(box[2] - box[0] + 34, self.max_width)

        width = size + pad * 2 + text_width
        height = size + pad * 2
        image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)

        orb_left = width - pad - size
        orb_box = (orb_left, pad, orb_left + size, pad + size)

        if caption:
            # Dark rounded plate behind the text so it stays legible on any
            # wallpaper or editor theme.
            plate = (pad - 6, pad + 2, orb_left + size // 2, pad + size - 2)
            draw.rounded_rectangle(plate, radius=(size - 4) // 2, fill=(22, 22, 26, 232))
            draw.text(
                (pad + 8, height // 2),
                caption,
                font=self._font,
                fill=(238, 238, 242, 255),
                anchor="lm",
            )

        # Breathing glow. Recording and busy pulse; resting states barely move.
        speed = {"recording": 2.4, "busy": 3.2, "session": 1.6, "armed": 0.9}.get(state, 0.6)
        depth = {"recording": 0.45, "busy": 0.38, "session": 0.30}.get(state, 0.16)
        pulse = 0.5 + 0.5 * math.sin(phase * speed * 2.0 * math.pi)

        for ring in range(4, 0, -1):
            spread = ring * (2.0 + 14.0 * pulse * depth)
            alpha = int((104.0 * depth / ring) * (0.5 + pulse * 0.5))
            draw.ellipse(
                (
                    orb_box[0] - spread,
                    orb_box[1] - spread,
                    orb_box[2] + spread,
                    orb_box[3] + spread,
                ),
                fill=color + (max(0, min(70, alpha)),),
            )

        draw.ellipse(orb_box, fill=color + (255,))
        # A brighter inner disc keeps the orb reading as lit rather than flat.
        inset = size * (0.30 - 0.24 * pulse * depth)
        highlight = tuple(min(255, int(c * 1.45) + 40) for c in color)
        draw.ellipse(
            (
                orb_box[0] + inset,
                orb_box[1] + inset,
                orb_box[2] - inset,
                orb_box[3] - inset,
            ),
            fill=highlight + (235,),
        )
        return image

    # ------------------------------------------------------------------- win32
    def _run(self) -> None:
        try:
            self._create_window()
        except Exception as exc:
            log.debug("overlay unavailable: %s", exc)
            self.enabled = False
            return

        user32 = ctypes.windll.user32
        msg = wintypes.MSG()
        started = time.monotonic()
        last_frame = 0.0
        topmost_check = 0.0

        while not self._stop.is_set():
            while user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 1):
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))

            now = time.monotonic()
            state, caption = self._snapshot()
            animated = state in ("recording", "busy", "session")
            # Idle costs almost nothing; only animate when there is motion to show.
            interval = (1 / 24) if (animated or caption) else (1 / 4)
            if now - last_frame >= interval:
                last_frame = now
                try:
                    self._paint(self._render(state, caption, now - started))
                except Exception as exc:
                    log.debug("overlay paint failed: %s", exc)
                    break

            # Fullscreen apps and other topmost windows can steal the z-order.
            if now - topmost_check > 2.0:
                topmost_check = now
                try:
                    user32.SetWindowPos(
                        self._hwnd,
                        _HWND_TOPMOST,
                        0,
                        0,
                        0,
                        0,
                        _SWP_NOMOVE | _SWP_NOSIZE | _SWP_NOACTIVATE,
                    )
                except Exception:
                    pass
            time.sleep(0.01)

        try:
            ctypes.windll.user32.DestroyWindow(self._hwnd)
        except Exception:
            pass

    def _create_window(self) -> None:
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32

        # Without an explicit restype the HWND is truncated to 32 bits on x64.
        user32.CreateWindowExW.restype = wintypes.HWND
        user32.CreateWindowExW.argtypes = [
            wintypes.DWORD,
            wintypes.LPCWSTR,
            wintypes.LPCWSTR,
            wintypes.DWORD,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            wintypes.HWND,
            wintypes.HMENU,
            wintypes.HINSTANCE,
            wintypes.LPVOID,
        ]
        user32.DefWindowProcW.restype = ctypes.c_longlong
        # Without argtypes ctypes guesses int for LPARAM and overflows on x64.
        user32.DefWindowProcW.argtypes = [
            wintypes.HWND,
            wintypes.UINT,
            wintypes.WPARAM,
            wintypes.LPARAM,
        ]

        def wndproc(hwnd, message, wparam, lparam):  # noqa: ANN001
            if message == _WM_DESTROY:
                return 0
            return user32.DefWindowProcW(hwnd, message, wparam, lparam)

        self._wndproc_ref = _WNDPROC(wndproc)
        instance = kernel32.GetModuleHandleW(None)
        class_name = f"VoiceVibeOrb{id(self)}"

        wndclass = _WndClassEx()
        wndclass.cbSize = ctypes.sizeof(_WndClassEx)
        wndclass.style = 0
        wndclass.lpfnWndProc = ctypes.cast(self._wndproc_ref, ctypes.c_void_p)
        wndclass.hInstance = instance
        wndclass.lpszClassName = class_name
        if not user32.RegisterClassExW(ctypes.byref(wndclass)):
            raise ctypes.WinError()

        self._hwnd = user32.CreateWindowExW(
            _WS_EX_LAYERED
            | _WS_EX_TRANSPARENT
            | _WS_EX_TOPMOST
            | _WS_EX_TOOLWINDOW
            | _WS_EX_NOACTIVATE,
            class_name,
            "Voice Vibe",
            _WS_POPUP,
            0,
            0,
            10,
            10,
            None,
            None,
            instance,
            None,
        )
        if not self._hwnd:
            raise ctypes.WinError()
        user32.ShowWindow(self._hwnd, _SW_SHOWNOACTIVATE)

    def _origin(self, width: int, height: int) -> tuple[int, int]:
        user32 = ctypes.windll.user32
        screen_w = user32.GetSystemMetrics(0)
        screen_h = user32.GetSystemMetrics(1)
        margin = self.margin
        if self.position == "bottom-left":
            return margin, screen_h - height - margin
        if self.position == "top-right":
            return screen_w - width - margin, margin
        if self.position == "top-left":
            return margin, margin
        return screen_w - width - margin, screen_h - height - margin

    def _paint(self, image: Image.Image) -> None:
        user32 = ctypes.windll.user32
        gdi32 = ctypes.windll.gdi32
        width, height = image.size

        # UpdateLayeredWindow wants premultiplied BGRA.
        rgba = np.asarray(image, dtype=np.uint8)
        alpha = rgba[:, :, 3].astype(np.uint16)
        rgb = (rgba[:, :, :3].astype(np.uint16) * alpha[:, :, None] // 255).astype(np.uint8)
        bgra = np.dstack([rgb[:, :, ::-1], rgba[:, :, 3]])
        if self.opacity < 1.0:
            bgra = (bgra.astype(np.uint16) * self.opacity).astype(np.uint8)
        buffer = np.ascontiguousarray(bgra).tobytes()

        header = _BitmapInfoHeader()
        header.biSize = ctypes.sizeof(_BitmapInfoHeader)
        header.biWidth = width
        header.biHeight = -height  # negative means top-down, matching PIL row order
        header.biPlanes = 1
        header.biBitCount = 32
        header.biCompression = 0

        screen_dc = user32.GetDC(None)
        memory_dc = gdi32.CreateCompatibleDC(screen_dc)
        bits = ctypes.c_void_p()
        bitmap = gdi32.CreateDIBSection(
            memory_dc, ctypes.byref(header), 0, ctypes.byref(bits), None, 0
        )
        if not bitmap:
            gdi32.DeleteDC(memory_dc)
            user32.ReleaseDC(None, screen_dc)
            return
        try:
            ctypes.memmove(bits, buffer, len(buffer))
            old = gdi32.SelectObject(memory_dc, bitmap)

            x, y = self._origin(width, height)
            position = _Point(x, y)
            size = _Size(width, height)
            source = _Point(0, 0)
            blend = _BlendFunction(_AC_SRC_OVER, 0, 255, _AC_SRC_ALPHA)

            user32.UpdateLayeredWindow(
                self._hwnd,
                screen_dc,
                ctypes.byref(position),
                ctypes.byref(size),
                memory_dc,
                ctypes.byref(source),
                0,
                ctypes.byref(blend),
                _ULW_ALPHA,
            )
            gdi32.SelectObject(memory_dc, old)
        finally:
            gdi32.DeleteObject(bitmap)
            gdi32.DeleteDC(memory_dc)
            user32.ReleaseDC(None, screen_dc)
