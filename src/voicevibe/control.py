"""Spoken commands aimed at the computer rather than the cursor.

A command is an utterance that *starts* with a prefix word ("computer, open
chrome"). The prefix is the whole gate: speech without it never reaches the
router, so ordinary dictation cannot be intercepted however it is worded. A
prefix anywhere but the start ("the computer is slow") is just dictation.

The router itself handles nothing yet. Every command comes back unhandled and
is typed exactly as it was heard, so turning [control] on changes no behaviour
until real commands are added to `Router.route`.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from .wake import _LEADING, _WORD, PhraseMatcher

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Route:
    """What the router did with one command."""

    handled: bool = False
    caption: str = ""  # shown beside the orb
    # Whether a handled command sends a wake-word session back to armed.
    ends_dictation: bool = False


NOT_HANDLED = Route()


class Router:
    def __init__(self, cfg: dict | None = None) -> None:
        cfg = cfg or {}
        self.enabled = bool(cfg.get("enabled", False))
        prefixes = cfg.get("prefixes", ["computer"])
        if isinstance(prefixes, str):
            prefixes = [prefixes]
        # Exact words only. A fuzzy prefix would claim "compute the total..."
        # and, once commands exist, act on it instead of typing it.
        self.prefix = PhraseMatcher([str(p) for p in prefixes])
        if self.enabled and not self.prefix:
            log.warning("[control].enabled is true but no prefixes are set; disabling.")
            self.enabled = False

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

    def route(self, command: str) -> Route:
        """Carry out `command` if it is one this router knows.

        Nothing is known yet, so everything falls through to dictation.
        """
        return NOT_HANDLED
