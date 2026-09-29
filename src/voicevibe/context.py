"""Screen context v2: the bundle (TASK.md §3.3) every hub request carries.

Built from what Voice Vibe already reads -- screen.window_info, the UIA
focused-element text, the clipboard selection and Windows OCR -- plus the
UIA element under the pointer with its ancestors, and a region around the
pointer (or the focus pin, see focus.py):

  shallow (every request)   window, caret_text, pointer_element, region.rect,
                            browser name/title, pinned
  deep (get_context deep)   + selection (a Ctrl+C round trip), region crop
                            PNG in %LOCALAPPDATA%\\VoiceVibe\\crops + its OCR
                            text, browser URL

The shallow bundle also carries `focused_element {name, type, class}` (the
keyboard focus), which the code skill checks before it pastes a prompt.

The hub adds the Windows-MCP region Snapshot / Zen DOM itself (it owns the
MCP client); Voice Vibe never starts a second automation stack.

The privacy guard runs first. If the foreground window, the window under the
pointer, or (deep) any window overlapping the region is blocked, the bundle
is only `{"window": {"process": ...}, "pinned": .., "redacted": true}`: no
title, text, element, OCR or crop is read at all, so nothing can leak.

`LocalScreen` answers the few screen phrases Voice Vibe handles itself, hub
or no hub: focus on my cursor / unfocus / what's this / don't look at this
window / you can look at this window again.
"""

from __future__ import annotations

import logging
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from .focus import FocusPin, Rect
from .privacy import PrivacyGuard

log = logging.getLogger(__name__)

CROP_KEEP_SECONDS = 2 * 86400  # the 2-day retention (rule 15)
MAX_ANCESTORS = 6
_UIA_TYPES = {
    50000: "Button", 50001: "Calendar", 50002: "CheckBox", 50003: "ComboBox", 50004: "Edit",
    50005: "Hyperlink", 50006: "Image", 50007: "ListItem", 50008: "List", 50009: "Menu",
    50010: "MenuBar", 50011: "MenuItem", 50012: "ProgressBar", 50013: "RadioButton",
    50014: "ScrollBar", 50015: "Slider", 50016: "Spinner", 50017: "StatusBar", 50018: "Tab",
    50019: "TabItem", 50020: "Text", 50021: "ToolBar", 50022: "ToolTip", 50023: "Tree",
    50024: "TreeItem", 50025: "Custom", 50026: "Group", 50027: "Thumb", 50028: "DataGrid",
    50029: "DataItem", 50030: "Document", 50031: "SplitButton", 50032: "Window", 50033: "Pane",
    50034: "Header", 50035: "HeaderItem", 50036: "Table", 50037: "TitleBar", 50038: "Separator",
}
_SPOKEN_TYPES = {
    "Button": "button", "SplitButton": "button", "Hyperlink": "link", "Edit": "text box",
    "Document": "document", "TabItem": "tab", "MenuItem": "menu item", "ListItem": "list item",
    "TreeItem": "tree item", "CheckBox": "checkbox", "RadioButton": "option", "ComboBox":
    "drop-down", "Image": "image", "Text": "text", "Slider": "slider", "ToolBar": "toolbar",
    "DataItem": "row", "HeaderItem": "column header", "Tab": "tab strip", "Menu": "menu",
}
BROWSERS = {"msedge.exe": "edge", "zen.exe": "zen", "chrome.exe": "chrome",
            "firefox.exe": "firefox", "brave.exe": "brave", "opera.exe": "opera",
            "vivaldi.exe": "vivaldi"}
_BROWSER_SUFFIX = re.compile(
    r"(?:\s+and\s+\d+\s+more\s+pages?)?(?:\s+-\s+[^-—]+)?\s+[-—]\s+(?:Microsoft[\u200b ]*Edge|"
    r"Zen(?: Browser)?|Google Chrome|Mozilla Firefox|Brave|Opera|Vivaldi)$")
_APP_SUFFIX = re.compile(r".*\s[-—–|]\s")


# ------------------------------------------------------------ win32 reads
def _window() -> dict | None:
    from .screen import window_info

    info = window_info()
    return _slim(info) if info else None


def _slim(info: dict) -> dict:
    return {"hwnd": int(info.get("hwnd") or 0), "title": str(info.get("title") or ""),
            "process": str(info.get("process_name") or info.get("process") or ""),
            "rect": tuple(info.get("rect") or (0, 0, 0, 0))}


