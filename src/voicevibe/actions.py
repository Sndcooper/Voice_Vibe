"""Run small keyboard and mouse scripts: the hands for spoken commands.

A spec is plain data, so a router, a config table, or a test can build one:

    {"keys": "ctrl+t"}
    {"type_text": "hello"}
    {"click": [x, y]}                 or {"click": {"x", "y", "button", "count"}}
    {"scroll": ["down", 3]}           or {"scroll": {"direction", "amount"}}
    {"sequence": [step, ...]}         a bare list means the same

The whole spec is parsed and checked before the first key is sent. A typo in
step five must not leave steps one to four done and the app half-driven.

`dry_run=True` records what would happen and touches nothing, which is what
the tests use and what a "show me first" command would use.

Coordinates are screen pixels. The process is per-monitor DPI aware (see
__main__), so they are physical pixels and agree with screen.window_info().
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any, Union

from .inserter import _MAIN_KEYS, _MODIFIER_KEYS, _MODIFIERS, _resolve_keys

log = logging.getLogger(__name__)

# Bounds on what one spec can do. A spoken command that parses into something
# huge is a bug, and a runaway script at the OS input layer is hard to stop.
MAX_STEPS = 200
MAX_DEPTH = 8
MAX_TEXT = 10_000
MAX_SCROLL = 50
MAX_CLICKS = 3

_BUTTONS = ("left", "right", "middle")
# pynput scrolls by (dx, dy) wheel notches; positive dy is up.
_SCROLL = {"up": (0, 1), "down": (0, -1), "left": (-1, 0), "right": (1, 0)}


class ActionError(ValueError):
    """A spec that cannot be run. Raised before anything is sent."""


@dataclass(frozen=True)
class Keys:
    spec: str

    def describe(self) -> str:
        return f"keys {self.spec}"


@dataclass(frozen=True)
class TypeText:
    text: str

    def describe(self) -> str:
        preview = self.text if len(self.text) <= 40 else self.text[:37] + "..."
        return f"type {preview!r}"


@dataclass(frozen=True)
class Click:
    x: int
    y: int
    button: str = "left"
    count: int = 1

    def describe(self) -> str:
        times = "" if self.count == 1 else f" x{self.count}"
        return f"click {self.button} at ({self.x}, {self.y}){times}"


@dataclass(frozen=True)
class Scroll:
    direction: str
    amount: int = 1

    def describe(self) -> str:
        return f"scroll {self.direction} {self.amount}"


Step = Union[Keys, TypeText, Click, Scroll]


def _int(value: Any, what: str) -> int:
    # bool is an int subclass; {"click": [True, 5]} is a bug, not (1, 5).
    if isinstance(value, bool) or not isinstance(value, int):
        raise ActionError(f"{what} must be an integer, got {value!r}")
    return value


def _parse_keys(value: Any) -> Keys:
    if not isinstance(value, str) or not value.strip():
        raise ActionError(f"keys must be a combo like 'ctrl+t', got {value!r}")
    # _resolve_keys skips names it does not know, which would quietly turn
    # "ctrl+foo+t" into ctrl+t. Here every part has to mean something.
    tokens = [t.strip().lower() for t in value.split("+")]
    mains = [t for t in tokens if t not in _MODIFIER_KEYS]
    for token in tokens:
        if not token or not (token in _MODIFIER_KEYS or token in _MAIN_KEYS or len(token) == 1):
            raise ActionError(f"unknown key {token!r} in {value!r}")
    if len(mains) != 1:
        raise ActionError(f"{value!r} needs exactly one non-modifier key")
    return Keys("+".join(tokens))


def _parse_type_text(value: Any) -> TypeText:
    if not isinstance(value, str) or not value:
        raise ActionError(f"type_text must be a non-empty string, got {value!r}")
    if len(value) > MAX_TEXT:
        raise ActionError(f"type_text is {len(value)} characters; the limit is {MAX_TEXT}")
    return TypeText(value)


def _parse_click(value: Any) -> Click:
    if isinstance(value, (list, tuple)) and len(value) == 2:
        value = {"x": value[0], "y": value[1]}
    if not isinstance(value, dict) or "x" not in value or "y" not in value:
        raise ActionError(f"click needs [x, y] or {{'x': .., 'y': ..}}, got {value!r}")
    unknown = set(value) - {"x", "y", "button", "count"}
    if unknown:
        raise ActionError(f"click does not take {sorted(unknown)}")
    button = value.get("button", "left")
    if button not in _BUTTONS:
        raise ActionError(f"click button must be one of {_BUTTONS}, got {button!r}")
    count = _int(value.get("count", 1), "click count")
    if not 1 <= count <= MAX_CLICKS:
        raise ActionError(f"click count must be 1 to {MAX_CLICKS}, got {count}")
    # Negative coordinates are real: a monitor left of or above the primary.
    return Click(_int(value["x"], "click x"), _int(value["y"], "click y"), button, count)


def _parse_scroll(value: Any) -> Scroll:
    if isinstance(value, str):
        value = {"direction": value}
    elif isinstance(value, (list, tuple)) and len(value) == 2:
        value = {"direction": value[0], "amount": value[1]}
    if not isinstance(value, dict) or "direction" not in value:
        raise ActionError(f"scroll needs [direction, amount], got {value!r}")
    unknown = set(value) - {"direction", "amount"}
    if unknown:
        raise ActionError(f"scroll does not take {sorted(unknown)}")
    direction = str(value["direction"]).lower()
    if direction not in _SCROLL:
        raise ActionError(f"scroll direction must be one of {tuple(_SCROLL)}, got {direction!r}")
    amount = _int(value.get("amount", 1), "scroll amount")
    if not 1 <= amount <= MAX_SCROLL:
        raise ActionError(f"scroll amount must be 1 to {MAX_SCROLL}, got {amount}")
    return Scroll(direction, amount)


_PARSERS = {
    "keys": _parse_keys,
    "type_text": _parse_type_text,
    "click": _parse_click,
    "scroll": _parse_scroll,
}


def parse(spec: Any) -> list[Step]:
    """Flatten a spec into checked steps, or raise ActionError."""
    steps: list[Step] = []

    def walk(node: Any, depth: int) -> None:
        if depth > MAX_DEPTH:
            raise ActionError(f"sequences nest deeper than {MAX_DEPTH}")
        if isinstance(node, (list, tuple)):
            node = {"sequence": node}
        if not isinstance(node, dict) or len(node) != 1:
            raise ActionError(f"each step needs exactly one action, got {node!r}")
        (kind, value), = node.items()
        if kind == "sequence":
            if not isinstance(value, (list, tuple)):
                raise ActionError(f"sequence must be a list, got {value!r}")
            for child in value:
                walk(child, depth + 1)
            return
        if kind not in _PARSERS:
            raise ActionError(f"unknown action {kind!r}; expected one of "
                              f"{('sequence', *_PARSERS)}")
        steps.append(_PARSERS[kind](value))
        if len(steps) > MAX_STEPS:
            raise ActionError(f"more than {MAX_STEPS} steps")

    walk(spec, 0)
    return steps


class Executor:
    """Sends parsed steps through pynput, or only records them.

    `keyboard` and `mouse` are pynput Controllers, created on first use when
    not given. Pass fakes to observe exactly what would be sent.
    """

    def __init__(
        self,
        dry_run: bool = False,
        keyboard: Any = None,
        mouse: Any = None,
        step_delay: float = 0.05,
        type_delay: float = 0.004,
    ) -> None:
        self.dry_run = dry_run
        self._keyboard = keyboard
        self._mouse = mouse
        # Apps need a beat between steps: ctrl+l then typing, with no gap,
        # types into the old focus.
        self.step_delay = max(0.0, float(step_delay))
        self.type_delay = max(0.0, float(type_delay))
        self.performed: list[Step] = []

    @property
    def keyboard(self):  # noqa: ANN201
        if self._keyboard is None:
            from pynput.keyboard import Controller

            self._keyboard = Controller()
        return self._keyboard

    @property
    def mouse(self):  # noqa: ANN201
        if self._mouse is None:
            from pynput.mouse import Controller

            self._mouse = Controller()
        return self._mouse

    def run(self, spec: Any) -> list[Step]:
        """Run `spec`. Returns the steps taken; raises ActionError if invalid."""
        steps = parse(spec)
        for index, step in enumerate(steps):
            if self.dry_run:
                log.info("(dry run) %s", step.describe())
            else:
                if index and self.step_delay:
                    time.sleep(self.step_delay)
                log.debug("action: %s", step.describe())
                self._perform(step)
            self.performed.append(step)
        return steps

    def _perform(self, step: Step) -> None:
        if isinstance(step, Keys):
            self._press(step.spec)
        elif isinstance(step, TypeText):
            self._type(step.text)
        elif isinstance(step, Click):
            from pynput.mouse import Button

            self.mouse.position = (step.x, step.y)
            self.mouse.click(getattr(Button, step.button), step.count)
        elif isinstance(step, Scroll):
            dx, dy = _SCROLL[step.direction]
            self.mouse.scroll(dx * step.amount, dy * step.amount)

    def _release_modifiers(self) -> None:
        # A hotkey modifier still held turns "t" into ctrl+alt+t.
        for key in _MODIFIERS:
            try:
                self.keyboard.release(key)
            except Exception:
                pass

    def _press(self, spec: str) -> None:
        modifiers, main = _resolve_keys(spec)
        self._release_modifiers()
        for modifier in modifiers:
            self.keyboard.press(modifier)
        try:
            self.keyboard.press(main)
            self.keyboard.release(main)
        finally:
            for modifier in reversed(modifiers):
                self.keyboard.release(modifier)

    def _type(self, text: str) -> None:
        from pynput.keyboard import Key

        self._release_modifiers()
        for char in text:
            if char == "\n":
                self.keyboard.tap(Key.enter)
            else:
                self.keyboard.type(char)
            if self.type_delay:
                time.sleep(self.type_delay)
