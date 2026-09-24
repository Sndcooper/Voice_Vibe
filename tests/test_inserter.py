"""Trailing voice-command extraction.

The risk here is asymmetric: failing to detect "enter" means you press a key
yourself, but a false detection presses Enter in the middle of someone's
sentence and submits a half-written message. Non-matches are the real tests.
"""

from __future__ import annotations

import unittest

import stubs

stubs.install()

from voicevibe.inserter import Inserter, _resolve_keys  # noqa: E402

COMMANDS = [
    {"say": "enter", "keys": "enter", "ends_dictation": True},
    {"say": "send it", "keys": "enter", "ends_dictation": True},
    {"say": "submit", "keys": "enter", "ends_dictation": True},
    {"say": "next field", "keys": "tab", "ends_dictation": False},
]

OUTPUT = {"mode": "paste", "voice_commands": True, "add_trailing_space": True}


def make(**overrides: object) -> Inserter:
    cfg = dict(OUTPUT)
    cfg.update(overrides)
    return Inserter(cfg, [], COMMANDS)


class TestCommandExtraction(unittest.TestCase):
    def setUp(self) -> None:
        self.inserter = make()

    def test_trailing_command_is_peeled_off(self) -> None:
        body, fired = self.inserter.prepare("refactor the login handler enter")
        self.assertEqual(body, "refactor the login handler")
        self.assertEqual([c["keys"] for c in fired], ["enter"])

    def test_bare_command_yields_no_text(self) -> None:
        body, fired = self.inserter.prepare("enter")
        self.assertEqual(body, "")
        self.assertEqual(len(fired), 1)

    def test_command_inside_a_word_is_ignored(self) -> None:
        body, fired = self.inserter.prepare("please re-enter your password")
        self.assertEqual(fired, [])
        self.assertIn("re-enter", body)

    def test_command_not_at_the_end_is_ignored(self) -> None:
        body, fired = self.inserter.prepare("press enter to continue")
        self.assertEqual(fired, [])
        self.assertIn("enter", body)

    def test_trailing_punctuation_does_not_block_a_match(self) -> None:
        _, fired = self.inserter.prepare("ship the release, enter.")
        self.assertEqual(len(fired), 1)

    def test_filler_comma_before_command_is_dropped(self) -> None:
        body, _ = self.inserter.prepare("ship the release, enter")
        self.assertEqual(body, "ship the release")

    def test_longest_matching_phrase_wins(self) -> None:
        body, fired = self.inserter.prepare("write the summary send it")
        self.assertEqual(body, "write the summary")
        self.assertEqual(len(fired), 1)
        self.assertEqual(fired[0]["say"], "send it")

    def test_repeated_commands_all_fire(self) -> None:
        body, fired = self.inserter.prepare("done enter enter")
        self.assertEqual(body, "done")
        self.assertEqual(len(fired), 2)

    def test_disabled_voice_commands_leave_text_alone(self) -> None:
        body, fired = make(voice_commands=False).prepare("all done enter")
        self.assertEqual(fired, [])
        self.assertIn("enter", body)

    def test_ends_dictation_flag_is_preserved(self) -> None:
        _, fired = self.inserter.prepare("username next field")
        self.assertEqual(len(fired), 1)
        self.assertFalse(fired[0]["ends_dictation"])


class TestTextShaping(unittest.TestCase):
    def test_trailing_space_added_for_plain_text(self) -> None:
        body, _ = make().prepare("hello world")
        self.assertTrue(body.endswith(" "))

    def test_no_trailing_space_before_a_command(self) -> None:
        # A space before Enter can submit a message with a stray trailing blank.
        body, _ = make().prepare("hello world enter")
        self.assertFalse(body.endswith(" "))

    def test_replacements_apply(self) -> None:
        inserter = Inserter(dict(OUTPUT), [{"find": "new line", "replace": "\n"}], [])
        body, _ = inserter.prepare("first new line second")
        self.assertEqual(body.strip(), "first\nsecond")

    def test_lowercase_option(self) -> None:
        body, _ = make(lowercase=True).prepare("Hello World")
        self.assertEqual(body.strip(), "hello world")

    def test_strip_trailing_period(self) -> None:
        body, _ = make(strip_trailing_period=True).prepare("hello world.")
        self.assertEqual(body.strip(), "hello world")

    def test_empty_input_stays_empty(self) -> None:
        body, fired = make().prepare("   ")
        self.assertEqual(body, "")
        self.assertEqual(fired, [])


class TestKeyResolution(unittest.TestCase):
    def test_plain_key(self) -> None:
        modifiers, main = _resolve_keys("enter")
        self.assertEqual(modifiers, [])
        self.assertIsNotNone(main)

    def test_combo_splits_modifiers(self) -> None:
        modifiers, main = _resolve_keys("ctrl+shift+s")
        self.assertEqual(len(modifiers), 2)
        self.assertEqual(main, "s")

    def test_unknown_key_returns_no_main(self) -> None:
        _, main = _resolve_keys("nonsense_key")
        self.assertIsNone(main)


if __name__ == "__main__":
    unittest.main()
