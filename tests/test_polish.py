"""Transcript polishing.

The risk is asymmetric. Failing to add a full stop costs one keystroke; a rule
that fires inside ordinary speech silently changes what someone said. So the
"leave it alone" cases carry more weight here than the clever ones.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from voicevibe.polish import apply_edit, detect_edit, polish  # noqa: E402


class TestCapitalisation(unittest.TestCase):
    def test_first_word(self) -> None:
        self.assertEqual(polish("refactor the handler"), "Refactor the handler.")

    def test_each_sentence(self) -> None:
        self.assertEqual(
            polish("hello world. this is next"), "Hello world. This is next."
        )

    def test_standalone_i(self) -> None:
        self.assertEqual(polish("i think i'm right"), "I think I'm right.")

    def test_i_inside_a_word_is_untouched(self) -> None:
        # Only the standalone pronoun is raised, never an i within a word.
        self.assertEqual(polish("the list is big"), "The list is big.")

    def test_abbreviations_do_not_start_a_sentence(self) -> None:
        self.assertEqual(
            polish("see the docs e.g. the readme"), "See the docs e.g. the readme."
        )


class TestTermination(unittest.TestCase):
    def test_statement_gets_a_full_stop(self) -> None:
        self.assertTrue(polish("the build passed").endswith("."))

    def test_question_gets_a_question_mark(self) -> None:
        for text in ("how do i fix this", "what is next", "can you check"):
            with self.subTest(text=text):
                self.assertTrue(polish(text).endswith("?"))

    def test_existing_punctuation_is_kept(self) -> None:
        self.assertEqual(polish("already done!"), "Already done!")

    def test_no_terminator_when_disabled(self) -> None:
        self.assertEqual(polish("a fragment", terminate=False), "A fragment")

    def test_empty_input(self) -> None:
        self.assertEqual(polish(""), "")
        self.assertEqual(polish("   "), "")


class TestSpokenMarks(unittest.TestCase):
    def test_trailing_mark_is_applied(self) -> None:
        self.assertEqual(polish("this is done add a full stop"), "This is done.")

    def test_trailing_question_mark(self) -> None:
        self.assertEqual(polish("wrap it up add a question mark"), "Wrap it up?")

    def test_mid_sentence_is_left_alone(self) -> None:
        # People say this. Rewriting it would eat half the sentence.
        result = polish("i will add a comma here and then continue")
        self.assertIn("add a comma here and then continue", result)

    def test_the_word_comma_in_ordinary_speech(self) -> None:
        self.assertIn("comma separated", polish("the file is comma separated"))

    def test_bare_mark_name_is_not_swallowed(self) -> None:
        # Nothing precedes it, so it is far likelier to be a mishearing.
        self.assertEqual(polish("add a comma"), "Add a comma.")


class TestSpacing(unittest.TestCase):
    def test_no_space_before_punctuation(self) -> None:
        self.assertEqual(polish("hello , world"), "Hello, world.")

    def test_single_space_after(self) -> None:
        self.assertEqual(polish("one,two"), "One, two.")

    def test_runs_of_spaces_collapse(self) -> None:
        self.assertEqual(polish("too    many   spaces"), "Too many spaces.")


class TestEditDetection(unittest.TestCase):
    def test_recognised_edits(self) -> None:
        for phrase, expected in (
            ("scratch that", "undo"),
            ("delete that", "undo"),
            ("cap that", "capitalise"),
            ("all caps that", "upper"),
            ("lowercase that", "lower"),
            ("new paragraph", "paragraph"),
        ):
            with self.subTest(phrase=phrase):
                self.assertEqual(detect_edit(phrase), expected)

    def test_edits_only_match_the_whole_utterance(self) -> None:
        # The same words inside a sentence are dictation, not an instruction.
        for phrase in (
            "scratch that idea from the plan",
            "i want to capitalise that word",
            "add a new paragraph to the document",
        ):
            with self.subTest(phrase=phrase):
                self.assertIsNone(detect_edit(phrase))

    def test_ordinary_speech_is_never_an_edit(self) -> None:
        self.assertIsNone(detect_edit("refactor the login handler"))


class TestEditApplication(unittest.TestCase):
    def test_undo_clears(self) -> None:
        text, spoken = apply_edit("undo", "some text")
        self.assertEqual(text, "")
        self.assertTrue(spoken)

    def test_case_changes(self) -> None:
        self.assertEqual(apply_edit("upper", "hello")[0], "HELLO")
        self.assertEqual(apply_edit("lower", "HELLO")[0], "hello")

    def test_paragraph_appends_a_break(self) -> None:
        self.assertTrue(apply_edit("paragraph", "done")[0].endswith("\n\n"))

    def test_unknown_edit_is_a_no_op(self) -> None:
        self.assertEqual(apply_edit("nonsense", "keep me")[0], "keep me")


if __name__ == "__main__":
    unittest.main()
