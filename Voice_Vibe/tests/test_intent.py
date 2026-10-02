"""Intent routing and app-launch safety.

The critical property is that anything unrecognised stays dictation. A router
that swallows ordinary speech turns a working dictation tool into a broken one,
so the "this is just text" cases matter more than the clever ones.
"""

from __future__ import annotations

import unittest

import stubs

stubs.install()

from voicevibe.intent import DICTATE, Responder, _find_error, _sentences  # noqa: E402
from voicevibe.launcher import AppEntry, Launcher  # noqa: E402
from voicevibe.screen import ScreenContext  # noqa: E402


class FakeLauncher(Launcher):
    """Allowlist with known contents and no real process launching."""

    def __init__(self, names=("Google Chrome", "Blender", "File Explorer", "Excel")):
        super().__init__(apps=None, discover=False)
        from pathlib import Path

        self._entries = [AppEntry(n, Path("C:/fake") / n, source="builtin") for n in names]
        self._discovered = True
        self.launched: list[str] = []

    def launch(self, entry: AppEntry) -> bool:
        self.launched.append(entry.name)
        return True


class FakeScreen:
    def __init__(self, title="Untitled - Notepad", selection="") -> None:
        self.context = ScreenContext(title=title, selection=selection)
        self.deep_calls = 0

    def read(self, deep: bool = False) -> ScreenContext:
        self.deep_calls += int(deep)
        return self.context


class TestDictationFallthrough(unittest.TestCase):
    """Ordinary speech must never be intercepted."""

    def setUp(self) -> None:
        self.responder = Responder(launcher=FakeLauncher(), screen=FakeScreen())

    def test_plain_sentence_is_dictation(self) -> None:
        for sentence in (
            "refactor the login handler to validate the token first",
            "send the email to the team this afternoon",
            "the error was caused by a missing import",
            "I opened the file and it was empty",
            "what is the capital of France",
            "read the documentation before you start",
        ):
            with self.subTest(sentence=sentence):
                reply = self.responder.respond(sentence)
                self.assertEqual(reply.action, DICTATE)
                self.assertFalse(reply.handled)
                self.assertEqual(reply.text, sentence)

    def test_empty_input_is_dictation(self) -> None:
        self.assertEqual(self.responder.respond("   ").action, DICTATE)

    def test_disabled_responder_never_intercepts(self) -> None:
        off = Responder(launcher=FakeLauncher(), screen=FakeScreen(), cfg={"enabled": False})
        self.assertEqual(off.respond("open chrome").action, DICTATE)


class TestLaunching(unittest.TestCase):
    def setUp(self) -> None:
        self.launcher = FakeLauncher()
        self.responder = Responder(launcher=self.launcher, screen=FakeScreen())

    def test_opens_a_known_app(self) -> None:
        reply = self.responder.respond("open chrome")
        self.assertEqual(reply.action, "launch")
        self.assertEqual(self.launcher.launched, ["Google Chrome"])

    def test_accepts_alternative_verbs(self) -> None:
        for phrase in ("launch blender", "start blender", "run blender", "please open blender"):
            with self.subTest(phrase=phrase):
                FakeLauncher.launched = []
                launcher = FakeLauncher()
                Responder(launcher=launcher, screen=FakeScreen()).respond(phrase)
                self.assertEqual(launcher.launched, ["Blender"])

    def test_unknown_app_is_refused_not_launched(self) -> None:
        reply = self.responder.respond("open photoshop")
        self.assertEqual(reply.action, "control")
        self.assertEqual(self.launcher.launched, [])
        self.assertIn("don't know", reply.speak)

    def test_generic_noun_stays_dictation(self) -> None:
        # "open the file" must not launch File Explorer.
        for phrase in ("open the file", "open the document", "open a new tab", "open the menu"):
            with self.subTest(phrase=phrase):
                reply = self.responder.respond(phrase)
                self.assertEqual(reply.action, DICTATE)
                self.assertEqual(self.launcher.launched, [])

    def test_multiword_app_still_launches(self) -> None:
        reply = self.responder.respond("open file explorer")
        self.assertEqual(reply.action, "launch")
        self.assertEqual(self.launcher.launched, ["File Explorer"])

    def test_launching_can_be_disabled(self) -> None:
        off = Responder(
            launcher=self.launcher, screen=FakeScreen(), cfg={"launch_apps": False}
        )
        self.assertEqual(off.respond("open chrome").action, DICTATE)
        self.assertEqual(self.launcher.launched, [])


