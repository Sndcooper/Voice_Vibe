"""Ask out loud before a dangerous action, and wait for a spoken yes.

Wiring matters here. The executor runs on the worker thread -- the same thread
that transcribes every utterance -- so waiting for "the next job" would wait
on itself forever. Instead, while a question is open the app hands each
session utterance straight to `offer()`, and the waiting call transcribes it
itself. The worker is blocked anyway, so nothing else is using the model.

Consent has to be unambiguous, so the rules are lopsided:

  - yes means the *whole* utterance is yes-words ("yes", "Yes, confirm.").
    "yes but not that one" is not yes.
  - no means any no-word anywhere. Cancelling by mistake is cheap.
  - anything else -- room noise, a colleague, the question itself coming back
    through the speakers -- is ignored, and the clock keeps running.
  - silence until the deadline is no.
"""

from __future__ import annotations

import logging
import queue
import re
import threading
import time
from typing import Any, Callable, Iterable

log = logging.getLogger(__name__)

DEFAULT_YES = ("yes", "confirm")
DEFAULT_NO = ("no", "cancel", "stop", "never mind")

_WORD = re.compile(r"[\w']+")


def _normal(text: str) -> str:
    return " ".join(_WORD.findall(str(text).lower()))


class VoiceConfirmer:
    """A Confirmer (see actions) that speaks, shows, and listens.

    `transcribe(audio) -> str` turns an offered utterance into text.
    `say(text)` should block until spoken, so the question is not heard as
    its own answer. `show(text)` puts the question on screen.
    `listening()` says whether any answer can arrive at all; if not, there is
    no point waiting out the timeout.
    """

    def __init__(
        self,
        transcribe: Callable[[Any], str],
        say: Callable[[str], Any] | None = None,
        show: Callable[[str], Any] | None = None,
        listening: Callable[[], bool] | None = None,
        yes_words: Iterable[str] = DEFAULT_YES,
        no_words: Iterable[str] = DEFAULT_NO,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.transcribe = transcribe
        self.say = say or (lambda text: None)
        self.show = show or (lambda text: None)
        self.listening = listening or (lambda: True)
        self.yes = {_normal(w) for w in yes_words if _normal(w)}
        self.no = {_normal(w) for w in no_words if _normal(w)}
        self.clock = clock
        self._answers: queue.Queue[Any] | None = None
        self._lock = threading.Lock()
        # What was heard for the last verdict, so the hub can re-check a "yes"
        # itself instead of trusting a bare boolean ("" on timeout).
        self.last_answer = ""

    @property
    def pending(self) -> bool:
        return self._answers is not None

    def offer(self, audio: Any) -> bool:
        """Take an utterance if a question is open. Safe from any thread.

        Returns True when taken, so the caller does not also treat it as
        dictation -- a "yes" must never be typed into the document.
        """
        with self._lock:
            answers = self._answers
        if answers is None:
            return False
        answers.put(audio)
        return True

    def answer(self, text: str) -> bool | None:
        """True for yes, False for no, None for anything else."""
        said = _normal(text)
        if not said:
            return None
        # Padded so phrases match whole words: "no" is not in "know".
        if any(f" {phrase} " in f" {said} " for phrase in self.no):
            return False
        # Every word must be a yes-word; single-word yes phrases can repeat.
        if said in self.yes or all(word in self.yes for word in said.split()):
            return True
        return None

    def __call__(self, prompt: str, timeout: float) -> bool:
        self.last_answer = ""
        if not self.listening():
            log.warning("Cannot confirm %r: no open session to hear the answer.", prompt)
            return False

        question = prompt.strip().rstrip("?.!")
        self.show(f"{question}? Say yes")
        # Spoken without the word "yes" in it, so any echo that is picked up
        # cannot be mistaken for the answer.
        self.say(f"{question}?")

        answers: queue.Queue[Any] = queue.Queue()
        # Opened only now, after speaking: anything captured during the
        # question belongs to the question, not the answer.
        with self._lock:
            self._answers = answers
        deadline = self.clock() + max(0.0, timeout)
        try:
            while True:
                remaining = deadline - self.clock()
                if remaining <= 0:
                    break
                try:
                    audio = answers.get(timeout=remaining)
                except queue.Empty:
                    break
                text = self.transcribe(audio) or ""
                verdict = self.answer(text)
                if verdict is None:
                    if text.strip():
                        log.info("(confirming, ignored) %s", text.strip())
                    continue
                self.last_answer = text.strip()
                log.info("Confirmation %s: %s", "given" if verdict else "refused", text.strip())
                self.show("Confirmed" if verdict else "Cancelled")
                return verdict
        finally:
            with self._lock:
                self._answers = None
        log.info("No answer within %gs; cancelled.", timeout)
        self.show("Cancelled - no answer")
        return False
