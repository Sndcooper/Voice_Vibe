"""Voice-control typing words (Ctrl+Alt+W sessions only).

Plain dictation keeps its rule: only a separate "press enter" sends Enter.
"""

from __future__ import annotations

import unittest

import stubs

stubs.install()

from voicevibe.inserter import Inserter, is_session_typing, session_steps, strip_type  # noqa: E402


def _enters(inserter: Inserter) -> int:
    return sum(1 for kind, key in inserter.keyboard.events
               if kind == "press" and getattr(key, "name", key) == "enter")


def _typed(inserter: Inserter) -> str:
    return "".join(value for kind, value in inserter.keyboard.events if kind == "type")


class ParserTests(unittest.TestCase):
    def test_steps(self) -> None:
        self.assertEqual(session_steps("Type Claude, press enter."),
                         ([("Type Claude", "press enter")], ""))
        self.assertEqual(session_steps("Claude, and enter.")[0][0][0], "Claude")
        self.assertEqual(len(session_steps("Press enter, press enter.")[0]), 2)
        self.assertEqual(session_steps("git status, hit return, then clear")[1], "then clear")
        self.assertEqual(session_steps("when done, press the enter key")[0][0][0], "when done")

    def test_not_a_submit(self) -> None:
        for text in ("press enter to continue", "the enter key is broken",
                     "I will enter the room", "Press Enter keys everywhere", ""):
            self.assertEqual(session_steps(text)[0], [], text)

    def test_type_word(self) -> None:
        self.assertEqual(strip_type("type git status"), "git status")
        self.assertEqual(strip_type("Please type hello"), "hello")
        self.assertEqual(strip_type("typewriters are loud"), "typewriters are loud")
        self.assertTrue(is_session_typing("type hello"))
        self.assertTrue(is_session_typing("hello, press enter"))
        self.assertFalse(is_session_typing("open terminal"))
        self.assertFalse(is_session_typing("open terminal and type ls, press enter"))


class InsertSessionTests(unittest.TestCase):
    def make(self) -> Inserter:
        return Inserter({"mode": "type", "command_delay": 0}, [])

    def test_text_then_enter(self) -> None:
        ins = self.make()
        inserted, fired = ins.insert_session("Type Claude, press enter.")
        self.assertEqual(_typed(ins), "Claude")
        self.assertEqual(_enters(ins), 1)
        self.assertEqual([f["keys"] for f in fired], ["enter"])
        self.assertTrue(fired[0]["ends_dictation"])

    def test_two_submits_and_a_tail(self) -> None:
        ins = self.make()
        ins.insert_session("ls, press enter, git status, press enter, and more words")
        self.assertEqual(_enters(ins), 2)
        self.assertIn("more words", _typed(ins))

    def test_type_without_submit(self) -> None:
        ins = self.make()
        inserted, fired = ins.insert_session("type hello world")
        self.assertEqual(fired, [])
        self.assertTrue(_typed(ins).lower().startswith("hello world"))

    def test_plain_insert_is_unchanged(self) -> None:
        ins = self.make()
        ins.insert("Type Claude, press enter.")
        self.assertEqual(_enters(ins), 0)
        self.assertIn("press enter", _typed(ins).lower())


if __name__ == "__main__":
    unittest.main()
