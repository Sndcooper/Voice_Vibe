"""Strict yes / loose no, same rule as Voice Vibe's spoken confirmations.

Yes only when every word is a yes-word ("yes", "yes approve"); any no-word
anywhere means no ("yes no" is no); everything else -- including Whisper's
favourite phantom, "Thank you." -- is undecided and never approves.
"""

from __future__ import annotations

import re

YES_WORDS = frozenset({"yes", "yeah", "yep", "confirm", "confirmed", "approve", "approved"})
NO_PHRASES = ("no", "nope", "cancel", "stop", "deny", "denied", "reject", "don't", "dont",
              "do not", "never mind", "nevermind")


def _normal(text: str) -> str:
    text = (text or "").lower().replace("\u2019", "'")
    return " ".join(re.sub(r"[^a-z' ]+", " ", text).split())


def parse(text: str) -> bool | None:
    """True = yes, False = no, None = anything else."""
    said = _normal(text)
    if not said:
        return None
    padded = f" {said} "
    if any(f" {phrase} " in padded for phrase in NO_PHRASES):
        return False
    if all(word in YES_WORDS for word in said.split()):
        return True
    return None
