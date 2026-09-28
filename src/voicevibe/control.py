"""Spoken commands aimed at the computer rather than the cursor.

A command is an utterance that *starts* with a prefix word ("computer, open
chrome"). The prefix is the whole gate: speech without it never reaches the
router, so ordinary dictation cannot be intercepted however it is worded. A
prefix anywhere but the start ("the computer is slow") is just dictation.

Commands are global: shortcuts every Windows app honours, plus a few Win32
calls. None of them needs to know which app is in front. Each command is
matched against the *whole* utterance, so "computer copy that paragraph and
paste it below" is not "copy" -- it is unrecognised, and typed as heard.

Every action goes through the executor, so trigger-word confirmation applies
to built-in commands exactly as to anything else.
"""

from __future__ import annotations

import logging
import re
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable

from .actions import MAX_SCROLL, ActionError, Cancelled, Executor, parse
from .wake import _LEADING, _WORD, PhraseMatcher
from .winctl import match_window

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Route:
    """What the router did with one command."""

    handled: bool = False
    caption: str = ""  # shown beside the orb
    # Whether a handled command sends a wake-word session back to armed.
    ends_dictation: bool = False
    speak: str = ""  # said back, for answers that are not an action


NOT_HANDLED = Route()

_NUMBERS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
    "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "fifteen": 15,
    "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50,
    # What Whisper writes for a lone number after a word: "tab to", "tab for".
    "to": 2, "too": 2, "for": 4,
}
_ORDINALS = {
    "first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5, "sixth": 6,
    "seventh": 7, "eighth": 8,
}
_POLITE = re.compile(r"^(?:please|can you|could you|would you)\s+|\s+(?:please|now)$", re.I)
_STOP = re.compile(r"stop(?: scrolling)?|(?:that's )?enough", re.I)
def _number(word: str | None) -> int | None:
    if word is None:
        return None
    word = word.lower()
    if word.isdigit():
        return int(word)
    return _NUMBERS.get(word)


def _clean(command: str) -> str:
    """Whisper's punctuation and politeness off, the words (and case) kept.

    Case survives because "save as Q3 Report" should type "Q3 Report".
    """
    text = command.replace(",", " ").strip().rstrip(".!?;:").strip()
    text = " ".join(text.split())
    previous = None
    while previous != text:
        previous, text = text, _POLITE.sub("", text).strip()
    return text


def _keys(combo: str) -> dict:
    return {"keys": combo}


class Repeater:
    """Runs one spec over and over on its own thread until told to stop.

    Bounded by `limit` seconds, so a "keep scrolling" nobody stops -- the
    speaker walked off, "stop" was misheard -- still ends by itself.
    """

    def __init__(self, executor: Executor, interval: float = 0.12, limit: float = 30.0) -> None:
        self.executor = executor
        self.interval = interval
        self.limit = limit
        self._cancel = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()

    @property
    def running(self) -> bool:
        thread = self._thread
        return thread is not None and thread.is_alive()

    def start(self, spec: Any) -> None:
        self.stop()
        parse(spec)  # fail here, on the caller's thread, not silently inside the loop
        with self._lock:
            cancel = threading.Event()
            self._cancel = cancel
            self._thread = threading.Thread(
                target=self._loop, args=(spec, cancel), name="repeat", daemon=True
            )
            self._thread.start()

    def _loop(self, spec: Any, cancel: threading.Event) -> None:
        deadline = time.monotonic() + self.limit
        try:
            while not cancel.is_set() and time.monotonic() < deadline:
                self.executor.run(spec)
                cancel.wait(self.interval)
        except Exception:
            log.exception("Repeating action failed; stopped.")

    def stop(self) -> bool:
        """Stop and wait for the loop to end. True if something was running."""
        with self._lock:
            thread, self._thread = self._thread, None
            self._cancel.set()
        if thread is None or not thread.is_alive():
            return False
        thread.join(1.0)
        return True


Handler = Callable[[re.Match], Any]


