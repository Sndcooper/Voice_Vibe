"""Decide what a transcript is asking for, and answer it.

There is no language model here, by design. This has to run on a laptop with no
GPU and a few gigabytes of RAM, next to Whisper, without making dictation
slower -- so replies are produced by matching and extraction, not generation.

That buys three things a small local model would not: it is instant, it never
invents an answer, and adding it costs no memory at all.

Anything not recognised falls through to plain dictation, so existing behaviour
is unchanged: the router only ever *adds* responses.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from .launcher import Launcher
from .screen import ScreenContext, ScreenReader

log = logging.getLogger(__name__)

DICTATE = "dictate"
LAUNCH = "launch"
SCREEN = "screen"
CONTROL = "control"

# "open blender", "launch chrome", "start up notepad".
_LAUNCH = re.compile(
    r"^(?:please\s+)?(?:open|launch|start|run|fire)\s+(?:up\s+)?(?:the\s+|my\s+)?(.+)$",
    re.IGNORECASE,
)

# "open terminal and run the tests" / "open notepad, then type hello": the app
# name, then the rest of the request.
_THEN = re.compile(r"\s*(?:,\s*)?\b(?:and then|and|then)\b\s*|\s*,\s+", re.IGNORECASE)

# Nouns that make "open X" an editing instruction rather than an app launch.
# Only consulted when the allowlist has already failed to resolve the name, so
# a real app called "File Explorer" is still launched normally.
_NOT_AN_APP = frozenset(
    """file folder tab window menu door link issue ticket account session
    document page project branch line row cell column""".split()
)

_SCREEN_PATTERNS = (
    # The interrogative is mandatory. Without it, any sentence that merely
    # mentions "the error" -- which dictating about a bug does constantly --
    # would be swallowed instead of typed.
    (re.compile(r"\bwhat(?:'s|s| is| was)?\s+(?:this|that|the)\s+error\b", re.I), "error"),
    (re.compile(r"\b(?:read|explain|describe)\s+(?:me\s+)?(?:this|that|the)\s+error\b", re.I), "error"),
    (re.compile(r"\bwhy (?:is|did|does) (?:it|this|that) (?:fail|failing|break|broken|not work)\b", re.I), "error"),
    (re.compile(r"\b(?:read|say)\s+(?:me\s+)?(?:this|that|it|the\s+selection)\b", re.I), "selection"),
    (re.compile(r"\bwhat does (?:this|that|it) say\b", re.I), "selection"),
    (re.compile(r"\bwhat(?:'s| is) selected\b", re.I), "selection"),
    (re.compile(r"\bwhat(?:'s| is)\s+on\s+(?:my\s+|the\s+)?screen\b", re.I), "screen"),
    (re.compile(r"\bread\s+(?:my\s+|the\s+)?screen\b", re.I), "screen"),
    (re.compile(r"\bwhat am i looking at\b", re.I), "screen"),
    (re.compile(r"\bwhere am i\b", re.I), "window"),
    (re.compile(r"\bwhat(?:'s| is)\s+(?:this|the\s+current)\s+(?:window|app|program)\b", re.I), "window"),
)

_ERROR_HINTS = (
    "error", "exception", "traceback", "failed", "failure", "cannot", "can't",
    "not found", "undefined", "unexpected", "invalid", "denied", "refused",
    "timeout", "missing", "fatal", "panic", "warning",
)

_CAPABILITIES = (
    "I can dictate into any field, open your apps, press keys like enter, "
    "and read what is on your screen."
)


@dataclass
class Reply:
    """What the app should do with one utterance."""

    action: str = DICTATE
    text: str = ""  # text to insert, for the dictate path
    speak: str = ""  # spoken back to the user
    caption: str = ""  # shown beside the orb
    # "open terminal and run the tests": what comes after the launch, handled
    # by the app once the new window is in front.
    follow: str = ""

    @property
    def handled(self) -> bool:
        """True when this was something other than plain dictation."""
        return self.action != DICTATE


def _split_then(target: str) -> tuple[str, str, str]:
    """("terminal", "and", "start the tests") for "terminal and start the tests"."""
    match = _THEN.search(target)
    if not match or match.start() == 0:
        return target, "", ""
    return (target[:match.start()].strip(), match.group(0).strip(),
            target[match.end():].strip(" ,."))


def _sentences(text: str, limit: int = 2, max_chars: int = 240) -> str:
    """Trim extracted text to something worth listening to.

    Reading four thousand characters of OCR aloud is useless, so speech gets
    the first couple of sentences while the orb and the history keep the rest.
    """
    collapsed = " ".join(text.split())
    if not collapsed:
        return ""
    parts = re.split(r"(?<=[.!?])\s+", collapsed)
    out = " ".join(parts[:limit])
    if len(out) > max_chars:
        out = out[:max_chars].rsplit(" ", 1)[0] + "..."
    return out


def _find_error(body: str) -> str:
    """The line in a blob of screen text most likely to be the actual error."""
    lines = [line.strip() for line in body.splitlines() if line.strip()]
    best = ""
    best_score = 0
    for line in lines:
        lowered = line.lower()
        score = sum(2 if hint in lowered else 0 for hint in _ERROR_HINTS)
        # A traceback's last line is the real message; prefer later matches.
        if score and score >= best_score:
            best, best_score = line, score
    return best


class Responder:
    """Routes a transcript and produces the reply for it."""

    def __init__(
        self,
        launcher: Launcher | None = None,
        screen: ScreenReader | None = None,
        cfg: dict | None = None,
    ) -> None:
        cfg = cfg or {}
        self.enabled = bool(cfg.get("enabled", True))
        self.launch_enabled = bool(cfg.get("launch_apps", True))
        self.answer_screen = bool(cfg.get("answer_screen", True))
        self.launcher = launcher
        self.screen = screen

    def respond(self, text: str) -> Reply:
        """Classify one utterance. Falls back to dictation on anything unknown."""
        stripped = text.strip()
        if not self.enabled or not stripped:
            return Reply(action=DICTATE, text=text)

        probe = stripped.rstrip(".!?,;: ")

        if self.answer_screen:
            for pattern, kind in _SCREEN_PATTERNS:
                if pattern.search(probe):
                    return self._answer_screen(kind)

        if re.fullmatch(r"(?:what can you do|help me|what are your commands)", probe, re.I):
            return Reply(action=CONTROL, speak=_CAPABILITIES, caption=_CAPABILITIES)

        if self.launch_enabled and self.launcher is not None:
            match = _LAUNCH.match(probe)
            if match:
                reply = self._maybe_launch(match.group(1).strip(), text)
                if reply is not None:
                    return reply

        return Reply(action=DICTATE, text=text)

    # ---------------------------------------------------------------- handlers
    def _maybe_launch(self, target: str, original: str) -> Reply | None:
        """Launch `target` if it names a known app. None means "not a launch".

        The allowlist decides. Only when it finds nothing do we ask whether the
        phrase looked like an app name at all -- that way "open file explorer"
        still launches, while "open a new tab" goes back to being dictation.
        """
        if not target:
            return None
        # A bare generic noun is an editing instruction: "open the file" asks to
        # open a file, not to launch File Explorer. Multi-word names are fine,
        # so "open file explorer" still resolves normally.
        words = target.lower().split()
        if len(words) == 1 and words[0] in _NOT_AN_APP:
            return None

        entry = self.launcher.resolve(target)
        follow = ""
        if entry is None:
            # "terminal and start the tests": the app name comes first.
            first, _, rest = _split_then(target)
            if rest:
                head = self.launcher.resolve(first) if first else None
                if head is not None:
                    entry, follow = head, rest
        if entry is None:
            if set(target.lower().split()) & _NOT_AN_APP:
                return None
            message = f"I don't know an app called {target}."
            log.info("No allowlisted app matches %r; dictating nothing.", target)
            return Reply(action=CONTROL, speak=message, caption=message)

        started = self.launcher.launch(entry)
        message = (
            f"Opening {entry.name}." if started else f"I couldn't start {entry.name}."
        )
        return Reply(
            action=LAUNCH if started else CONTROL, speak=message, caption=message,
            follow=follow if started else "",
        )

    def _answer_screen(self, kind: str) -> Reply:
        if self.screen is None:
            return Reply(action=CONTROL, speak="I can't read the screen right now.")

        context: ScreenContext = self.screen.read(deep=kind != "window")
        title = context.title or "an untitled window"

        if kind == "window":
            message = f"You're in {title}."
            return Reply(action=SCREEN, speak=message, caption=message)

        body = context.body
        if not body:
            message = f"I can only see the window title: {title}."
            return Reply(action=SCREEN, speak=message, caption=message)

        if kind == "error":
            found = _find_error(body)
            if not found:
                message = f"I don't see an error in {title}."
                return Reply(action=SCREEN, speak=message, caption=message)
            return Reply(action=SCREEN, speak=_sentences(found), caption=found[:400])

        if kind == "selection":
            return Reply(action=SCREEN, speak=_sentences(body), caption=body[:400])

        # kind == "screen": lead with where we are, then what it says.
        summary = _sentences(body, limit=2)
        message = f"{title}. {summary}" if summary else title
        return Reply(action=SCREEN, speak=message, caption=message[:400])