def _window_at(point: tuple[int, int]) -> dict | None:
    if sys.platform != "win32":
        return None
    import ctypes
    from ctypes import wintypes

    from .screen import window_info

    user32 = ctypes.windll.user32
    user32.WindowFromPoint.restype = wintypes.HWND
    user32.WindowFromPoint.argtypes = [wintypes.POINT]
    user32.GetAncestor.restype = wintypes.HWND
    user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
    hwnd = user32.WindowFromPoint(wintypes.POINT(*point))
    root = user32.GetAncestor(hwnd, 2) if hwnd else None  # GA_ROOT
    info = window_info(root) if root else None
    return _slim(info) if info else None


def _windows() -> list[dict]:
    from .winctl import top_level_windows

    return [_slim(w) for w in top_level_windows()]


def _pointer() -> tuple[int, int]:
    from .focus import pointer_position

    return pointer_position()


_uia_client: Any = None


def _uia() -> tuple[Any, Any]:
    global _uia_client
    from .uia import Finder

    if _uia_client is None:
        _uia_client = Finder()
    return _uia_client._client()  # per-thread IUIAutomation, shared with click-by-name


def _element_at(point: tuple[int, int]) -> dict | None:
    """The UIA element under `point` and up to MAX_ANCESTORS named ancestors."""
    if sys.platform != "win32":
        return None
    from ctypes import wintypes

    ua, _core = _uia()
    element = ua.ElementFromPoint(wintypes.POINT(*point))
    if element is None:
        return None
    r = element.CurrentBoundingRectangle
    out = {"name": str(element.CurrentName or "").strip()[:200],
           "type": _UIA_TYPES.get(element.CurrentControlType, "Unknown"),
           "rect": [r.left, r.top, r.right, r.bottom], "ancestors": []}
    walker = ua.ControlViewWalker
    parent = walker.GetParentElement(element)
    steps = 0
    while parent is not None and len(out["ancestors"]) < MAX_ANCESTORS and steps < 20:
        steps += 1
        try:
            name = str(parent.CurrentName or "").strip()
            kind = _UIA_TYPES.get(parent.CurrentControlType, "Unknown")
        except Exception:  # noqa: BLE001 - the tree changed under us
            break
        if name:
            out["ancestors"].append({"name": name[:120], "type": kind})
        if kind == "Window" and name:
            break
        parent = walker.GetParentElement(parent)
    return out


def _caret() -> str:
    from .screen import focused_element_text

    return focused_element_text()


def _focused() -> dict | None:
    """Name / control type / class of the element with keyboard focus."""
    if sys.platform != "win32":
        return None
    ua, _core = _uia()
    element = ua.GetFocusedElement()
    if element is None:
        return None
    return {"name": str(element.CurrentName or "").strip()[:200],
            "type": _UIA_TYPES.get(element.CurrentControlType, "Unknown"),
            "class": str(element.CurrentClassName or "")[:80]}


def _selection() -> str:
    from .screen import selected_text

    return selected_text()


def _grab(rect: Rect) -> Any:
    from PIL import ImageGrab

    return ImageGrab.grab(bbox=rect, all_screens=True)


def _ocr(image: Any) -> str:
    from .screen import ocr_image

    return ocr_image(image).text


def _browser_url(hwnd: int) -> str:
    """The address bar's text (Edge: "Address and search bar"; Zen/Firefox:
    the urlbar edit), via one cached UIA FindAll for Edit controls."""
    from .uia import Finder

    finder = Finder()
    for element in finder.elements(hwnd, types=("Edit",)):
        if re.search(r"address|search or enter|url", element.name, re.I) and element.ref:
            try:
                ua, core = finder._client()
                pattern = element.ref.GetCurrentPattern(core.UIA_ValuePatternId)
                value = pattern.QueryInterface(core.IUIAutomationValuePattern).CurrentValue
                return str(value or "").strip()
            except Exception as exc:  # noqa: BLE001
                log.debug("address bar read failed: %s", exc)
    return ""


def crops_dir() -> Path:
    from .history import data_dir

    return data_dir() / "crops"


def purge_crops(folder: Path | None = None, now: float | None = None,
                keep: float = CROP_KEEP_SECONDS) -> int:
    """Delete crop PNGs older than `keep`. Returns how many went."""
    folder = folder or crops_dir()
    now = time.time() if now is None else now
    gone = 0
    for path in Path(folder).glob("crop-*.png") if Path(folder).is_dir() else ():
        try:
            if now - path.stat().st_mtime > keep:
                path.unlink()
                gone += 1
        except OSError:
            continue
    return gone


def _overlaps(a: Rect, b: Rect) -> bool:
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


