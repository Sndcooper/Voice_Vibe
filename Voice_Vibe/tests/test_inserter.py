"""Standalone Enter commands and basic polishing.

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

OUTPUT = {"raw_dictation": False, "mode": "paste", "voice_commands": True, "add_trailing_space": True}


def make(**overrides: object) -> Inserter:
    cfg = dict(OUTPUT)
    cfg.update(overrides)
    return Inserter(cfg, [], COMMANDS)


class TestCommandExtraction(unittest.TestCase):
    def test_standalone_press_enter_only(self):
        for text in ("press enter", "Press Enter.", "PRESS ENTER!", " press   enter? "):
            with self.subTest(text=text):
                body, commands = make().prepare(text)
                self.assertEqual(body, "")
                self.assertEqual([c["keys"] for c in commands], ["enter"])
                self.assertTrue(commands[0]["ends_dictation"])

    def test_sentence_mentions_and_old_commands_never_send_keys(self):
        for text in ("enter", "send it", "submit", "next field", "scratch that",
                     "please press enter", "press enter to continue",
                     "when done press enter", "done. Press enter.",
                     "press enter press enter", 'say "press enter"',
                     "open calculator", "point one bread point two milk"):
            with self.subTest(text=text):
                body, commands = make().prepare(text)
                self.assertTrue(body.strip())
                self.assertEqual(commands, [])
                self.assertNotIn("\n", body)

    def test_disabled_commands_preserve_words(self):
        body, commands = make(voice_commands=False).prepare("press enter")
        self.assertEqual(body.strip(), "Press enter.")
        self.assertEqual(commands, [])

    def test_raw_dictation_bypasses_polish_and_commands(self):
        self.assertEqual(make(raw_dictation=True).prepare("press enter"), ("press enter", []))


class TestTextShaping(unittest.TestCase):
    def test_basic_polish(self):
        self.assertEqual(make().prepare("hello    world")[0], "Hello world. ")
        self.assertEqual(make().prepare("how do i fix this")[0], "How do I fix this? ")

    def test_legacy_lists_and_replacements_are_ignored(self):
        inserter = Inserter(dict(OUTPUT, format_lists=True),
                            [{"find": "new line", "replace": "\n"}], COMMANDS)
        self.assertEqual(inserter.prepare("first new line second")[0],
                         "First new line second. ")
        self.assertEqual(inserter.prepare("point one bread point two milk")[0],
                         "Point one bread point two milk. ")

    def test_spoken_punctuation_words_are_preserved(self):
        self.assertEqual(make().prepare("remember to add a comma")[0],
                         "Remember to add a comma. ")

    def test_polish_can_be_disabled(self):
        self.assertEqual(make(polish=False).prepare("hello world")[0], "hello world ")

    def test_speak_path_uses_basic_polish(self):
        self.assertEqual(make().polish("hello world"), "Hello world. ")

    def test_empty_text_stays_empty(self):
        self.assertEqual(make().prepare("   "), ("", []))

    def test_standalone_command_sends_one_enter_without_pasting(self):
        from unittest.mock import Mock
        inserter = make(command_delay=0)
        inserter.press = Mock(return_value=True)
        inserter._paste = Mock()
        body, commands = inserter.insert("Press enter.")
        inserter.press.assert_called_once_with("enter")
        inserter._paste.assert_not_called()
        self.assertEqual(body, "")
        self.assertEqual(len(commands), 1)

    def test_sentence_is_pasted_without_sending_enter(self):
        from unittest.mock import Mock
        inserter = make(command_delay=0)
        inserter.press = Mock()
        inserter._paste = Mock()
        inserter.insert("after editing press enter")
        inserter.press.assert_not_called()
        inserter._paste.assert_called_once_with("After editing press enter. ")


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
