"""Read what is currently on screen, as text.

Four sources, cheapest and most reliable first. Each one degrades to the next,
so this always returns *something* useful even on a bare install:

  1. window title      ctypes, free, always available
  2. selected text     clipboard round-trip, works in nearly every app
  3. UI Automation     exact text of the focused control (optional: comtypes)
  4. OCR               the OS text recogniser (optional: winsdk)

Only 1 and 2 are needed for the common questions ("what is this error?"), and
neither costs a dependency or a model download -- which is the point, because
this has to run on machines with no GPU and little RAM.
"""

from __future__ import annotations

import ctypes
import logging
import sys
import time
from ctypes import wintypes
from dataclasses import dataclass

log = logging.getLogger(__name__)

_SRCCOPY = 0x00CC0020
_PW_CLIENTONLY = 0x00000001
_PW_RENDERFULLCONTENT = 0x00000002
_DWMWA_EXTENDED_FRAME_BOUNDS = 9


def _user32():  # noqa: ANN201
    """user32 with the handle-returning calls correctly typed.

    Without an explicit restype ctypes assumes `int`, which truncates or
    sign-extends an HWND on 64-bit Windows.
    """
    user32 = ctypes.windll.user32
    user32.GetForegroundWindow.restype = wintypes.HWND
    user32.GetDC.restype = wintypes.HDC
    user32.GetDC.argtypes = [wintypes.HWND]
    user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
    user32.PrintWindow.argtypes = [wintypes.HWND, wintypes.HDC, wintypes.UINT]
    user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    user32.GetWindowThreadProcessId.restype = wintypes.DWORD
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    return user32


def _dwmapi():  # noqa: ANN201
    dwmapi = ctypes.windll.dwmapi
    dwmapi.DwmGetWindowAttribute.restype = ctypes.c_long  # HRESULT, checked by hand
    dwmapi.DwmGetWindowAttribute.argtypes = [
        wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD,
    ]
    return dwmapi


def _gdi32():  # noqa: ANN201
    """gdi32 with its handle types declared.

    Every one of these takes or returns a HANDLE. Without argtypes ctypes
    assumes int, and a real 64-bit handle then raises "int too long to
    convert" -- which is a crash, not a graceful failure.
    """
    gdi32 = ctypes.windll.gdi32
    gdi32.CreateCompatibleDC.restype = wintypes.HDC
    gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
    gdi32.CreateCompatibleBitmap.restype = wintypes.HBITMAP
    gdi32.CreateCompatibleBitmap.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int]
    gdi32.SelectObject.restype = wintypes.HGDIOBJ
    gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
    gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
    gdi32.DeleteDC.argtypes = [wintypes.HDC]
    gdi32.BitBlt.argtypes = [
        wintypes.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
        wintypes.HDC, ctypes.c_int, ctypes.c_int, wintypes.DWORD,
    ]
    gdi32.GetDIBits.argtypes = [
        wintypes.HDC, wintypes.HBITMAP, wintypes.UINT, wintypes.UINT,
        ctypes.c_void_p, ctypes.c_void_p, wintypes.UINT,
    ]
    return gdi32


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


@dataclass
class ScreenContext:
    title: str = ""
    selection: str = ""
    element: str = ""
    ocr: str = ""

    @property
    def body(self) -> str:
        """The most specific text available, best source first."""
        return self.selection or self.element or self.ocr or ""

    def __bool__(self) -> bool:
        return bool(self.title or self.body)


def window_title(hwnd=None) -> str:  # noqa: ANN001
    """Title of the foreground window, or of `hwnd` if given."""
    if sys.platform != "win32":
        return ""
    try:
        user32 = _user32()
        hwnd = hwnd or user32.GetForegroundWindow()
        if not hwnd:
            return ""
        length = user32.GetWindowTextLengthW(hwnd)
        buffer = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buffer, length + 1)
        return buffer.value.strip()
    except Exception:
        return ""


def _window_rect(user32, hwnd) -> tuple[int, int, int, int] | None:  # noqa: ANN001
    """Visible bounds of `hwnd` as (left, top, right, bottom) screen pixels.

    GetWindowRect includes the invisible resize borders Windows 10+ draws
    around every window, so the DWM frame bounds are asked for first.
    """
    rect = wintypes.RECT()
    try:
        hr = _dwmapi().DwmGetWindowAttribute(
            hwnd, _DWMWA_EXTENDED_FRAME_BOUNDS, ctypes.byref(rect), ctypes.sizeof(rect)
        )
        if hr == 0:
            return rect.left, rect.top, rect.right, rect.bottom
    except Exception:
        pass
    if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
        return None
    return rect.left, rect.top, rect.right, rect.bottom