class Router:
    def __init__(
        self,
        cfg: dict | None = None,
        executor: Executor | None = None,
        commands: list[dict] | None = None,
    ) -> None:
        cfg = cfg or {}
        self.enabled = bool(cfg.get("enabled", False))
        # Confirmation of dangerous steps lives in the executor, so no command
        # -- built in or configured -- can skip it.
        self.executor = executor or Executor()
        self.scroll_amount = max(1, min(MAX_SCROLL, int(cfg.get("scroll_amount", 5))))
        self.repeater = Repeater(self.executor, limit=float(cfg.get("keep_scrolling_limit", 30.0)))
        prefixes = cfg.get("prefixes", ["computer"])
        if isinstance(prefixes, str):
            prefixes = [prefixes]
        # Exact words only. A fuzzy prefix would claim "compute the total..."
        # and act on it instead of typing it.
        self.prefix = PhraseMatcher([str(p) for p in prefixes])
        if self.enabled and not self.prefix:
            log.warning("[control].enabled is true but no prefixes are set; disabling.")
            self.enabled = False
        self.user_commands = self._load_user_commands(commands or [])
        self._table = self._build_table()

    # ------------------------------------------------------------ recognising
    def split(self, text: str) -> str | None:
        """The command after a leading prefix, or None if `text` is dictation.

        An empty string means the prefix was said on its own.
        """
        if not self.enabled:
            return None
        span = self.prefix.find(text)
        if span is None or _WORD.search(text[: span[0]]):
            return None
        return text[span[1] :].lstrip(_LEADING)

    def is_stop(self, text: str) -> bool:
        """A "stop" meant for a running repeat, prefixed or not.

        The bare word counts only while something is repeating: that is when
        people say it without thinking, and the only time it is unambiguous.
        """
        if not self.repeater.running:
            return False
        command = self.split(text)
        return bool(_STOP.fullmatch(_clean(text if command is None else command)))

    def stop(self) -> bool:
        return self.repeater.stop()

    @staticmethod
    def _load_user_commands(commands: list[dict]) -> dict[str, dict]:
        """[[commands]] rows, by spoken phrase. They win over built-ins."""
        loaded: dict[str, dict] = {}
        for row in commands:
            say = _clean(str(row.get("say", ""))).lower()
            keys = str(row.get("keys", ""))
            try:
                parse(_keys(keys))
            except ActionError as exc:
                log.warning("[[commands]] %r ignored: %s", say, exc)
                continue
            if say:
                loaded[say] = row
        return loaded

    def _build_table(self) -> list[tuple[re.Pattern[str], Handler]]:
        this = r"(?: (?:it|this|that|the selection))?"
        rules: list[tuple[str, Handler]] = [
            # ------------------------------------------------------ editing
            (r"save(?: (?:it|this|the file|file))?", lambda m: _keys("ctrl+s")),
            (r"save (?:it |this |the file |file )?as(?: (?P<name>.+))?", self._save_as),
            (r"find and replace|replace", lambda m: _keys("ctrl+h")),
            (r"(?:find|search for)(?: (?P<text>.+))?", self._find),
            (r"select (?:all|everything)", lambda m: _keys("ctrl+a")),
            (r"copy" + this, lambda m: _keys("ctrl+c")),
            (r"cut" + this, lambda m: _keys("ctrl+x")),
            (r"paste" + this, lambda m: _keys("ctrl+v")),
            (r"undo" + this, lambda m: _keys("ctrl+z")),
            (r"redo" + this, lambda m: _keys("ctrl+y")),
            (r"(?:make (?:it|this|that) )?bold" + this, lambda m: _keys("ctrl+b")),
            (r"(?:make (?:it|this|that) )?itali(?:c|cs|cize|cise)" + this, lambda m: _keys("ctrl+i")),
            (r"underline" + this, lambda m: _keys("ctrl+u")),
            # No shortcut does this everywhere. Start of line, select through
            # the line break, delete: right in Notepad, Word, browsers and most
            # editors. Map "delete line" in [[commands]] for editors with their
            # own (VS Code: ctrl+shift+k).
            (r"delete (?:the |this )?line",
             lambda m: [_keys("home"), _keys("shift+down"), _keys("delete")]),
            # ------------------------------------------------------ scrolling
            (r"scroll (?P<dir>up|down|left|right)"
             r"(?: (?:by )?(?P<n>\w+)(?: (?:times|notches|clicks|lines))?)?", self._scroll),
            (r"page (?P<dir>up|down)", lambda m: _keys(f"page_{m['dir'].lower()}")),
            (r"(?:go|scroll|jump)(?: (?:up|down))? to (?:the )?(?P<end>top|bottom)"
             r"(?: of (?:the )?(?:page|document|file))?", self._to_end),
            (r"(?P<end>top|bottom) of (?:the )?(?:page|document|file)", self._to_end),
            (r"keep scrolling(?: (?P<dir>up|down))?", self._keep_scrolling),
            (_STOP.pattern, self._stop),
            # ------------------------------------------------------------ tabs
            (r"(?:open )?(?:a )?new tab", lambda m: _keys("ctrl+t")),
            (r"close (?:the |this )?tab", lambda m: _keys("ctrl+w")),
            (r"next tab", lambda m: _keys("ctrl+tab")),
            (r"(?:previous|prev) tab|back a tab", lambda m: _keys("ctrl+shift+tab")),
            (r"(?:go to |switch to )?(?:the )?last tab", lambda m: _keys("ctrl+9")),
            (r"(?:go to |switch to )?tab (?:number )?(?P<n>\w+)", self._tab),
            (r"(?:go to |switch to )?(?:the )?(?P<ord>%s) tab" % "|".join(_ORDINALS), self._tab),
            (r"(?:reopen|restore) (?:the )?(?:last )?(?:closed )?tab|undo close tab",
             lambda m: _keys("ctrl+shift+t")),
            # Chrome, Edge and Firefox: focus the address bar, then open its
            # URL in a new tab.
            (r"duplicate (?:the |this )?tab",
             lambda m: [_keys("alt+d"), {"wait": 0.15}, _keys("alt+enter")]),
            (r"pin (?:the |this )?tab", self._pin_tab),
            # --------------------------------------------------------- windows
            (r"minimi[sz]e(?: (?:the |this )?window)?", lambda m: {"window": "minimize"}),
            (r"maximi[sz]e(?: (?:the |this )?window)?", lambda m: {"window": "maximize"}),
            (r"restore(?: (?:the |this )?window)?", lambda m: {"window": "restore"}),
            (r"snap (?:the |this )?(?:window )?(?:to (?:the )?)?(?P<dir>left|right)",
             lambda m: _keys(f"win+{m['dir'].lower()}")),
            (r"move (?:the |this )?(?:window )?to (?:the )?(?:(?P<dir>left|right)|other|next) "
             r"(?:monitor|screen|display)",
             lambda m: _keys(f"win+shift+{(m['dir'] or 'right').lower()}")),
            (r"show (?:the )?desktop|minimi[sz]e (?:all|everything)", lambda m: _keys("win+d")),
            (r"(?:switch|change) to (?:the )?(?P<name>.+?)(?: window| app)?|"
             r"(?:focus(?: on)?|bring up) (?:the )?(?P<name2>.+?)(?: window| app)?", self._switch),
            # ---------------------------------------------------------- system
            (r"volume (?P<dir>up|down)(?: (?:by )?(?P<n>\w+))?", self._volume),
            (r"turn (?:it|the volume) (?P<dir>up|down)", self._volume),
            (r"(?P<dir>louder|quieter|softer)", self._volume),
            (r"(?:un)?mute(?: (?:the )?(?:sound|audio|volume))?", lambda m: _keys("mute")),
            (r"(?:play|pause|resume)(?: (?:the )?(?:music|media|song|video))?|play pause",
             lambda m: _keys("play_pause")),
            (r"next (?:track|song)|skip(?: (?:this |the )?(?:track|song))?",
             lambda m: _keys("next_track")),
            (r"(?:previous|last) (?:track|song)", lambda m: _keys("previous_track")),
            (r"(?:take a )?screen ?shot|snip(?: the screen)?", lambda m: _keys("win+shift+s")),
            (r"(?:show |open )?(?:the )?clipboard(?: history)?", lambda m: _keys("win+v")),
            (r"lock(?: (?:the )?(?:computer|screen|pc|workstation))?",
             lambda m: {"lock": True, "confirm": "Lock the computer?"}),
        ]
        return [(re.compile(pattern, re.IGNORECASE), handler) for pattern, handler in rules]

    # ----------------------------------------------------------------- routing
    def route(self, command: str) -> Route:
        """Carry out `command` if it is one this router knows."""
        text = _clean(command)
        if not text:
            return NOT_HANDLED

        row = self.user_commands.get(text.lower())
        if row is not None:
            return self._run(_keys(row["keys"]), command, text,
                             ends_dictation=bool(row.get("ends_dictation", False)))

        for pattern, handler in self._table:
            match = pattern.fullmatch(text)
            if not match:
                continue
            result = handler(match)
            if result is None:
                continue  # the words fit but the details did not ("tab banana")
            if isinstance(result, Route):
                return result
            return self._run(result, command, text)
        return NOT_HANDLED

    def _run(self, spec: Any, command: str, caption: str, ends_dictation: bool = False) -> Route:
        # Any other command ends a "keep scrolling": carrying on scrolling
        # after "next tab" would scroll the wrong page.
        self.repeater.stop()
        try:
            self.executor.run(spec, command=command)
        except Cancelled:
            return Route(handled=True, caption="Cancelled")
        except ActionError as exc:
            # A built-in producing a bad spec is a bug here, not something to
            # type into the document.
            log.error("Command %r built an invalid action: %s", command, exc)
            return Route(handled=True, caption="Couldn't do that")
        return Route(handled=True, caption=caption, ends_dictation=ends_dictation)

    # ---------------------------------------------------------------- handlers
    def _save_as(self, m: re.Match) -> Any:
        steps: list[dict] = [_keys("ctrl+shift+s")]
        if m["name"]:
            # The dialog opens with the name field selected, so typing replaces
            # it. Enter is left to the user: the name was just heard, not seen.
            steps += [{"wait": 1.0}, {"type_text": m["name"]}]
        return steps

    def _find(self, m: re.Match) -> Any:
        steps: list[dict] = [_keys("ctrl+f")]
        if m["text"]:
            steps += [{"wait": 0.3}, {"type_text": m["text"]}]
        return steps

    def _scroll(self, m: re.Match) -> Any:
        amount = _number(m["n"]) if m["n"] else self.scroll_amount
        if amount is None or not 1 <= amount <= MAX_SCROLL:
            return None
        return {"scroll": [m["dir"].lower(), amount]}

    @staticmethod
    def _to_end(m: re.Match) -> Any:
        return _keys("ctrl+home" if m["end"].lower() == "top" else "ctrl+end")

    def _keep_scrolling(self, m: re.Match) -> Route:
        direction = (m["dir"] or "down").lower()
        self.repeater.start({"scroll": [direction, 1]})
        return Route(handled=True, caption=f"Scrolling {direction} - say stop")

    def _stop(self, m: re.Match) -> Route:
        stopped = self.repeater.stop()
        return Route(handled=True, caption="Stopped" if stopped else "")

    @staticmethod
    def _tab(m: re.Match) -> Any:
        groups = m.groupdict()
        n = _ORDINALS.get(groups["ord"].lower()) if groups.get("ord") else _number(groups.get("n"))
        if n is None or not 1 <= n <= 8:
            return None  # ctrl+9 is "last tab", not tab nine
        return _keys(f"ctrl+{n}")

    @staticmethod
    def _pin_tab(m: re.Match) -> Route:
        # No browser has a pin shortcut; it lives only in the tab's menu,
        # which needs UI Automation to reach. Say so rather than fake it.
        return Route(handled=True, caption="Can't pin tabs yet",
                     speak="I can't pin tabs yet.")

    def _switch(self, m: re.Match) -> Any:
        name = m["name"] or m["name2"]
        desktop = self.executor.desktop
        target = match_window(name, desktop.windows(), foreground=desktop.foreground())
        if target is None:
            return Route(handled=True, caption=f"No {name} window",
                         speak=f"I don't see {name} open.")
        return {"focus": {"hwnd": target["hwnd"], "title": target["title"]}}

    @staticmethod
    def _volume(m: re.Match) -> Any:
        word = m["dir"].lower()
        up = word in ("up", "louder")
        # Each press is one Windows volume step (2%); five is a noticeable change.
        n = m.groupdict().get("n")
        presses = _number(n) if n else 5
        if presses is None or not 1 <= presses <= 50:
            return None
        return [_keys("volume_up" if up else "volume_down")] * presses