class TestScreenAnswers(unittest.TestCase):
    TRACEBACK = (
        "Traceback (most recent call last):\n"
        '  File "run.py", line 3, in <module>\n'
        "ModuleNotFoundError: No module named 'voicevibe'"
    )

    def test_reads_the_error_line(self) -> None:
        screen = FakeScreen(title="cmd", selection=self.TRACEBACK)
        reply = Responder(launcher=FakeLauncher(), screen=screen).respond(
            "what is this error"
        )
        self.assertEqual(reply.action, "screen")
        self.assertIn("ModuleNotFoundError", reply.speak)

    def test_window_question_does_not_touch_the_clipboard(self) -> None:
        # "where am I" only needs the title, so it must not trigger a Ctrl+C.
        screen = FakeScreen(title="Visual Studio Code")
        reply = Responder(launcher=FakeLauncher(), screen=screen).respond("where am i")
        self.assertEqual(screen.deep_calls, 0)
        self.assertIn("Visual Studio Code", reply.speak)

    def test_read_this_returns_the_selection(self) -> None:
        screen = FakeScreen(selection="the quick brown fox")
        reply = Responder(launcher=FakeLauncher(), screen=screen).respond("read this")
        self.assertIn("quick brown fox", reply.speak)

    def test_empty_screen_says_so_without_crashing(self) -> None:
        screen = FakeScreen(title="Notepad", selection="")
        reply = Responder(launcher=FakeLauncher(), screen=screen).respond(
            "what's on my screen"
        )
        self.assertEqual(reply.action, "screen")
        self.assertIn("Notepad", reply.speak)

    def test_screen_answers_can_be_disabled(self) -> None:
        off = Responder(
            launcher=FakeLauncher(),
            screen=FakeScreen(selection="x"),
            cfg={"answer_screen": False},
        )
        self.assertEqual(off.respond("what's on my screen").action, DICTATE)


class TestExtraction(unittest.TestCase):
    def test_find_error_prefers_the_real_message(self) -> None:
        found = _find_error(TestScreenAnswers.TRACEBACK)
        self.assertIn("ModuleNotFoundError", found)

    def test_find_error_returns_empty_for_ordinary_text(self) -> None:
        self.assertEqual(_find_error("the weather is nice today\nand tomorrow"), "")

    def test_sentences_truncates_long_text(self) -> None:
        out = _sentences("word " * 300, max_chars=80)
        self.assertLessEqual(len(out), 84)
        self.assertTrue(out.endswith("..."))

    def test_sentences_keeps_short_text_intact(self) -> None:
        self.assertEqual(_sentences("All done."), "All done.")


class TestLauncherSafety(unittest.TestCase):
    def test_skips_uninstallers_during_discovery(self) -> None:
        from voicevibe.launcher import _SKIP

        for label in ("Uninstall Blender", "Blender Readme", "Repair Office"):
            with self.subTest(label=label):
                self.assertTrue(any(s in label.lower() for s in _SKIP))

    def test_resolve_refuses_when_nothing_is_close(self) -> None:
        self.assertIsNone(FakeLauncher().resolve("totally fictional program"))

    def test_resolve_is_case_and_punctuation_insensitive(self) -> None:
        entry = FakeLauncher().resolve("Google, Chrome!")
        self.assertIsNotNone(entry)
        assert entry is not None
        self.assertEqual(entry.name, "Google Chrome")

    def test_empty_name_resolves_to_nothing(self) -> None:
        self.assertIsNone(FakeLauncher().resolve("   "))


if __name__ == "__main__":
    unittest.main()