def _process_name(pid: int) -> str:
    """Executable name of `pid`, or "" if it is gone or not ours to inspect."""
    if not pid:
        return ""
    try:
        import psutil

        return psutil.Process(pid).name()
    except Exception:
        # ImportError, NoSuchProcess, and AccessDenied (elevated processes) all
        # mean the same thing to a caller: the name is unknown.
        return ""


def window_info(hwnd=None) -> dict | None:  # noqa: ANN001
    """Identity and position of the foreground window, or of `hwnd` if given.

    Returns {"hwnd", "title", "process_name", "rect"}, with rect as
    (left, top, right, bottom), or None when there is no window to describe.
    """
    if sys.platform != "win32":
        return None
    try:
        user32 = _user32()
        hwnd = hwnd or user32.GetForegroundWindow()
        if not hwnd:
            return None
        rect = _window_rect(user32, hwnd)
        if rect is None:
            return None
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        return {
            "hwnd": hwnd,
            "title": window_title(hwnd),
            "process_name": _process_name(pid.value),
            "rect": rect,
        }
    except Exception as exc:
        log.debug("window info failed: %s", exc)
        return None


def selected_text(timeout: float = 0.35) -> str:
    """Whatever is highlighted in the focused app, via a clipboard round-trip.

    Intrusive by nature -- it presses Ctrl+C -- so callers should only reach for
    it when the user asked about something specific on screen. The previous
    clipboard contents are always put back.
    """
    if sys.platform != "win32":
        return ""
    try:
        import pyperclip
        from pynput.keyboard import Controller, Key
    except Exception:
        return ""

    try:
        previous = pyperclip.paste()
    except Exception:
        previous = ""

    sentinel = f"\x00vv{time.monotonic_ns()}"
    try:
        # A sentinel distinguishes "nothing was selected" (clipboard unchanged)
        # from "the selection happens to equal the old clipboard".
        pyperclip.copy(sentinel)
        keyboard = Controller()
        with keyboard.pressed(Key.ctrl):
            keyboard.press("c")
            keyboard.release("c")

        deadline = time.monotonic() + timeout
        grabbed = ""
        while time.monotonic() < deadline:
            time.sleep(0.03)
            current = pyperclip.paste()
            if current != sentinel:
                grabbed = current
                break
        return grabbed.strip()
    except Exception as exc:
        log.debug("selection capture failed: %s", exc)
        return ""
    finally:
        try:
            pyperclip.copy(previous)
        except Exception:
            pass


def focused_element_text() -> str:
    """Text of the focused control via UI Automation. Needs the `screen` extra."""
    if sys.platform != "win32":
        return ""
    try:
        import comtypes.client  # noqa: F401
        from comtypes.gen import UIAutomationClient as UIA
    except Exception:
        return ""
    try:
        import comtypes.client

        automation = comtypes.client.CreateObject(
            "{ff48dba4-60ef-4201-aa87-54103eef594e}",
            interface=UIA.IUIAutomation,
        )
        element = automation.GetFocusedElement()
        if element is None:
            return ""
        for pattern_id, attribute in (
            (UIA.UIA_TextPatternId, "DocumentRange"),
            (UIA.UIA_ValuePatternId, "CurrentValue"),
        ):
            try:
                pattern = element.GetCurrentPattern(pattern_id)
                if pattern is None:
                    continue
                if attribute == "DocumentRange":
                    return str(pattern.DocumentRange.GetText(4000)).strip()
                return str(pattern.CurrentValue).strip()
            except Exception:
                continue
        return str(getattr(element, "CurrentName", "") or "").strip()
    except Exception as exc:
        log.debug("UI Automation unavailable: %s", exc)
        return ""


