"""Find clickable things in the front window by what they are called.

UI Automation exposes every button, link, tab and menu item an app draws,
with its name and screen rectangle. One cached FindAll pulls the whole list
in a single cross-process call (~0.1s even for a browser); walking the tree
node by node, which is what the `uiautomation` package's Control API does,
costs one call per property per node and takes seconds.

Chromium apps -- Chrome, Edge, VS Code, Claude, Slack -- build their
accessibility tree only once something asks for it, so the first query of
such a window returns just the title-bar buttons. The finder notices a
window it has not seen answering with almost nothing and asks once more.

When UIA has nothing -- games, canvas apps, remote desktops -- OCR boxes from
screen.py stand in, as Elements with no UIA handle behind them.

Needs the `screen` extra (comtypes + uiautomation). Without it every lookup
returns an empty list and callers fall through to OCR, then to dictation.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Any, Iterable

from .launcher import Launcher, _normalize

log = logging.getLogger(__name__)

# Control types a person would click. Order is also the tie-break when two
# elements overlap: a Button inside a ListItem is the one to press.
INTERACTIVE = ("Button", "Hyperlink", "MenuItem", "TabItem", "CheckBox", "ListItem")
LINKS = ("Hyperlink",)
_TYPE_IDS = {
    "Button": 50000, "CheckBox": 50002, "Hyperlink": 50005, "ListItem": 50007,
    "MenuItem": 50011, "TabItem": 50019,
}
_TYPE_NAMES = {v: k for k, v in _TYPE_IDS.items()}
# Words people add that name the kind of thing, not the thing: "the save button".
_TYPE_WORDS = {
    "button": "Button", "link": "Hyperlink", "menu": "MenuItem", "item": None,
    "tab": "TabItem", "checkbox": "CheckBox", "check box": "CheckBox", "option": None,
}
MAX_ELEMENTS = 400
_FEW = 4  # a Chromium window that has not woken up shows only its caption buttons


@dataclass(eq=False)
class Element:
    """One clickable thing, in screen pixels. `ref` is the UIA element, if any."""

    name: str
    control_type: str
    rect: tuple[int, int, int, int]
    ref: Any = field(default=None, repr=False)
    source: str = "uia"  # or "ocr"

    @property
    def center(self) -> tuple[int, int]:
        left, top, right, bottom = self.rect
        return (left + right) // 2, (top + bottom) // 2

    def describe(self) -> str:
        kind = "text" if self.source == "ocr" else self.control_type.lower()
        return f"{self.name or 'unnamed'} {kind}".strip()

    def invoke(self) -> bool:
        """Press it the accessible way. False if it has no suitable pattern.

        Patterns act on the element itself: no pointer movement, and it works
        even when something else is drawn on top.
        """
        if self.ref is None:
            return False
        try:
            import uiautomation as auto

            control = auto.Control.CreateControlFromElement(self.ref)
            if control is None:
                return False
            invoke = control.GetPattern(auto.PatternId.InvokePattern)
            if invoke is not None:
                invoke.Invoke()
                return True
            expand = control.GetPattern(auto.PatternId.ExpandCollapsePattern)
            if expand is not None:
                if expand.ExpandCollapseState == auto.ExpandCollapseState.Collapsed:
                    expand.Expand()
                else:
                    expand.Collapse()
                return True
            select = control.GetPattern(auto.PatternId.SelectionItemPattern)
            if select is not None:
                select.Select()
                return True
            toggle = control.GetPattern(auto.PatternId.TogglePattern)
            if toggle is not None:
                toggle.Toggle()
                return True
        except Exception as exc:
            # A stale element (the page moved on) lands here; the caller
            # falls back to clicking where it was.
            log.debug("UIA pattern failed on %s: %s", self.describe(), exc)
        return False



def _overlaps(a: tuple[int, int, int, int], b: tuple[int, int, int, int]) -> bool:
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def reading_order(elements: Iterable[Element]) -> list[Element]:
    """Top to bottom, then left to right, like reading.

    Badge numbers follow this, so "7" is where a reader expects the seventh.
    Elements whose tops are within a few pixels share a row: fixed-height
    buckets would split a toolbar in two wherever a boundary fell.
    """
    rows: list[list[Element]] = []
    for element in sorted(elements, key=lambda e: (e.rect[1], e.rect[0])):
        if rows and element.rect[1] - rows[-1][0].rect[1] <= 8:
            rows[-1].append(element)
        else:
            rows.append([element])
    return [e for row in rows for e in sorted(row, key=lambda e: e.rect[0])]


def dedupe(elements: Iterable[Element]) -> list[Element]:
    """Drop elements sitting on the same spot as a better one.

    Apps nest a named Button inside a named ListItem; both would get a badge
    and both would match "click inbox". Keep the more clickable one.
    """
    kept: list[Element] = []
    priority = {name: i for i, name in enumerate(INTERACTIVE)}
    ordered = sorted(elements, key=lambda e: priority.get(e.control_type, len(priority)))
    for element in ordered:
        cx, cy = element.center
        if any(abs(cx - k.center[0]) <= 4 and abs(cy - k.center[1]) <= 4 for k in kept):
            continue
        kept.append(element)
    return kept


class Finder:
    """UIA lookups for one window, cached for the length of one command.

    Call `new_command()` as each command starts. Within a command, the second
    lookup -- "click X" retrying with OCR, say -- reuses the first; across
    commands the list is always fresh, because the screen has changed.
    """

    def __init__(self) -> None:
        self._generation = 0
        self._cache: dict[tuple[int, str, int], Any] = {}
        self._seen: set[int] = set()
        self._local = threading.local()
        self._warned = False

    def new_command(self) -> None:
        self._generation += 1
        self._cache.clear()

    def _client(self):  # noqa: ANN202
        """IUIAutomation for this thread. COM objects are per apartment."""
        client = getattr(self._local, "client", None)
        if client is None:
            import comtypes
            import comtypes.client

            try:
                comtypes.CoInitializeEx()
            except OSError:
                pass  # already initialised on this thread
            core = comtypes.client.GetModule("UIAutomationCore.dll")
            ua = comtypes.client.CreateObject(
                "{ff48dba4-60ef-4201-aa87-54103eef594e}", interface=core.IUIAutomation
            )
            client = self._local.client = (ua, core)
        return client

    def elements(self, hwnd: int, types: Iterable[str] = INTERACTIVE) -> list[Element]:
        types = tuple(types)
        key = (hwnd, ",".join(types), self._generation)
        if key not in self._cache:
            self._cache[key] = self._query(hwnd, types)
        return self._cache[key]

    def text(self, hwnd: int) -> Any:
        """OCR of the window with screen-pixel boxes (screen.OcrResult), cached
        like elements(). Two seconds or so, so only reached for when UIA fails.
        """
        key = (hwnd, "ocr", self._generation)
        if key not in self._cache:
            from .screen import ocr_window

            self._cache[key] = ocr_window(hwnd)
        return self._cache[key]

    def _query(self, hwnd: int, types: tuple[str, ...]) -> list[Element]:
        try:
            ua, core = self._client()
        except Exception as exc:
            if not self._warned:
                self._warned = True
                log.warning("UI Automation unavailable (%s); install the screen extra.", exc)
            return []
        try:
            found = self._find_all(ua, core, hwnd, types)
            if len(found) <= _FEW and hwnd not in self._seen:
                # First contact with a Chromium window wakes its tree up.
                time.sleep(0.4)
                found = self._find_all(ua, core, hwnd, types)
            self._seen.add(hwnd)
        except Exception as exc:
            log.debug("UIA query failed for %s: %s", hwnd, exc)
            return []
        return dedupe(found)[:MAX_ELEMENTS]

    @staticmethod
    def _find_all(ua, core, hwnd: int, types: tuple[str, ...]) -> list[Element]:  # noqa: ANN001
        ids = [_TYPE_IDS[t] for t in types if t in _TYPE_IDS]
        condition = ua.CreatePropertyCondition(core.UIA_ControlTypePropertyId, ids[0])
        for type_id in ids[1:]:
            condition = ua.CreateOrCondition(
                condition, ua.CreatePropertyCondition(core.UIA_ControlTypePropertyId, type_id)
            )
        condition = ua.CreateAndCondition(
            condition, ua.CreatePropertyCondition(core.UIA_IsOffscreenPropertyId, False)
        )
        request = ua.CreateCacheRequest()
        for prop in (core.UIA_NamePropertyId, core.UIA_ControlTypePropertyId,
                     core.UIA_BoundingRectanglePropertyId):
            request.AddProperty(prop)

        root = ua.ElementFromHandle(hwnd)
        window = root.CurrentBoundingRectangle
        bounds = (window.left, window.top, window.right, window.bottom)
        found = root.FindAllBuildCache(core.TreeScope_Descendants, condition, request)
        out: list[Element] = []
        for i in range(found.Length if found else 0):
            element = found.GetElement(i)
            r = element.CachedBoundingRectangle
            rect = (r.left, r.top, r.right, r.bottom)
            # Zero-size and scrolled-out elements report as "on screen" too.
            if rect[2] - rect[0] < 2 or rect[3] - rect[1] < 2 or not _overlaps(rect, bounds):
                continue
            out.append(Element(
                name=str(element.CachedName or "").strip(),
                control_type=_TYPE_NAMES.get(element.CachedControlType, "Unknown"),
                rect=rect,
                ref=element,
            ))
        return out


# ----------------------------------------------------------------- matching
def split_kind(spoken: str) -> tuple[str, str | None]:
    """ "the save button" -> ("save", "Button"). The kind is a preference."""
    words = _normalize(spoken).split()
    if words and words[0] == "the":
        words = words[1:]
    for size in (2, 1):
        tail = " ".join(words[-size:])
        if len(words) > size and tail in _TYPE_WORDS:
            return " ".join(words[:-size]), _TYPE_WORDS[tail]
    return " ".join(words), None


def score(spoken: str, name: str) -> float:
    """How well a spoken target fits an element name, 0..1.

    The launcher's scoring (exact > contiguous words > scattered words >
    prefixes > similarity), because the problem is the same: "save" should
    find "Save", "Save As..." should lose to it, "download" should find
    "Downloads".
    """
    wanted, key = _normalize(spoken), _normalize(name)
    if not wanted or not key:
        return 0.0
    if key == wanted:
        return 1.0
    return Launcher._score(key, wanted, wanted.split())


def rank(spoken: str, elements: Iterable[Element], threshold: float = 0.84) -> list[Element]:
    """Elements that fit `spoken`, best first. Empty if none is close enough."""
    target, kind = split_kind(spoken)
    scored = []
    for element in elements:
        s = score(target, element.name)
        if kind and element.control_type == kind:
            s += 0.02  # "the save button" prefers the Button called Save
        if s >= threshold:
            scored.append((s, element))
    # Stable: equal scores keep reading order.
    scored.sort(key=lambda pair: -pair[0])
    return [element for _, element in scored]


def ambiguous(spoken: str, matches: list[Element]) -> bool:
    """Two or more equally good matches of the same kind: a coin toss.

    Same name but different kinds is not ambiguous -- a Save button beats a
    Save menu item, by the INTERACTIVE order -- so that is clicked, with the
    other left for "next one".
    """
    if len(matches) < 2:
        return False
    target, _ = split_kind(spoken)
    top = score(target, matches[0].name)
    second = score(target, matches[1].name)
    return abs(top - second) < 1e-6 and matches[1].control_type == matches[0].control_type


def text_boxes(lines: Iterable[Any], max_words: int = 6) -> list[Element]:
    """Every run of 1..max_words consecutive OCR words in a line, as an Element.

    "click sign in" must find the two words "Sign" "in" as one target, with
    the box around both.
    """
    boxes: list[Element] = []
    for line in lines:
        words = list(line.words)
        for start in range(len(words)):
            for end in range(start + 1, min(len(words), start + max_words) + 1):
                run = words[start:end]
                rect = (min(w.rect[0] for w in run), min(w.rect[1] for w in run),
                        max(w.rect[2] for w in run), max(w.rect[3] for w in run))
                boxes.append(Element(" ".join(w.text for w in run), "Text", rect, source="ocr"))
    return boxes


def rank_text(spoken: str, lines: Iterable[Any], threshold: float = 0.84) -> list[Element]:
    """OCR boxes for `spoken`, best first; the shortest run wins a tie.

    OCR misreads letters ("Sign ln"), so plain similarity counts here more
    than it does for UIA names, which are exact.
    """
    target, _ = split_kind(spoken)
    wanted = _normalize(target)
    scored = []
    for box in text_boxes(lines, max_words=max(1, len(wanted.split()) + 1)):
        s = max(score(target, box.name), SequenceMatcher(None, _normalize(box.name), wanted).ratio())
        if s >= threshold:
            scored.append((s, len(box.name), box))
    scored.sort(key=lambda t: (-t[0], t[1]))
    return [box for *_, box in scored]

