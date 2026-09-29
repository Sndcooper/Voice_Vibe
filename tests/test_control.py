"""Command routing inside a session.

The critical property is the same as for intents: anything that is not a
command stays dictation. Here that means the prefix must lead the utterance,
and a command the router does not handle is typed exactly as it was heard.
"""

from __future__ import annotations

import unittest

import stubs

stubs.install()

from voicevibe.config import DEFAULTS  # noqa: E402
from voicevibe.control import NOT_HANDLED, Route, Router  # noqa: E402
from voicevibe.wake import PhraseMatcher  # noqa: E402

try:
    from voicevibe import app
except Exception:  # numpy / sounddevice / PIL missing on a bare checkout
    app = None


def router(**cfg) -> Router:  # noqa: ANN003
    return Router({"enabled": True, **cfg})


class TestPrefixGate(unittest.TestCase):
    """Only a leading prefix makes an utterance a command."""

    def setUp(self) -> None:
        self.router = router()

    def test_leading_prefix_is_a_command(self) -> None:
        for said, command in (
            ("computer open chrome", "open chrome"),
            ("Computer, open Chrome.", "open Chrome."),
            ("COMPUTER: next tab", "next tab"),
            ("  computer -- scroll down", "scroll down"),
        ):
            with self.subTest(said=said):
                self.assertEqual(self.router.split(said), command)

    def test_prefix_later_in_the_sentence_is_dictation(self) -> None:
        for sentence in (
            "the computer is slow today",
            "restart the computer before the demo",
            "hey computer open chrome",
            "my computer, not yours",
        ):
            with self.subTest(sentence=sentence):
                self.assertIsNone(self.router.split(sentence))

    def test_prefix_inside_a_longer_word_is_dictation(self) -> None:
        for sentence in ("computers are cheap now", "computerised records", "compute the total"):
            with self.subTest(sentence=sentence):
                self.assertIsNone(self.router.split(sentence))

    def test_plain_sentence_is_dictation(self) -> None:
        for sentence in (
            "refactor the login handler to validate the token first",
            "open the file and read it",
            "",
            "   ",
        ):
            with self.subTest(sentence=sentence):
                self.assertIsNone(self.router.split(sentence))

    def test_bare_prefix_is_an_empty_command(self) -> None:
        self.assertEqual(self.router.split("Computer."), "")

    def test_custom_prefixes(self) -> None:
        custom = router(prefixes=["jarvis", "hey machine"])
        self.assertEqual(custom.split("jarvis save"), "save")
        self.assertEqual(custom.split("hey machine, save"), "save")
        self.assertIsNone(custom.split("computer save"))

    def test_a_single_string_prefix_is_accepted(self) -> None:
        self.assertEqual(router(prefixes="jarvis").split("jarvis save"), "save")


class TestDisabled(unittest.TestCase):
    def test_off_by_default(self) -> None:
        self.assertFalse(Router().enabled)
        self.assertFalse(Router(DEFAULTS["control"]).enabled)

    def test_disabled_router_never_intercepts(self) -> None:
        off = Router({"enabled": False})
        self.assertIsNone(off.split("computer open chrome"))

    def test_no_prefixes_disables_it(self) -> None:
        empty = router(prefixes=[])
        self.assertFalse(empty.enabled)
        self.assertIsNone(empty.split("computer open chrome"))


class RecordingRouter(Router):
    """Handles exactly the commands it is given, and remembers what it saw."""

    def __init__(self, handles=(), ends_dictation=False) -> None:  # noqa: ANN001
        super().__init__({"enabled": True})
        self.handles = set(handles)
        self.ends_dictation = ends_dictation
        self.seen: list[str] = []

    def route(self, command: str) -> Route:
        self.seen.append(command)
        if command in self.handles:
            return Route(handled=True, caption=command, ends_dictation=self.ends_dictation)
        return NOT_HANDLED


class _Quiet:
    """Absorbs any call: beeper, overlay, history, indicators."""

    def __getattr__(self, name: str):  # noqa: ANN204
        return lambda *a, **k: None


@unittest.skipIf(app is None, "app.py needs numpy, sounddevice and pillow")
class TestSessionWiring(unittest.TestCase):
    """_do_session sends prefixed utterances to the router and types the rest."""

    def make(self, router: Router, wake: bool = True):  # noqa: ANN201
        vv = app.VoiceVibe.__new__(app.VoiceVibe)
        vv.router = router
        vv.wake_enabled = wake
        vv._wake_state = app.DICTATING
        vv.wake_matcher = PhraseMatcher(["hey computer"])
        vv.sleep_matcher = PhraseMatcher(["never mind"])
        vv._last_activity = 0.0
        vv._ends_dictation = False
        vv.beeper = vv.overlay = vv.history = _Quiet()
        vv.armed_reasons = []
        vv._do_session_extra = lambda *args: False
        vv._arm = vv.armed_reasons.append
        vv.inserted = []
        vv._do_insert = lambda text, elapsed, **kwargs: vv.inserted.append(text)
        return vv

    def test_unhandled_command_is_typed_as_heard(self) -> None:
        r = RecordingRouter()
        vv = self.make(r)
        vv._do_session("Computer, open Chrome.", 0.1)
        self.assertEqual(r.seen, ["open Chrome."])
        self.assertEqual(vv.inserted, ["Computer, open Chrome."])

    def test_handled_command_is_not_typed(self) -> None:
        vv = self.make(RecordingRouter(handles={"open chrome"}))
        vv._do_session("computer open chrome", 0.1)
        self.assertEqual(vv.inserted, [])

    def test_handled_command_can_end_dictation(self) -> None:
        vv = self.make(RecordingRouter(handles={"submit"}, ends_dictation=True))
        vv._do_session("computer submit", 0.1)
        self.assertEqual(vv.armed_reasons, ["submitted"])

    def test_plain_dictation_never_reaches_the_router(self) -> None:
        r = RecordingRouter()
        vv = self.make(r)
        vv._do_session("the computer is slow today", 0.1)
        self.assertEqual(r.seen, [])
        self.assertEqual(vv.inserted, ["the computer is slow today"])

    def test_disabled_control_types_everything(self) -> None:
        vv = self.make(Router({"enabled": False}))
        vv._do_session("computer open chrome", 0.1)
        self.assertEqual(vv.inserted, ["computer open chrome"])

    def test_works_without_a_wake_phrase(self) -> None:
        vv = self.make(RecordingRouter(handles={"open chrome"}), wake=False)
        vv._do_session("computer open chrome", 0.1)
        vv._do_session("hello there", 0.1)
        self.assertEqual(vv.inserted, ["hello there"])

    def test_sleep_phrase_still_wins(self) -> None:
        r = RecordingRouter()
        vv = self.make(r)
        vv._do_session("computer never mind", 0.1)
        self.assertEqual(r.seen, [])
        self.assertEqual(vv.armed_reasons, ["sleep phrase"])
        self.assertEqual(vv.inserted, [])


if __name__ == "__main__":
    unittest.main()