def capture_window(hwnd=None):  # noqa: ANN001, ANN201
    """Client area of the foreground window as a PIL image. No new dependencies.

    Pixel (0, 0) is the client area's top-left, so client_origin() maps any
    point in the image to the screen.
    """
    if sys.platform != "win32":
        return None
    try:
        from PIL import Image
    except Exception:
        return None

    user32 = _user32()
    gdi32 = _gdi32()
    hwnd = hwnd or user32.GetForegroundWindow()
    if not hwnd:
        return None

    rect = wintypes.RECT()
    if not user32.GetClientRect(hwnd, ctypes.byref(rect)):
        return None
    width, height = rect.right - rect.left, rect.bottom - rect.top
    if width <= 0 or height <= 0:
        return None

    window_dc = user32.GetDC(hwnd)
    memory_dc = gdi32.CreateCompatibleDC(window_dc)
    bitmap = gdi32.CreateCompatibleBitmap(window_dc, width, height)
    try:
        old = gdi32.SelectObject(memory_dc, bitmap)
        # PrintWindow handles layered/DWM-composited windows that BitBlt misses.
        # CLIENTONLY matters: without it the frame is drawn into this
        # client-sized bitmap too, shifting everything by the border width.
        if not user32.PrintWindow(hwnd, memory_dc, _PW_CLIENTONLY | _PW_RENDERFULLCONTENT):
            gdi32.BitBlt(memory_dc, 0, 0, width, height, window_dc, 0, 0, _SRCCOPY)

        buffer = ctypes.create_string_buffer(width * height * 4)
        header = _BitmapInfoHeader()
        header.biSize = ctypes.sizeof(_BitmapInfoHeader)
        header.biWidth = width
        header.biHeight = -height  # negative means top-down
        header.biPlanes = 1
        header.biBitCount = 32
        header.biCompression = 0
        gdi32.GetDIBits(
            memory_dc, bitmap, 0, height, buffer, ctypes.byref(header), 0
        )
        gdi32.SelectObject(memory_dc, old)
        return Image.frombuffer("RGBA", (width, height), buffer, "raw", "BGRA", 0, 1)
    except Exception as exc:
        log.debug("window capture failed: %s", exc)
        return None
    finally:
        gdi32.DeleteObject(bitmap)
        gdi32.DeleteDC(memory_dc)
        user32.ReleaseDC(hwnd, window_dc)


def ocr_image(image) -> str:  # noqa: ANN001
    """Run the OS text recogniser over an image. Needs the `screen` extra.

    Uses the recogniser already built into Windows, so there is no model
    download and no resident memory cost.
    """
    if image is None:
        return ""
    try:
        import asyncio
        import io

        from winsdk.windows.graphics.imaging import BitmapDecoder
        from winsdk.windows.media.ocr import OcrEngine
        from winsdk.windows.storage.streams import DataWriter, InMemoryRandomAccessStream
    except Exception:
        return ""

    async def run() -> str:
        engine = OcrEngine.try_create_from_user_profile_languages()
        if engine is None:
            return ""
        payload = io.BytesIO()
        image.convert("RGB").save(payload, format="PNG")
        stream = InMemoryRandomAccessStream()
        writer = DataWriter(stream.get_output_stream_at(0))
        writer.write_bytes(payload.getvalue())
        await writer.store_async()
        decoder = await BitmapDecoder.create_async(stream)
        bitmap = await decoder.get_software_bitmap_async()
        result = await engine.recognize_async(bitmap)
        return "\n".join(line.text for line in result.lines)

    try:
        return asyncio.run(run()).strip()
    except Exception as exc:
        log.debug("OCR failed: %s", exc)
        return ""


class ScreenReader:
    """Gathers screen context, skipping the expensive sources unless asked."""

    def __init__(self, cfg: dict | None = None) -> None:
        cfg = cfg or {}
        self.enabled = bool(cfg.get("enabled", True)) and sys.platform == "win32"
        self.use_selection = bool(cfg.get("use_selection", True))
        self.use_uia = bool(cfg.get("use_uia", True))
        self.use_ocr = bool(cfg.get("use_ocr", True))
        self.max_chars = int(cfg.get("max_chars", 4000))

    def read(self, deep: bool = False) -> ScreenContext:
        """`deep` permits the intrusive and slow sources (selection, OCR)."""
        if not self.enabled:
            return ScreenContext()

        context = ScreenContext(title=window_title())
        if not deep:
            return context

        if self.use_selection:
            context.selection = selected_text()[: self.max_chars]
        if not context.selection and self.use_uia:
            context.element = focused_element_text()[: self.max_chars]
        if not context.body and self.use_ocr:
            context.ocr = ocr_image(capture_window())[: self.max_chars]
        return context

    @staticmethod
    def available() -> dict[str, bool]:
        """Which optional sources this install can actually use."""
        from importlib.util import find_spec

        def has(name: str) -> bool:
            try:
                return find_spec(name) is not None
            except (ImportError, ValueError):
                return False

        return {"title": sys.platform == "win32", "selection": has("pyperclip"),
                "uia": has("comtypes"), "ocr": has("winsdk")}