# ---------------------------------------------------------------- builder
class ContextBuilder:
    def __init__(self, cfg: dict | None = None, *, guard: PrivacyGuard | None = None,
                 pin: FocusPin | None = None,
                 window: Callable[[], dict | None] = _window,
                 window_at: Callable[[tuple[int, int]], dict | None] = _window_at,
                 windows: Callable[[], list[dict]] = _windows,
                 pointer: Callable[[], tuple[int, int]] = _pointer,
                 element_at: Callable[[tuple[int, int]], dict | None] = _element_at,
                 caret: Callable[[], str] = _caret,
                 focused: Callable[[], dict | None] = _focused,
                 selection: Callable[[], str] = _selection,
                 grab: Callable[[Rect], Any] = _grab,
                 ocr: Callable[[Any], str] = _ocr,
                 browser_url: Callable[[int], str] = _browser_url,
                 crops_dir: Path | None = None,
                 clock: Callable[[], float] = time.time) -> None:
        cfg = cfg or {}
        self.enabled = bool(cfg.get("enabled", True))
        self.use_selection = bool(cfg.get("use_selection", True))
        self.use_uia = bool(cfg.get("use_uia", True))
        self.use_ocr = bool(cfg.get("use_ocr", True))
        self.max_chars = int(cfg.get("max_chars", 4000))
        size = cfg.get("region_size") or (800, 500)
        self.guard = guard or PrivacyGuard(cfg)
        self.pin = pin or FocusPin(seconds=float(cfg.get("focus_seconds", 180)),
                                   size=(int(size[0]), int(size[1])))
        self.window, self.window_at, self.windows = window, window_at, windows
        self.pointer, self.element_at, self.caret = pointer, element_at, caret
        self.focused = focused
        self.selection, self.grab, self.ocr, self.browser_url = selection, grab, ocr, browser_url
        self._crops = crops_dir
        self.clock = clock

    @property
    def crops(self) -> Path:
        return self._crops or crops_dir()

    def warm(self) -> None:
        """Pay the one-time UIA/COM setup (~1 s) now, e.g. on a thread at start."""
        point = self._try("pointer", self.pointer, default=(0, 0))
        self._try("pointer element", self.element_at, point)
        self._try("caret", self.caret)

    def _try(self, what: str, fn: Callable, *args: Any, default: Any = None) -> Any:
        try:
            return fn(*args)
        except Exception as exc:  # noqa: BLE001 - one broken source must not sink the bundle
            log.debug("context %s failed: %s", what, exc)
            return default

    def _cap(self, text: Any) -> str:
        return str(text or "").strip()[: self.max_chars]

    def bundle(self, deep: bool = False, pin: bool | None = None) -> dict:
        """The §3.3 bundle. `pin` True/False pins / unpins first."""
        if pin is True:
            self.pin.pin()
        elif pin is False:
            self.pin.unpin()
        pinned_rect = self.pin.current()
        bundle: dict[str, Any] = {"pinned": pinned_rect is not None, "redacted": False}
        if not self.enabled:
            return bundle

        front = self._try("window", self.window) or {}
        point = self._try("pointer", self.pointer, default=(0, 0))
        region = pinned_rect or self._try("region", self.pin.region_at_pointer)
        under = self._try("window at pointer", self.window_at, point)
        checked = [front, under]
        if deep and region:
            checked += [w for w in (self._try("windows", self.windows, default=[]) or [])
                        if _overlaps(tuple(w.get("rect") or (0, 0, 0, 0)), region)]
        verdict = self.guard.check_any(checked)
        if verdict.blocked:
            log.info("Context redacted: %s", verdict.reason)
            bundle["window"] = {"process": str(front.get("process") or "")}
            bundle["redacted"] = True
            return bundle

        bundle["window"] = {"hwnd": int(front.get("hwnd") or 0),
                            "title": str(front.get("title") or ""),
                            "process": str(front.get("process") or "")}
        bundle["caret_text"] = self._cap(self._try("caret", self.caret, default="")) \
            if self.use_uia else ""
        bundle["selection"] = ""
        if self.use_uia:
            element = self._try("pointer element", self.element_at, point)
            if element:
                bundle["pointer_element"] = element
            focused = self._try("focused element", self.focused)
            if focused:
                bundle["focused_element"] = focused
        if region:
            bundle["region"] = {"rect": list(region), "image_ref": None}
        browser = BROWSERS.get(bundle["window"]["process"].lower())
        if browser:
            title = _BROWSER_SUFFIX.sub("", bundle["window"]["title"]).strip()
            bundle["browser"] = {"name": browser, "title": title, "dom_text": None}

        if deep:
            if self.use_selection:
                bundle["selection"] = self._cap(self._try("selection", self.selection, default=""))
            if region:
                self._add_crop(bundle["region"], region)
            if browser and bundle["window"]["hwnd"]:
                url = self._try("browser url", self.browser_url, bundle["window"]["hwnd"],
                                default="")
                if url:
                    bundle["browser"]["url"] = url
        return bundle

    def _add_crop(self, part: dict, region: Rect) -> None:
        image = self._try("grab", self.grab, tuple(region))
        if image is None:
            return
        try:
            self.crops.mkdir(parents=True, exist_ok=True)
            path = self.crops / f"crop-{int(self.clock() * 1000)}.png"
            image.save(path, format="PNG")
            part["image_ref"] = str(path)
        except Exception as exc:  # noqa: BLE001
            log.debug("crop save failed: %s", exc)
        if self.use_ocr:
            part["ocr_text"] = self._cap(self._try("ocr", self.ocr, image, default=""))


