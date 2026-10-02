"""Wake matching. Non-matches matter as much as matches: a false wake types
whatever was said next into whatever had focus.

Stdlib only, so this suite runs before any dependency is installed.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from voicevibe.wake import PhraseMatcher  # noqa: E402

PHRASES = ["hey computer", "okay computer", "ok computer"]


class TestExactMatching(unittest.TestCase):
    def setUp(self) -> None:
        self.matcher = PhraseMatcher(PHRASES)

    def test_matches_bare_phrase(self) -> None:
        self.assertTrue(self.matcher.matches("hey computer"))

    def test_ignores_case_and_punctuation(self) -> None:
        self.assertTrue(self.matcher.matches("Hey, Computer!"))

    def test_matches_mid_sentence(self) -> None:
        self.assertTrue(self.matcher.matches("so hey computer open the file"))

    def test_rejects_partial_phrase(self) -> None:
        self.assertFalse(self.matcher.matches("the computer is slow"))

    def test_rejects_unrelated_speech(self) -> None:
        self.assertFalse(self.matcher.matches("I was talking to my colleague"))

    def test_rejects_substring_of_longer_word(self) -> None:
        self.assertFalse(PhraseMatcher(["arise"]).matches("arisen from the dead"))


class TestSplit(unittest.TestCase):
    def setUp(self) -> None:
        self.matcher = PhraseMatcher(PHRASES)

    def test_returns_remainder_after_phrase(self) -> None:
        woke, rest = self.matcher.split("hey computer refactor the login handler")
        self.assertTrue(woke)
        self.assertEqual(rest, "refactor the login handler")

    def test_strips_punctuation_after_phrase(self) -> None:
        _, rest = self.matcher.split("hey computer, send the email")
        self.assertEqual(rest, "send the email")

    def test_drops_text_before_the_phrase(self) -> None:
        _, rest = self.matcher.split("um so anyway hey computer open blender")
        self.assertEqual(rest, "open blender")

    def test_no_match_returns_text_untouched(self) -> None:
        woke, rest = self.matcher.split("just dictating normally")
        self.assertFalse(woke)
        self.assertEqual(rest, "just dictating normally")

    def test_bare_phrase_leaves_empty_remainder(self) -> None:
        woke, rest = self.matcher.split("hey computer")
        self.assertTrue(woke)
        self.assertEqual(rest.strip(), "")


class TestFuzzyMatching(unittest.TestCase):
    """Fuzzy absorbs the two things Whisper does to short phrases: splitting a
    word and swapping a letter. It must not start matching ordinary speech."""

    def setUp(self) -> None:
        self.matcher = PhraseMatcher(PHRASES, fuzzy=0.82)

    def test_absorbs_letter_swap(self) -> None:
        self.assertTrue(self.matcher.matches("hey computor"))

    def test_absorbs_split_word(self) -> None:
        self.assertTrue(PhraseMatcher(["arise"], fuzzy=0.82).matches("a rise"))

    def test_single_word_does_not_match_two_word_phrase(self) -> None:
        # "computer" scores ~0.84 against "heycomputer"; word alignment must
        # stop that from waking on ordinary speech.
        self.assertFalse(self.matcher.matches("the computer is slow today"))

    def test_does_not_match_unrelated_sentence(self) -> None:
        for sentence in (
            "let me commute here",
            "I need to compute the average",
            "hey can you hear me",
            "okay so the next step",
        ):
            with self.subTest(sentence=sentence):
                self.assertFalse(self.matcher.matches(sentence))


class TestSleepPhrases(unittest.TestCase):
    def test_longest_phrase_wins(self) -> None:
        matcher = PhraseMatcher(["sleep", "go to sleep"])
        span = matcher.find("please go to sleep")
        self.assertIsNotNone(span)
        assert span is not None
        self.assertEqual("please go to sleep"[span[0] : span[1]], "go to sleep")

    def test_empty_matcher_is_falsy_and_never_matches(self) -> None:
        matcher = PhraseMatcher([])
        self.assertFalse(matcher)
        self.assertFalse(matcher.matches("anything at all"))


if __name__ == "__main__":
    unittest.main()
