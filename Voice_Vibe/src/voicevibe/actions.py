"""Run small keyboard and mouse scripts: the hands for spoken commands.

A spec is plain data, so a router, a config table, or a test can build one:

    {"keys": "ctrl+t"}
    {"type_text": "hello"}
    {"click": [x, y]}                 or {"click": {"x", "y", "button", "count"}}
    {"scroll": ["down", 3]}           or {"scroll": {"direction", "amount"}}
    {"wait": 0.5}                     seconds, for a dialog to open
    {"window": "minimize"}            or maximize / restore, the front window
    {"focus": hwnd}                   or {"focus": {"hwnd", "title"}}
    {"lock": true}                    lock the workstation
    {"element": {"target": el, "action": "click"}}
                                      a uia.Element; also double_click,
                                      right_click, hover, select, focus
    {"click_named": "Save|Save all"}  or {"click_named": {"name", "action",
                                      "pick": "best|first|last", "types"}};
                                      looked up when the step runs, so it
                                      can find a menu the previous step opened
    {"first_of": [spec, spec, ...]}   the first alternative whose click_named
                                      targets all exist
    {"say": "text"}                   spoken through the system voice
    {"say_clipboard": true}           read the clipboard aloud
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
MAX_WAIT = 10.0
WINDOW_OPS = ("minimize", "maximize", "restore")
POINTER_ACTIONS = ("click", "double_click", "right_click", "hover", "select", "focus")
PICKS = ("best", "first", "last")

DEFAULT_CONFIRM_WORDS = ("delete", "uninstall", "send", "buy")
DEFAULT_CONFIRM_TIMEOUT = 8.0

_BUTTONS = ("left", "right", "middle")
# pynput scrolls by (dx, dy) wheel notches; positive dy is up.
_SCROLL = {"up": (0, 1), "down": (0, -1), "left": (-1, 0), "right": (1, 0)}


class ActionError(ValueError):
    """A spec that cannot be run. Raised before anything is sent."""


class TargetNotFound(Exception):
    """A click_named step found nothing by that name when it came to run."""

    def __init__(self, name: str) -> None:
        super().__init__(f"nothing called {name!r}")
        self.name = name


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


@dataclass(frozen=True)
class Wait:
    seconds: float

    def describe(self) -> str:
        return f"wait {self.seconds:g}s"


@dataclass(frozen=True)
class Window:
    op: str

    def describe(self) -> str:
        return f"{self.op} the window"


@dataclass(frozen=True)
class Focus:
    hwnd: int
    title: str = ""

    def describe(self) -> str:
        return f"switch to {self.title or self.hwnd}"


@dataclass(frozen=True)
class Lock:
    def describe(self) -> str:
        return "lock the computer"


@dataclass(frozen=True)
class ElementAction:
    """Act on something found on screen (a uia.Element or an OCR box)."""

    element: Any
    action: str = "click"

    def describe(self) -> str:
        return f"{self.action.replace('_', ' ')} {self.element.describe()}"


@dataclass(frozen=True)
class ClickNamed:
    """Find an element by name when this step runs, then act on it."""

    names: tuple[str, ...]
    action: str = "click"
    pick: str = "best"
    types: tuple[str, ...] = ()

    def describe(self) -> str:
        return f"{self.action.replace('_', ' ')} {' or '.join(self.names)!r}"


@dataclass(frozen=True)
class FirstOf:
    """Alternatives, tried in order until one finds all its targets."""

    alternatives: tuple[tuple[Any, ...], ...]

    def describe(self) -> str:
        return "first of: " + " / ".join(
            "; ".join(s.describe() for s in alt) for alt in self.alternatives
        )


@dataclass(frozen=True)
class Say:
    text: str = ""
    clipboard: bool = False

    def describe(self) -> str:
        return "read the clipboard aloud" if self.clipboard else f"say {self.text!r}"


Step = Union[Keys, TypeText, Click, Scroll, Wait, Window, Focus, Lock, ElementAction,
             ClickNamed, FirstOf, Say, Confirm]

# Finds the element a ClickNamed step means: (names, types, pick) -> element,
# raising TargetNotFound. The router supplies one bound to the front window.
Resolver = Callable[[tuple, tuple, str], Any]

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


def _parse_wait(value: Any) -> Wait:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ActionError(f"wait must be a number of seconds, got {value!r}")
    if not 0 < value <= MAX_WAIT:
        raise ActionError(f"wait must be above 0 and at most {MAX_WAIT:g}s, got {value}")
    return Wait(float(value))


def _parse_window(value: Any) -> Window:
    if value not in WINDOW_OPS:
        raise ActionError(f"window must be one of {WINDOW_OPS}, got {value!r}")
    return Window(value)


def _parse_focus(value: Any) -> Focus:
    if isinstance(value, dict):
        unknown = set(value) - {"hwnd", "title"}
        if unknown or "hwnd" not in value:
            raise ActionError(f"focus takes hwnd and an optional title, got {value!r}")
        title = value.get("title", "")
        if not isinstance(title, str):
            raise ActionError(f"focus title must be a string, got {title!r}")
        hwnd = _int(value["hwnd"], "focus hwnd")
    else:
        hwnd, title = _int(value, "focus hwnd"), ""
    if hwnd <= 0:
        raise ActionError(f"focus hwnd must be positive, got {hwnd}")
    return Focus(hwnd, title)


def _parse_lock(value: Any) -> Lock:
    if value is not True:
        raise ActionError(f"lock takes true, got {value!r}")
    return Lock()


def _parse_element(value: Any) -> ElementAction:
    if not isinstance(value, dict) or "target" not in value:
        raise ActionError(f"element needs a target, got {value!r}")
    unknown = set(value) - {"target", "action"}
    if unknown:
        raise ActionError(f"element does not take {sorted(unknown)}")
    target = value["target"]
    if not all(hasattr(target, attr) for attr in ("center", "invoke", "describe")):
        raise ActionError(f"element target must be a found element, got {target!r}")
    action = value.get("action", "click")
    if action not in POINTER_ACTIONS:
        raise ActionError(f"element action must be one of {POINTER_ACTIONS}, got {action!r}")
    return ElementAction(target, action)


def _parse_click_named(value: Any) -> ClickNamed:
    if isinstance(value, str):
        value = {"name": value}
    if not isinstance(value, dict) or not isinstance(value.get("name"), str):
        raise ActionError(f"click_named needs a name, got {value!r}")
    unknown = set(value) - {"name", "action", "pick", "types"}
    if unknown:
        raise ActionError(f"click_named does not take {sorted(unknown)}")
    names = tuple(n.strip() for n in value["name"].split("|") if n.strip())
    if not names:
        raise ActionError(f"click_named needs a name, got {value!r}")
    action = value.get("action", "click")
    if action not in POINTER_ACTIONS:
        raise ActionError(f"click_named action must be one of {POINTER_ACTIONS}, got {action!r}")
    pick = value.get("pick", "best")
    if pick not in PICKS:
        raise ActionError(f"click_named pick must be one of {PICKS}, got {pick!r}")
    types = value.get("types", ())
    if isinstance(types, str):
        types = (types,)
    if not isinstance(types, (list, tuple)) or not all(isinstance(t, str) for t in types):
        raise ActionError(f"click_named types must be control type names, got {types!r}")
    return ClickNamed(names, action, pick, tuple(types))


def _parse_say(value: Any) -> Say:
    if not isinstance(value, str) or not value.strip():
        raise ActionError(f"say needs text, got {value!r}")
    return Say(value.strip())


def _parse_say_clipboard(value: Any) -> Say:
    if value is not True:
        raise ActionError(f"say_clipboard takes true, got {value!r}")
    return Say(clipboard=True)


_PARSERS = {
    "keys": _parse_keys,
    "type_text": _parse_type_text,
    "click": _parse_click,
    "scroll": _parse_scroll,
    "wait": _parse_wait,
    "window": _parse_window,
    "focus": _parse_focus,
    "lock": _parse_lock,
    "element": _parse_element,
    "click_named": _parse_click_named,
    "say": _parse_say,
    "say_clipboard": _parse_say_clipboard,
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
        elif kind == "first_of":
            if not isinstance(value, (list, tuple)) or not value:
                raise ActionError(f"first_of must be a non-empty list, got {value!r}")
            # Each alternative is parsed -- and gated -- on its own.
            step = FirstOf(tuple(tuple(parse(alt, triggers)) for alt in value))
            count += sum(len(alt) for alt in step.alternatives)
            if count > MAX_STEPS:
                raise ActionError(f"more than {MAX_STEPS} steps")
            steps.append(step)
            covered = [step]
            fallback = step.describe()
            keys = ""
        else:
            if kind not in _PARSERS:
                raise ActionError(f"unknown action {kind!r}; expected one of "
                                  f"{('sequence', 'first_of', *_PARSERS)}")
            step = _PARSERS[kind](value)
            count += 1
            if count > MAX_STEPS:
                raise ActionError(f"more than {MAX_STEPS} steps")
            steps.append(step)
            covered = [step]
            fallback = step.describe()
            # What a step is *about*, for trigger words: its keys, or the
            # name of what it will click.
            if isinstance(step, Keys):
                keys = step.spec
            elif isinstance(step, ClickNamed):
                keys = " ".join(step.names)
            else:
                keys = ""

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

    `desktop` does the Win32 steps (window, focus, lock); winctl.Desktop by
    default.

    `confirmer(prompt, timeout)` is asked at each Confirm gate and must return
    True to go on. With no confirmer, gated steps never run.

    `resolver` finds click_named targets; `say(text)` speaks. Both are set by
    whoever owns them (the router, the app); without them those steps fail
    as "not found" or are logged.
    """

    def __init__(
        self,
        dry_run: bool = False,
        keyboard: Any = None,
        mouse: Any = None,
        desktop: Any = None,
        step_delay: float = 0.05,
        type_delay: float = 0.004,
        confirmer: Confirmer | None = None,
        confirm_words: Iterable[str] = DEFAULT_CONFIRM_WORDS,
        confirm_timeout: float = DEFAULT_CONFIRM_TIMEOUT,
        resolver: Resolver | None = None,
        say: Callable[[str], Any] | None = None,
    ) -> None:
        self.dry_run = dry_run
        self._keyboard = keyboard
        self._mouse = mouse
        self._desktop = desktop
        self.confirmer = confirmer
        self.resolver = resolver
        self.say = say
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

    @property
    def desktop(self):  # noqa: ANN201
        if self._desktop is None:
            from .winctl import Desktop

            self._desktop = Desktop()
        return self._desktop

    def plan(self, spec: Any, command: str = "") -> list[Step]:
        """The steps `run` would take, gates included, without taking them."""
        forced_by = _trigger(self.triggers, command)
        if not forced_by:
            return parse(spec, self.triggers)
        # The spoken request names something dangerous but cannot say which
        # step does it, so the whole spec waits for a yes. That one yes covers
        # the trigger words inside it too -- "delete line" is asked once, not
        # again at its delete key. Gates the spec asks for itself still stand.
        steps = parse(spec, None)
        return _merge_gates([Confirm(command.strip(), forced_by), *steps])

    def run(self, spec: Any, command: str = "") -> list[Step]:
        """Run `spec`, asking at each gate. Returns the steps taken.

        `command` is the spoken request that produced the spec, if any; a
        trigger word in it gates the whole spec. Raises ActionError if the spec
        is invalid (before anything runs) and Cancelled if a gate is refused.
        """
        steps = self.plan(spec, command)
        self._execute(steps)
        return steps

    def _execute(self, steps: Iterable[Step]) -> None:
        for index, step in enumerate(steps):
            if self.dry_run:
                log.info("(dry run) %s", step.describe())
            elif isinstance(step, Confirm):
                if not self._confirmed(step):
                    log.info("Cancelled at %s", step.describe())
                    raise Cancelled(step.prompt)
            elif isinstance(step, FirstOf):
                self._first_of(step)
            else:
                if index and self.step_delay:
                    time.sleep(self.step_delay)
                log.debug("action: %s", step.describe())
                self._perform(step)
            self.performed.append(step)

    def _first_of(self, step: FirstOf) -> None:
        missing: list[str] = []
        for alternative in step.alternatives:
            try:
                self._execute(alternative)
                return
            except TargetNotFound as exc:
                # Steps before the missing target have run -- "show sidebar"
                # before a "New chat" that still is not there -- which is why
                # alternatives should start with the lookup where they can.
                missing.append(exc.name)
        raise TargetNotFound(missing[-1] if missing else "")

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
            # pynput scrolls wherever the pointer is, so this moves the panel
            # under the mouse -- a sidebar, a preview -- not just the focus.
            dx, dy = _SCROLL[step.direction]
            self.mouse.scroll(dx * step.amount, dy * step.amount)
        elif isinstance(step, Wait):
            time.sleep(step.seconds)
        elif isinstance(step, Window):
            if not self.desktop.show(step.op):
                log.info("Could not %s: no ordinary window in front.", step.op)
        elif isinstance(step, Focus):
            if not self.desktop.focus(step.hwnd):
                log.warning("Windows refused to bring %s forward.", step.describe())
        elif isinstance(step, Lock):
            self.desktop.lock()
        elif isinstance(step, ElementAction):
            self._act(step)
        elif isinstance(step, ClickNamed):
            if self.resolver is None:
                raise TargetNotFound(step.names[0])
            element = self.resolver(step.names, step.types, step.pick)
            self._act(ElementAction(element, step.action))
        elif isinstance(step, Say):
            self._say(step)

    def _say(self, step: Say) -> None:
        text = step.text
        if step.clipboard:
            import pyperclip

            text = pyperclip.paste()
        if not text.strip():
            log.info("Nothing to read aloud.")
        elif self.say is None:
            log.info("(no voice) %s", text[:200])
        else:
            self.say(text)

    def _act(self, step: ElementAction) -> None:
        # A plain click goes through the element's own Invoke/Expand/Select
        # pattern when it has one: no pointer jump, and it works even when
        # something is drawn over the element. Everything else is the mouse.
        if step.action == "click" and step.element.invoke():
            return
        if step.action == "select" and step.element.select():
            return
        if step.action == "focus" and step.element.focus():
            return
        from pynput.mouse import Button

        self.mouse.position = step.element.center
        if step.action == "hover":
            return
        button = Button.right if step.action == "right_click" else Button.left
        self.mouse.click(button, 2 if step.action == "double_click" else 1)

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
