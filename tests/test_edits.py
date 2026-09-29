"""Spoken edits of the previous utterance, and opt-in word replacements.

What matters: both are off unless asked for, an edit only claims an
utterance it can act on (anything else is typed), and an edit touches only
the part of the text that changes.
"""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest import mock

import stubs

stubs.install()

from voicevibe.inserter import Inserter, apply_replacements  # noqa: E402
from voicevibe.polish import apply_edit, detect_edit, edit_applies, parse_edit  # noqa: E402

try:
    from voicevibe import app
except Exception:  # numpy / sounddevice / PIL missing on a bare checkout
    app = None


class TestParsing(unittest.TestCase):
    def test_word_deletions(self) -> None:
        for said, count in (
            ("delete the last word", 1), ("Delete last word.", 1), ("remove the last two words", 2),
            ("erase last 3 words", 3), ("scratch the last word", 1),
        ):
            with self.subTest(said=said):
                self.assertEqual(parse_edit(said), ("delete_words", {"count": count}))

    def test_replace(self) -> None:
        self.assertEqual(parse_edit("Replace Tuesday with Wednesday."),
                         ("replace", {"find": "Tuesday", "replace": "Wednesday"}))

    def test_not_edits(self) -> None:
        for said in (
            "change the meeting to Friday",     # dictated, not an instruction
            "delete the last paragraph of the report",
            "we should replace the filter",
            "the last word on the subject",
        ):
            with self.subTest(said=said):
                self.assertIsNone(parse_edit(said))

    def test_old_names_still_work(self) -> None:
        self.assertEqual(detect_edit("scratch that"), "undo")
        self.assertEqual(detect_edit("delete the last word"), "delete_words")


class TestApplying(unittest.TestCase):
    def test_delete_words(self) -> None:
        self.assertEqual(apply_edit("delete_words", "Meet at three pm. ", count=1)[0],
                         "Meet at three ")
        self.assertEqual(apply_edit("delete_words", "Meet at three pm.", count=2)[0], "Meet at")
        self.assertEqual(apply_edit("delete_words", "Hello. ", count=5)[0], "")

    def test_replace_last_whole_word(self) -> None:
        text, spoken = apply_edit("replace", "Tuesday, then Tuesday again. ",
                                  find="tuesday", replace="Wednesday")
        self.assertEqual(text, "Tuesday, then Wednesday again. ")
        self.assertEqual(spoken, "Replaced.")
        self.assertEqual(apply_edit("replace", "a category", find="cat", replace="dog")[0],
                         "a category")

    def test_applies_only_when_the_word_is_there(self) -> None:
        self.assertTrue(edit_applies("replace", "Meet Tuesday. ", find="Tuesday"))
        self.assertFalse(edit_applies("replace", "Meet Tuesday. ", find="Friday"))
        self.assertTrue(edit_applies("undo", "x"))
        self.assertFalse(edit_applies("undo", ""))


class TestReplacements(unittest.TestCase):
    RULES = [{"find": "pie torch", "replace": "PyTorch"}, {"find": "cat", "replace": "dog"}]

    def test_whole_words_any_case(self) -> None:
        self.assertEqual(apply_replacements("I use Pie Torch daily", self.RULES),
                         "I use PyTorch daily")
        self.assertEqual(apply_replacements("a category of cat", self.RULES),
                         "a category of dog")

    def test_off_by_default_on_when_asked(self) -> None:
        cfg = {"polish": False, "add_trailing_space": False}
        self.assertEqual(Inserter(cfg, self.RULES).prepare("pie torch")[0], "pie torch")
        on = Inserter({**cfg, "apply_replacements": True}, self.RULES)
        self.assertEqual(on.prepare("pie torch")[0], "PyTorch")


class FakeInserter:
    def __init__(self) -> None:
        self.ops: list[tuple[str, object]] = []

    def erase(self, count: int) -> None:
        self.ops.append(("erase", count))

    def insert_literal(self, text: str) -> None:
        self.ops.append(("type", text))

    def insert(self, text: str) -> tuple[str, list]:
        self.ops.append(("dictate", text))
        return text, []


class _Quiet:
    def __getattr__(self, name: str):  # noqa: ANN204
        return lambda *a, **k: None


@unittest.skipIf(app is None, "app.py needs numpy, sounddevice and pillow")
class TestAppEdits(unittest.TestCase):
    PREVIOUS = "Meet on Tuesday at noon. "

    def say(self, text: str, on: bool = True, previous: str = PREVIOUS):  # noqa: ANN201
        vv = app.VoiceVibe.__new__(app.VoiceVibe)
        vv.config = SimpleNamespace(output={}, control={"spoken_edits": on}, feedback={})
        vv.inserter = FakeInserter()
        vv._last_inserted = previous
        vv.history = vv.overlay = vv.beeper = vv.voice = _Quiet()
        vv.router = _Quiet()
        vv.executor = app.Executor(keyboard=stubs.FakeController(),
                                   confirmer=lambda *args: True)
        vv.responder = SimpleNamespace(respond=lambda text: SimpleNamespace(handled=False))
        with mock.patch.object(app, "focused_window", lambda: "Notepad"):
            if not vv._do_session_extra(text, "computer " + text, 0.1):
                vv._do_insert(text, 0.1)
        return vv

    def test_replace_touches_only_the_changed_tail(self) -> None:
        vv = self.say("replace Tuesday with Wednesday")
        # "Meet on " is kept; "Tuesday at noon. " (17 chars) is redone.
        self.assertEqual(vv.inserter.ops, [("erase", 17), ("type", "Wednesday at noon. ")])
        self.assertEqual(vv._last_inserted, "Meet on Wednesday at noon. ")

    def test_delete_last_word(self) -> None:
        vv = self.say("delete the last word")
        self.assertEqual(vv.inserter.ops, [("erase", 6), ("type", "")])
        self.assertEqual(vv._last_inserted, "Meet on Tuesday at ")

    def test_scratch_that_erases_everything(self) -> None:
        vv = self.say("scratch that")
        self.assertEqual(vv.inserter.ops, [("erase", 25), ("type", "")])
        self.assertEqual(vv._last_inserted, "")

    def test_off_means_typed(self) -> None:
        vv = self.say("scratch that", on=False)
        self.assertEqual(vv.inserter.ops, [("dictate", "scratch that")])

    def test_replace_of_a_missing_word_is_dictation(self) -> None:
        vv = self.say("replace the filter with a new one")
        self.assertEqual(vv.inserter.ops, [("dictate", "replace the filter with a new one")])

    def test_nothing_to_edit_is_dictation(self) -> None:
        vv = self.say("scratch that", previous="")
        self.assertEqual(vv.inserter.ops, [("dictate", "scratch that")])


if __name__ == "__main__":
    unittest.main()
