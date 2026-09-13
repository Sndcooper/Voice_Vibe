"""Wake and sleep phrase detection inside a transcript.

Detection runs on Whisper's output rather than a dedicated wake-word engine.
That costs a transcription per utterance, which is cheap on GPU, and buys two
things worth more than the saving: any phrase works with no model training, and
the wake word can appear in the same breath as the dictation
("arise refactor the login handler enter").

Matching is word-based so punctuation and casing are irrelevant, and so a phrase
never matches inside a longer word.
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher

_WORD = re.compile(r"[\w']+", re.UNICODE)
# Punctuation Whisper tends to leave right after a wake word.
_LEADING = " \t\n,.:;!?-\u2013\u2014"


def _words(text: str) -> list[tuple[str, int, int]]:
    return [(m.group(0).lower(), m.start(), m.end()) for m in _WORD.finditer(text)]


def _phrase_words(phrase: str) -> list[str]:
    return [m.group(0).lower() for m in _WORD.finditer(phrase)]


class PhraseMatcher:
    """Finds any of several word-sequences in a transcript.

    Exact word matching runs first. If `fuzzy` is set, a second pass compares
    letter sequences with word spacing removed, which absorbs the two things
    Whisper actually does to short wake words: splitting them ("a rise" for
    "arise") and swapping a letter or two ("arize", "arisa").
    """

    def __init__(self, phrases: list[str], fuzzy: float = 0.0) -> None:
        self.phrases = [p for p in (_phrase_words(x) for x in phrases) if p]
        # Longest first so "go to sleep" wins over a hypothetical "sleep".
        self.phrases.sort(key=len, reverse=True)
        self.fuzzy = max(0.0, min(1.0, float(fuzzy)))

    def __bool__(self) -> bool:
        return bool(self.phrases)

    def _find_exact(self, tokens: list[tuple[str, int, int]]) -> tuple[int, int, int] | None:
        best: tuple[int, int, int] | None = None  # (start, -length, end)
        for phrase in self.phrases:
            size = len(phrase)
            for i in range(len(tokens) - size + 1):
                if [t[0] for t in tokens[i : i + size]] != phrase:
                    continue
                candidate = (tokens[i][1], -size, tokens[i + size - 1][2])
                if best is None or candidate < best:
                    best = candidate
                break
        return best

    def _close(self, a: str, b: str) -> bool:
        return SequenceMatcher(None, a, b).ratio() >= self.fuzzy

    def _aligns(self, window: list[str], phrase: list[str]) -> bool:
        """Every phrase word has a near-match in the window, in order.

        Deliberately not a similarity score over the concatenated phrase. That
        lets a subset match the whole: bare "computer" scores 0.84 against
        "heycomputer" and would wake on "the computer is slow". Word-by-word
        alignment makes dropping a word impossible.

        One word may be split across two tokens ("a rise" for "arise") or two
        words merged into one, which is the whole reason fuzzy exists.
        """
        want, got = len(phrase), len(window)
        if got == want:
            return all(self._close(w, p) for w, p in zip(window, phrase))
        if got == want + 1:
            for j in range(want):
                merged = window[:j] + [window[j] + window[j + 1]] + window[j + 2 :]
                if all(self._close(w, p) for w, p in zip(merged, phrase)):
                    return True
            return False
        # No shorter-window case. Collapsing two phrase words into one token is
        # something Whisper effectively never does, and allowing it lets a single
        # word match a two-word phrase: "computer" scores 0.84 against
        # "heycomputer", so "the computer is slow" would wake it.
        return False

    def _find_fuzzy(self, tokens: list[tuple[str, int, int]]) -> tuple[int, int, int] | None:
        best: tuple[int, int, int] | None = None
        for phrase in self.phrases:
            want = len(phrase)
            for size in {want, want + 1}:
                if size < 1 or size > len(tokens):
                    continue
                for i in range(len(tokens) - size + 1):
                    window = [t[0] for t in tokens[i : i + size]]
                    if not self._aligns(window, phrase):
                        continue
                    candidate = (tokens[i][1], -size, tokens[i + size - 1][2])
                    if best is None or candidate < best:
                        best = candidate
        return best

    def find(self, text: str) -> tuple[int, int] | None:
        """Character span of the earliest match, or None."""
        tokens = _words(text)
        if not tokens or not self.phrases:
            return None
        hit = self._find_exact(tokens)
        if hit is None and self.fuzzy > 0:
            hit = self._find_fuzzy(tokens)
        if hit is None:
            return None
        return hit[0], hit[2]

    def matches(self, text: str) -> bool:
        return self.find(text) is not None

    def split(self, text: str) -> tuple[bool, str]:
        """Return (matched, whatever followed the phrase).

        Text before the wake word is dropped: it is either room noise or a false
        start, and the user's intent begins at the wake word.
        """
        span = self.find(text)
        if span is None:
            return False, text
        return True, text[span[1] :].lstrip(_LEADING)