# ------------------------------------------------------------ local phrases
@dataclass
class LocalReply:
    speak: str
    caption: str = ""
    action: str = "screen"


def _norm(text: str) -> str:
    text = re.sub(r"[^\w\s']", " ", (text or "").lower().replace("\u2019", "'"))
    return " ".join(text.split())


FOCUS = {"focus on my cursor", "focus on the cursor", "focus on my mouse", "focus on the mouse",
         "focus here", "focus on this", "focus on this area", "pin this", "pin this area",
         "look here"}
UNFOCUS = {"unfocus", "un focus", "stop focusing", "clear focus", "clear the focus", "unpin",
           "unpin this", "focus off", "forget the focus"}
WHATS_THIS = {"what's this", "whats this", "what is this", "what's that", "what is that",
              "what am i pointing at", "what's under my cursor", "what is under my cursor",
              "what's under my mouse", "what is under my mouse"}
PRIVATE = {"don't look at this window", "do not look at this window", "dont look at this window",
           "keep this window private", "this window is private", "mark this window private",
           "ignore this window"}
UNPRIVATE = {"you can look at this window", "you can look at this window again",
             "stop ignoring this window", "unmark this window", "this window isn't private"}


def app_name(title: str) -> str:
    """ "main.py - uBipedal - Visual Studio Code" -> "Visual Studio Code"."""
    tail = _APP_SUFFIX.sub("", title or "").strip()
    return tail.replace("\u200b", "")


def describe_element(element: dict | None, app: str) -> str:
    if not element:
        return ""
    kind = _SPOKEN_TYPES.get(str(element.get("type") or ""), "")
    name = str(element.get("name") or "").strip()
    parts = []
    if name:
        parts.append(f"{name} {kind}".strip())
    elif kind:
        parts.append(f"A {kind}")
    else:
        return ""
    for ancestor in element.get("ancestors") or []:
        if ancestor.get("type") == "Window" or ancestor.get("name") == name:
            continue
        parts.append(f"in {ancestor['name']}")
        break
    if app:
        parts.append(app)
    return ", ".join(parts) + "."


class LocalScreen:
    retry_delay = 0.35

    def __init__(self, context: ContextBuilder) -> None:
        self.context = context

    def handle(self, command: str) -> LocalReply | None:
        said = _norm(command)
        if said in FOCUS:
            self.context.pin.pin()
            seconds = int(self.context.pin.seconds)
            return LocalReply(f"Focused here for {seconds // 60 or 1} minutes.", "Focused")
        if said in UNFOCUS:
            had = self.context.pin.unpin()
            return LocalReply("Focus off." if had else "Nothing was focused.", "Unfocused")
        if said in PRIVATE:
            window = self.context._try("window", self.context.window)
            if not window or not self.context.guard.mark(window):
                return LocalReply("I can't tell which window that is.")
            return LocalReply("Okay, I won't look at this window.", "Private window")
        if said in UNPRIVATE:
            window = self.context._try("window", self.context.window) or {}
            lifted = self.context.guard.unmark(window)
            still = self.context.guard.check(window).blocked
            if still:
                return LocalReply("That window stays private.")
            return LocalReply("Okay, I can look at it again." if lifted else
                              "I wasn't ignoring this window.")
        if said in WHATS_THIS:
            return self._whats_this()
        return None

    def _whats_this(self) -> LocalReply:
        b = self.context.bundle()
        if b.get("redacted"):
            return LocalReply("That window is private, so I won't look.")
        app = app_name((b.get("window") or {}).get("title", ""))
        text = describe_element(b.get("pointer_element"), app)
        if not text and b.get("pointer_element"):
            # Chromium builds its accessibility tree on first contact (see
            # uia.py); a second look a moment later usually names the element.
            time.sleep(self.retry_delay)
            point = self.context._try("pointer", self.context.pointer, default=(0, 0))
            text = describe_element(self.context._try("element", self.context.element_at, point),
                                    app)
        if not text:
            deep = self.context.bundle(deep=True)
            ocr = ((deep.get("region") or {}).get("ocr_text") or "").strip().splitlines()
            text = f"It says: {ocr[0][:160]}" if ocr else f"I can't tell. You're in {app or 'an app'}."
        return LocalReply(text, text[:120])
