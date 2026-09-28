"""Run small keyboard and mouse scripts: the hands for spoken commands.

A spec is plain data, so a router, a config table, or a test can build one:

    {"keys": "ctrl+t"}
    {"type_text": "hello"}
    {"click": [x, y]}                 or {"click": {"x", "y", "button", "count"}}
    {"scroll": ["down", 3]}           or {"scroll": {"direction", "amount"}}
    {"sequence": [step, ...]}         a bare list means the same

Any step, sequences included, may also carry:

    "label": "send the email"         what the step is for, in words
    "confirm": true                   ask first; a string is the question itself

A confirmed step is announced and runs only after a spoken yes. Declining, or
not answering in time, raises Cancelled and nothing further runs. Steps before
it have already happened -- that is the point of asking at the dangerous step,
once the user can see what is about to be sent. A step whose label or keys
contain a trigger word ("delete", "send", ...) is confirmed even if the spec
says otherwise, and so is a whole spec whose spoken command does.

The whole spec is parsed and checked before the first key is sent. A typo in
step five must not leave steps one to four done and the app half-driven.

`dry_run=True` records what would happen and touches nothing, which is what
the tests use and what a "show me first" command would use.

Coordinates are screen pixels. The process is per-monitor DPI aware (see
__main__), so they are physical pixels and agree with screen.window_info().
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Union

from .inserter import _MAIN_KEYS, _MODIFIER_KEYS, _MODIFIERS, _resolve_keys

log = logging.getLogger(__name__)

# Bounds on what one spec can do. A spoken command that parses into something
# huge is a bug, and a runaway script at the OS input layer is hard to stop.
MAX_STEPS = 200
MAX_DEPTH = 8
MAX_TEXT = 10_000
MAX_SCROLL = 50
MAX_CLICKS = 3

DEFAULT_CONFIRM_WORDS = ("delete", "uninstall", "send", "buy")
DEFAULT_CONFIRM_TIMEOUT = 8.0

_BUTTONS = ("left", "right", "middle")
# pynput scrolls by (dx, dy) wheel notches; positive dy is up.
_SCROLL = {"up": (0, 1), "down": (0, -1), "left": (-1, 0), "right": (1, 0)}


class ActionError(ValueError):
    """A spec that cannot be run. Raised before anything is sent."""


class Cancelled(Exception):
    """A confirmation was declined or went unanswered; the rest did not run."""

    def __init__(self, prompt: str) -> None:
        super().__init__(f"not confirmed: {prompt}")
        self.prompt = prompt


@dataclass(frozen=True)
class Confirm:
    """A gate before the steps that follow it: ask, and stop unless told yes."""

    prompt: str
    forced_by: str = ""  # the trigger word that required it, if any

    def describe(self) -> str:
        why = f" (said {self.forced_by!r})" if self.forced_by else ""
        return f"confirm {self.prompt!r}{why}"


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


Step = Union[Keys, TypeText, Click, Scroll, Confirm]

# Asked before a step: yes -> run it. Anything else, or an exception, cancels.
Confirmer = Callable[[str, float], bool]


def trigger_pattern(words: Iterable[str]) -> re.Pattern[str] | None:
    """Matches any trigger word anywhere, returning the whole word it is in.

    Deliberately loose: "send" also catches "sending", "sender" and "resend".
    Over-matching costs one extra question; under-matching sends the email.
    """
    cleaned = [str(w).strip().lower() for w in words if str(w).strip()]
    if not cleaned:
        return None
    return re.compile(r"\w*(?:%s)\w*" % "|".join(map(re.escape, cleaned)), re.IGNORECASE)


def _trigger(pattern: re.Pattern[str] | None, *texts: str) -> str:
    if pattern is None:
        return ""
    for text in texts:
        hit = pattern.search(text or "")
        if hit:
            return hit.group(0).lower()
    return ""


def _merge_gates(steps: list[Step]) -> list[Step]:
    """One question, not two in a row, when gates end up adjacent."""
    out: list[Step] = []
    for step in steps:
        if isinstance(step, Confirm) and out and isinstance(out[-1], Confirm):
            prev = out[-1]
            prompt = prev.prompt if step.prompt == prev.prompt else f"{prev.prompt}; {step.prompt}"
            out[-1] = Confirm(prompt, prev.forced_by or step.forced_by)
        else:
            out.append(step)
    return out


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


_OPTIONS = ("label", "confirm")


def parse(spec: Any, triggers: re.Pattern[str] | None = None) -> list[Step]:
    """Flatten a spec into checked steps with Confirm gates, or raise ActionError.

    `triggers` (see trigger_pattern) forces a gate on any step whose label or
    keys mention one of its words, whatever the step's own `confirm` says.
    """
    steps: list[Step] = []
    count = 0

    def walk(node: Any, depth: int) -> None:
        nonlocal count
        if depth > MAX_DEPTH:
            raise ActionError(f"sequences nest deeper than {MAX_DEPTH}")
        if isinstance(node, (list, tuple)):
            node = {"sequence": node}
        if not isinstance(node, dict):
            raise ActionError(f"each step must be a dict, got {node!r}")
        action = {k: v for k, v in node.items() if k not in _OPTIONS}
        if len(action) != 1:
            raise ActionError(f"each step needs exactly one action, got {node!r}")
        (kind, value), = action.items()

        label = node.get("label", "")
        if not isinstance(label, str):
            raise ActionError(f"label must be a string, got {label!r}")
        confirm = node.get("confirm", False)
        if not isinstance(confirm, (bool, str)):
            raise ActionError(f"confirm must be true, false, or a question, got {confirm!r}")

        start = len(steps)
        if kind == "sequence":
            if not isinstance(value, (list, tuple)):
                raise ActionError(f"sequence must be a list, got {value!r}")
            for child in value:
                walk(child, depth + 1)
            covered = [s for s in steps[start:] if not isinstance(s, Confirm)]
            fallback = "; ".join(s.describe() for s in covered[:3])
            fallback += "; ..." if len(covered) > 3 else ""
            keys = ""
        else:
            if kind not in _PARSERS:
                raise ActionError(f"unknown action {kind!r}; expected one of "
                                  f"{('sequence', *_PARSERS)}")
            step = _PARSERS[kind](value)
            count += 1
            if count > MAX_STEPS:
                raise ActionError(f"more than {MAX_STEPS} steps")
            steps.append(step)
            covered = [step]
            fallback = step.describe()
            keys = step.spec if isinstance(step, Keys) else ""

        # An explicit `confirm: false` does not beat a trigger word: the list
        # exists precisely for specs that forgot, or were wrong, to ask.
        forced_by = _trigger(triggers, label, keys)
        if (confirm or forced_by) and covered:
            prompt = confirm.strip() if isinstance(confirm, str) and confirm.strip() else ""
            steps.insert(start, Confirm(prompt or label.strip() or fallback, forced_by))

    walk(spec, 0)
    return _merge_gates(steps)


class Executor:
    """Sends parsed steps through pynput, or only records them.

    `keyboard` and `mouse` are pynput Controllers, created on first use when
    not given. Pass fakes to observe exactly what would be sent.

    `confirmer(prompt, timeout)` is asked at each Confirm gate and must return
    True to go on. With no confirmer, gated steps never run.
    """

    def __init__(
        self,
        dry_run: bool = False,
        keyboard: Any = None,
        mouse: Any = None,
        step_delay: float = 0.05,
        type_delay: float = 0.004,
        confirmer: Confirmer | None = None,
        confirm_words: Iterable[str] = DEFAULT_CONFIRM_WORDS,
        confirm_timeout: float = DEFAULT_CONFIRM_TIMEOUT,
    ) -> None:
        self.dry_run = dry_run
        self._keyboard = keyboard
        self._mouse = mouse
        self.confirmer = confirmer
        self.triggers = trigger_pattern(confirm_words)
        self.confirm_timeout = max(0.0, float(confirm_timeout))
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

    def plan(self, spec: Any, command: str = "") -> list[Step]:
        """The steps `run` would take, gates included, without taking them."""
        steps = parse(spec, self.triggers)
        forced_by = _trigger(self.triggers, command)
        if forced_by:
            # The spoken request names something dangerous but cannot say which
            # step does it, so the whole spec waits for a yes.
            steps = _merge_gates([Confirm(command.strip(), forced_by), *steps])
        return steps

    def run(self, spec: Any, command: str = "") -> list[Step]:
        """Run `spec`, asking at each gate. Returns the steps taken.

        `command` is the spoken request that produced the spec, if any; a
        trigger word in it gates the whole spec. Raises ActionError if the spec
        is invalid (before anything runs) and Cancelled if a gate is refused.
        """
        steps = self.plan(spec, command)
        for index, step in enumerate(steps):
            if self.dry_run:
                log.info("(dry run) %s", step.describe())
            elif isinstance(step, Confirm):
                if not self._confirmed(step):
                    log.info("Cancelled at %s", step.describe())
                    raise Cancelled(step.prompt)
            else:
                if index and self.step_delay:
                    time.sleep(self.step_delay)
                log.debug("action: %s", step.describe())
                self._perform(step)
            self.performed.append(step)
        return steps

    def _confirmed(self, gate: Confirm) -> bool:
        if self.confirmer is None:
            log.warning("%s needs confirming, but there is no way to ask.", gate.describe())
            return False
        log.info("Asking: %s", gate.describe())
        try:
            # `is True`, not truthiness: a confirmer returning something odd
            # is a bug, and a bug must not read as consent.
            return self.confirmer(gate.prompt, self.confirm_timeout) is True
        except Exception:
            log.exception("Confirmation failed; treating it as no.")
            return False

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
