"""Spoken confirmation.

The critical property is that only a clear yes counts as consent. Noise, other
people, and the question echoing back through the speakers must never read as
yes; a no, or silence, must always cancel.

Audio is stood in for by strings, with an identity "transcriber", so nothing
here needs a microphone or a model.
"""

from __future__ import annotations

import queue
import threading
import time
import unittest

import stubs

stubs.install()

from voicevibe.confirm import VoiceConfirmer  # noqa: E402

try:
    from voicevibe import app
except Exception:  # numpy / sounddevice / PIL missing on a bare checkout
    app = None


def confirmer(**kwargs) -> VoiceConfirmer:  # noqa: ANN003
    kwargs.setdefault("transcribe", lambda audio: audio)
    return VoiceConfirmer(**kwargs)


def reply_once_asked(c: VoiceConfirmer, *utterances: str) -> threading.Thread:
    """Say `utterances` as soon as the question is open, like a user would."""

    def speak() -> None:
        deadline = time.monotonic() + 2
        while not c.pending and time.monotonic() < deadline:
            time.sleep(0.001)
        for utterance in utterances:
            c.offer(utterance)

    thread = threading.Thread(target=speak, daemon=True)
    thread.start()
    return thread


class TestAnswers(unittest.TestCase):
    def setUp(self) -> None:
        self.c = confirmer()

    def test_yes(self) -> None:
        for said in ("yes", "Yes.", "YES!", "confirm", "Yes, confirm.", "yes yes"):
            with self.subTest(said=said):
                self.assertIs(self.c.answer(said), True)

    def test_no(self) -> None:
        for said in ("no", "No.", "cancel", "stop", "never mind", "no, don't",
                     "yes, no, wait", "Never mind that."):
            with self.subTest(said=said):
                self.assertIs(self.c.answer(said), False)

    def test_anything_else_is_not_an_answer(self) -> None:
        for said in (
            "", "   ", "...",
            "yes but not that one",       # consent has to be the whole answer
            "yes please",
            "send the message",            # the question itself, echoed back
            "I know",                      # "no" only as a whole word
            "nonsense", "yesterday",
            "the email says yes",
        ):
            with self.subTest(said=said):
                self.assertIsNone(self.c.answer(said))

    def test_words_are_configurable(self) -> None:
        c = confirmer(yes_words=["do it", "yep"], no_words=["abort"])
        self.assertIs(c.answer("Do it."), True)
        self.assertIs(c.answer("yep"), True)
        self.assertIsNone(c.answer("yes"))
        self.assertIs(c.answer("abort"), False)
        self.assertIsNone(c.answer("no"))


class TestAsking(unittest.TestCase):
    def test_yes_confirms(self) -> None:
        c = confirmer()
        reply_once_asked(c, "Yes.")
        self.assertIs(c("Send the message", 2), True)
        self.assertFalse(c.pending)

    def test_no_cancels(self) -> None:
        c = confirmer()
        reply_once_asked(c, "no")
        self.assertIs(c("Send the message", 2), False)

    def test_chatter_is_ignored_until_a_real_answer(self) -> None:
        heard: list[str] = []
        c = confirmer(transcribe=lambda audio: heard.append(audio) or audio)
        reply_once_asked(c, "send the message", "", "hang on a second", "yes")
        self.assertIs(c("Send the message", 2), True)
        self.assertEqual(heard, ["send the message", "", "hang on a second", "yes"])

    def test_silence_cancels_at_the_deadline(self) -> None:
        c = confirmer()
        started = time.monotonic()
        self.assertIs(c("Send the message", 0.05), False)
        self.assertLess(time.monotonic() - started, 1.0)
        self.assertFalse(c.pending)

    def test_chatter_does_not_extend_the_deadline(self) -> None:
        now = [0.0]

        def transcribe(audio: str) -> str:
            now[0] += 5.0  # each utterance takes "5 seconds"
            return audio

        c = confirmer(transcribe=transcribe, clock=lambda: now[0])
        reply_once_asked(c, "um", "hmm", "yes")
        # By the time "yes" would be heard, the 8s window has closed.
        self.assertIs(c("Delete it", 8), False)

    def test_speech_during_the_question_is_not_the_answer(self) -> None:
        # The prompt is spoken before listening starts, so an echo of it --
        # or anything else said over it -- is refused, not queued.
        c = confirmer(say=lambda text: offered.append(c.offer("yes")))
        offered: list[bool] = []
        self.assertIs(c("Delete it", 0.05), False)
        self.assertEqual(offered, [False])

    def test_the_spoken_question_never_contains_a_yes_word(self) -> None:
        said: list[str] = []
        shown: list[str] = []
        c = confirmer(say=said.append, show=shown.append)
        c("Send the message?", 0.01)
        self.assertEqual(said, ["Send the message?"])
        self.assertIsNone(c.answer(said[0]))
        self.assertEqual(shown[0], "Send the message? Say yes")

    def test_no_session_means_no_question(self) -> None:
        said: list[str] = []
        c = confirmer(say=said.append, listening=lambda: False)
        self.assertIs(c("Send the message", 5), False)
        self.assertEqual(said, [])

    def test_offer_is_refused_when_nothing_is_asked(self) -> None:
        self.assertFalse(confirmer().offer("yes"))


@unittest.skipIf(app is None, "app.py needs numpy, sounddevice and pillow")
class TestAppHandOff(unittest.TestCase):
    """While a question is open, session audio goes to it, never to dictation."""

    def make(self):  # noqa: ANN201
        vv = app.VoiceVibe.__new__(app.VoiceVibe)
        vv._jobs = queue.Queue()
        vv.confirmer = confirmer()
        return vv

    def test_utterances_are_dictation_normally(self) -> None:
        vv = self.make()
        vv._on_segment("hello")
        self.assertEqual(vv._jobs.get_nowait(), ("hello", app.SESSION))

    def test_the_answer_goes_to_the_open_question(self) -> None:
        vv = self.make()
        result: list[bool] = []
        asking = threading.Thread(target=lambda: result.append(vv.confirmer("Buy it", 2)))
        asking.start()
        deadline = time.monotonic() + 2
        while not vv.confirmer.pending and time.monotonic() < deadline:
            time.sleep(0.001)
        vv._on_segment("yes")
        asking.join(2)
        self.assertEqual(result, [True])
        self.assertTrue(vv._jobs.empty())


if __name__ == "__main__":
    unittest.main()
